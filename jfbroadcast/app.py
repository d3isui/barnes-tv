"""Ties the pieces together and runs background maintenance."""
import io
import logging
import os
import socket
import threading
import time

from .cast import CastManager
from .config import Store, find_ffmpeg, find_fonts, ffmpeg_version
from .ffmpeg import Builder
from . import fontlib, themes
from .weather import WeatherService
from .adsplit import AdSplitter
from . import branding, loudness
from .graphics import Fonts, font_set
from .hls import HLSManager
from .lock import ChannelLock
from .scheduler import ScheduleManager
from .streamer import Sessions

log = logging.getLogger("app")


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class App:
    def __init__(self, data_dir, port):
        self.store = Store(data_dir)
        branding.init(self.store)
        fontlib.USER_DIR[0] = self.store.data_dir / "fonts"
        try:
            (self.store.data_dir / "fonts").mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        self.port = port
        self.sched = ScheduleManager(self.store)
        self.sessions = Sessions(self)
        self.hls = HLSManager(self)
        self.cast = CastManager(self)
        self.lock = ChannelLock(self.store)
        self.weather = WeatherService(self)
        self.adsplit = AdSplitter(self)
        self.sched.splitter = self.adsplit
        self._fonts = (None, None)
        self._header_cache = {}
        self._ffmpeg = (None, None)
        self.stop_evt = threading.Event()
        self.started = time.time()
        self.restart_requested = False
        self.shutdown_hook = None

    def restart(self):
        """Full restart (Settings -> Restart server): remember which TVs were casting what, stop everything
        cleanly, and exit so the supervisor starts a fresh server."""
        import json
        try:
            casting = {uid: p["cid"] for uid, p in self.cast.playing.items()}
            (self.store.data_dir / "state").mkdir(parents=True, exist_ok=True)
            (self.store.data_dir / "state" / "restart.json").write_text(
                json.dumps({"t": time.time(), "casting": casting}), encoding="utf-8")
        except Exception as e:
            log.warning("couldn't save casting state: %s", e)
        self.restart_requested = True
        if self.shutdown_hook:
            threading.Timer(0.4, self.shutdown_hook).start()

    def ffmpeg_path(self):
        key = self.store.settings.get("ffmpeg_path", "")
        if self._ffmpeg[0] != key:
            mem = self.store.data_dir / "state" / "ffmpeg-path.txt"
            try:
                remembered = mem.read_text(encoding="utf-8").strip() if mem.exists() else ""
            except OSError:
                remembered = ""
            found = find_ffmpeg(key, remembered)
            self._ffmpeg = (key, found)
            if os.path.isabs(found) and os.path.isfile(found) and found != remembered:
                try:
                    mem.parent.mkdir(parents=True, exist_ok=True)
                    mem.write_text(found, encoding="utf-8")
                except OSError:
                    pass
        return self._ffmpeg[1]

    def ffmpeg_supports(self, option):
        """Whether this ffmpeg build knows a command-line option (checked once per ffmpeg path)."""
        path = self.ffmpeg_path()
        cache = getattr(self, "_ff_opts", None)
        if not cache or cache[0] != path:
            import subprocess
            from .config import NO_WINDOW
            try:
                out = subprocess.run([path, "-hide_banner", "-h", "long"], capture_output=True, text=True,
                                     timeout=20, creationflags=NO_WINDOW).stdout
            except Exception:
                out = ""
            self._ff_opts = cache = (path, out)
        return f"-{option}" in cache[1]

    def ffmpeg_has_filter(self, name):
        """Whether this ffmpeg build has a filter (e.g. 'subtitles' needs libass)."""
        path = self.ffmpeg_path()
        cache = getattr(self, "_ff_filters", None)
        if not cache or cache[0] != path:
            import subprocess
            from .config import NO_WINDOW
            try:
                out = subprocess.run([path, "-hide_banner", "-filters"], capture_output=True, text=True,
                                     timeout=20, creationflags=NO_WINDOW).stdout
            except Exception:
                out = ""
            self._ff_filters = cache = (path, {ln.split()[1] for ln in out.splitlines() if len(ln.split()) > 2})
        return name in cache[1]

    def ffmpeg_info(self):
        p = self.ffmpeg_path()
        return {"path": p, "version": ffmpeg_version(p)}

    def font_paths(self):
        return find_fonts(self.store.settings)

    def fonts(self):
        paths = self.font_paths()
        key = tuple(sorted(paths.items()))
        if self._fonts[0] != key:
            self._fonts = (key, Fonts(paths))
        return self._fonts[1]

    def font_set(self, font_id):
        """Pillow fonts for a font id from the library ("system" = the OS fonts)."""
        return font_set(font_id, self.fonts())

    def theme(self, ch=None):
        """The theme a channel uses: its own choice, else the station theme."""
        return themes.get((ch or {}).get("theme") or self.store.settings.get("theme"))

    def brand_changed(self):
        """Branding edited: the guide and weather channels restyle themselves; slates are re-rendered on demand."""
        log.info("branding is now %s (%s)", branding.name(), branding.short())

    def header_logo(self, ch):
        """What the guide / weather channel draws in its top-left corner:
        {"mode", "image" (PIL RGBA or None), "size", "recolor", "key"}. Falls back to the station mark."""
        from PIL import Image
        from .config import HEADER_LOGO_DEFAULT
        from .graphics import default_logo
        hl = dict(HEADER_LOGO_DEFAULT, **((ch or {}).get("header_logo") or {}))
        mode = hl["mode"] if hl["mode"] in ("station", "channel", "custom", "name", "none") else "station"
        out = {"mode": mode, "image": None, "size": max(40, min(200, int(hl.get("size") or 100))),
               "recolor": bool(hl.get("recolor")), "key": None}
        if mode in ("channel", "custom") and ch:
            logos = self.store.data_dir / "logos"
            if mode == "channel":
                p = logos / f"{ch['id']}.png"
                p = p if (ch.get("logo") or {}).get("file") and p.exists() else None
            else:
                p = logos / f"{ch['id']}-header.png"
                p = p if hl.get("file") and p.exists() else None
            try:
                if mode == "custom" and p is None:
                    raise FileNotFoundError("no custom header logo uploaded")
                if p is not None:
                    key = (str(p), p.stat().st_mtime)
                    img = self._header_cache.get(key) or Image.open(p).convert("RGBA")
                else:                    # "this channel's logo" with none uploaded: the generated badge
                    key = ("badge", ch.get("id"), ch.get("number"), ch.get("name"))
                    img = self._header_cache.get(key) or Image.open(io.BytesIO(default_logo(self.fonts(), ch, 400))).convert("RGBA")
                if len(self._header_cache) > 8:
                    self._header_cache.clear()
                self._header_cache[key] = img
                out["image"], out["key"] = img, key
            except Exception as e:
                log.info("header logo for %s unavailable (%s); using the station mark", ch.get("name"), e)
                out["mode"] = "station"
        out["look"] = (out["mode"], out["key"], out["size"], out["recolor"])
        return out

    def theme_fonts(self, T, text_id="theme", display_id="theme"):
        """(text fonts, display fonts) for a theme, honouring per-channel overrides."""
        t = T.font("guide") if text_id in (None, "", "theme") else text_id
        dsp = T.font("guide_display") if display_id in (None, "", "theme") else display_id
        return self.font_set(t), self.font_set(dsp)

    def clock_font(self, ch):
        """(font file, size scale) for a channel's on-screen clock."""
        fid = (ch.get("clock") or {}).get("font") or "theme"
        if fid == "theme":
            fid = self.theme(ch).font("clock")
        f = fontlib.get(fid)
        path = fontlib.file_path(f, True) if f else ""
        if not path:
            return self.fonts().path_for("", True), 1.0
        return path, float(f.get("scale", 1.0))

    SUB_SIZES = {"small": 16, "medium": 20, "large": 25, "huge": 31}

    def subtitle_style(self, cfg, lang, codec):
        """libass options for text subtitles: our fonts folder, plus a font/size/style override for plain (SRT)
        subtitles. Styled ASS subtitles (anime typesetting) keep their own look."""
        out = {"fontsdir": str(fontlib.FONT_DIR)}
        if codec in ("ass", "ssa") and not cfg.get("override_ass"):
            return out
        cjk = (lang or "")[:2] in ("ja", "jp", "zh", "ch", "ko") or lang in ("jpn", "chi", "zho", "kor")
        fid = cfg.get("font") or ""
        f = fontlib.get(fid) if fid else None
        if cjk and not (f and f.get("cjk")):
            fid = "maru"           # a font that has Japanese characters
        if not fid or fid == "system" or not fontlib.file_path(fontlib.get(fid)):
            fid = "inter"          # always name a font we ship, so it works even where ffmpeg can't see system fonts
        fam = fontlib.family(fid)
        style = [f"FontSize={self.SUB_SIZES.get(cfg.get('size'), 20)}", "MarginV=22", "Shadow=1"]
        if fam:
            style.insert(0, f"FontName={fam}")
        if cfg.get("style") == "box":
            style += ["BorderStyle=3", "Outline=1", "BackColour=&H60000000"]
        else:
            style += ["BorderStyle=1", "Outline=2"]
        out["style"] = ",".join(style)
        return out

    def up_next_overlay(self, ch, t0, t1, title):
        """The 'UP NEXT > title' lower-third in the channel theme's font and colours."""
        T = self.theme(ch)
        Ft, _ = self.theme_fonts(T)
        label = Ft.text(f"UP NEXT  ›  {title}", True)
        return (t0, t1, label, {"font": Ft.path_for(label, True), "box": T.hex["accent2"],
                                "fg": T.hex["on_accent"] if T.light else "#ffffff"})

    def builder(self):
        b = Builder(self.store.settings, self.ffmpeg_path(), self.fonts())
        b.clock_font = self.clock_font
        return b

    def default_base(self):
        pub = (self.store.settings.get("public_url") or "").rstrip("/")
        return pub or f"http://{lan_ip()}:{self.port}"

    def music_paths(self):
        st = self.store.settings
        return [st.get("bumper_music_path")] + [c.get("music_path") for c in self.store.channels()] + \
               [b.get("music_path") for b in self.store.bumpers()]

    def start_maintenance(self):
        loudness.init(self.store.data_dir / "cache" / "music-loudness.json", self.ffmpeg_path)
        threading.Thread(target=self._maintain, daemon=True, name="maintenance").start()
        threading.Thread(target=self.cast.start, daemon=True, name="cast-discovery").start()

    def _maintain(self):
        time.sleep(3)
        while not self.stop_evt.is_set():
            st = self.store.settings
            if st.get("music_match_loudness", True):
                try:
                    loudness.prewarm(self.music_paths())       # measure new music in the background
                except Exception as e:
                    log.warning("music loudness scan failed: %s", e)
            if st.get("jellyfin_api_key"):
                for ch in self.store.channels():
                    if ch.get("type") in ("guide", "weather") or not ch.get("enabled", True):
                        continue
                    try:
                        self.sched.ensure(ch)
                    except Exception as e:
                        log.warning("schedule maintenance failed for %s: %s", ch["name"], e)
            self.stop_evt.wait(600)

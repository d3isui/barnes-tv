"""Settings + channel storage, and discovery of ffmpeg / fonts on Windows and Linux."""
import copy
import json
import os
import shutil
import subprocess
import threading
import uuid
from pathlib import Path

from . import themes

IS_WINDOWS = os.name == "nt"

DEFAULT_SETTINGS = {
    "bumper_packs": [],              # built-in bumper packs already added to this install
    "station_short": "",             # short station name ("Barnes TV"); empty = made from the full name
    "brand_color": "",               # app icon / TV app background colour; empty = Barnes navy
    "brand_recolor": None,           # tint the logos to each theme (None = yes for the Barnes art, no for uploads)
    "bumper_music_path": "",         # default music (file or folder) under text bumpers that don't set their own
    "music_match_loudness": True,    # bring music beds (bumpers, Up Next cards, guide, weather) down to TV loudness
    "music_volume_db": 0,            # the user's own adjustment on top, in dB (-30 .. +10)
    "station_name": "Barnes Television Broadcasting System",
    "theme": "barnes",               # station look: guide channel, slates, admin page, TV page (see themes.py)
    "ui_font": "theme",              # admin / TV page font: "theme" or a font id
    "jellyfin_url": "http://localhost:8096",
    "jellyfin_api_key": "",
    "jellyfin_user_id": "",          # blank = first administrator account
    "public_url": "",                # how Jellyfin reaches this app; blank = auto-detect
    "ffmpeg_path": "",               # blank = auto (Jellyfin's bundled ffmpeg, then PATH)
    "font_path": "",                 # blank = auto
    "font_bold_path": "",
    "cjk_font_path": "",             # used for Japanese/Chinese/Korean titles
    "media_access": "stream",        # "stream" = pull from Jellyfin over HTTP, "direct" = read files from disk
    "path_mappings": [],             # [{"from": "/media", "to": "D:\\Media"}] for direct mode
    "resolution": "1280x720",
    "framerate": 30,
    "video_encoder": "libx264",      # libx264 | h264_nvenc | h264_qsv | h264_amf | h264_vaapi | h264_videotoolbox
    "encoder_preset": "veryfast",
    "vaapi_device": "/dev/dri/renderD128",
    "video_bitrate_kbps": 4000,
    "audio_bitrate_kbps": 192,
    "deinterlace": True,
    "tonemap_hdr": True,
    "schedule_days": 3,
    "epg_hours": 48,
    "library_refresh_hours": 6,
    "idle_timeout_seconds": 30,
    "admin_password": "",
    "lock_enabled": False,           # channel lock ("kids mode")
    "lock_code_hash": "",
    "lock_salt": "",
    "lock_unlock_minutes": 60,       # how long one code entry unlocks a device
    "lock_hide_in_jellyfin": False,  # when locked, leave non-kids channels out of the M3U / guide given to Jellyfin
    "tuner_key": "",                 # private key on links handed to Jellyfin / Chromecasts (generated)
    "cast_hosts": "",                # optional Chromecast IPs, comma separated (if auto-discovery is blocked)
    "cast_hls_format": "fmp4",       # fmp4 | ts  (HLS segment type sent to Chromecasts)
    "cast_watchdog": True,           # reload the stream automatically when a TV gets stuck
    "map_api_key": "",               # CARTO basemaps key (weather radar maps): free at carto.com/basemaps/apikey
}

LOGO_DEFAULT = {"file": "", "position": "top-right", "size_percent": 12, "opacity": 0.85}
HEADER_LOGO_DEFAULT = {"mode": "station",   # station (the station logo from Branding) | channel (this channel's logo) | custom | name | none
                       "file": "",           # the uploaded image for "custom"
                       "size": 100,          # percent
                       "recolor": False}     # paint the logo in the theme's colour (for one-colour logos)
CLOCK_DEFAULT = {"enabled": True, "position": "top-left", "format": "12h", "size_percent": 4.5,
                 "bg_opacity": 35,          # 0 = no bar behind the time, 100 = solid black bar
                 "font": "theme",           # "theme" = the channel theme's clock font, or a font id
                 "opacity": 100,            # the digits themselves (10-100)
                 "color": "#ffffff",
                 "outline": "none",         # none | thin | thick  (Japanese-broadcast style = thick)
                 "shadow": True}
UP_NEXT_DEFAULT = {"enabled": True, "seconds_before_end": 90, "duration": 12}
BREAKS_DEFAULT = {
    "enabled": False,
    "sources": [],                   # where commercials come from (e.g. a "Commercials" library)
    "interval_minutes": 8,           # minutes of show between breaks
    "length_seconds": 120,           # target length of each break
    "min_tail_minutes": 3,           # never break this close to the end of a show
    "max_per_program": 0,            # 0 = no limit
    "use_chapters": True,            # snap breaks to nearby chapter marks (act breaks) when the file has them
    "episodes": True,
    "movies": True,
    "show_graphics": False,          # logo / clock during commercials
    "split": True,                   # find the separate ads inside long commercial compilations
    "split_over_seconds": 90,        # ...in any commercial video longer than this
}
BUMPERS_DEFAULT = {
    "enabled": False,
    "ids": [],                       # text bumpers from the library to use; empty = all of them
    "sources": [],                   # optional Jellyfin video bumpers (any placement)
    "into_break": True,              # "we'll be right back"
    "out_of_break": True,            # "and now, back to the show"
    "between_programs": True,        # "next: ..."
    "every_breaks": 1,               # bumpers around every break (1), every 2nd break (2), ...
    "show_graphics": False,
}
BUMPER_STYLE_DEFAULT = {"bg": "#000000", "fg": "#ffffff", "font": "regular", "size": "medium", "align": "center",
                        "case": "lower", "tag": "[{channel}]", "tag_pos": "bottom-right", "font_path": "",
                        "font_id": ""}

CHANNEL_DEFAULT = {
    "type": "standard",              # standard | guide
    "kids": False,                   # kids channels stay watchable when the channel lock is on
    "screen_off_minutes": 0,         # sleep channel: the TV page / app blacks out the picture after this long (0 = never)
    "number": 2,
    "name": "New Channel",
    "group": "",
    "enabled": True,
    "sources": [],                   # [{"type": "library|collection|playlist|series|genre|tag|studio", "id": "", "name": ""}]
    "exclude": [],
    "item_types": ["Movie", "Episode"],
    "include_specials": False,
    "min_minutes": 0,
    "max_minutes": 0,
    "order": "shuffle",              # shuffle | series_rotation | sequential | random
    "no_repeat_show": True,          # never the same show twice in a row (when there's anything else to play)
    # share of airtime per show (off by default: every episode/movie gets its fair turn, so big shows air more)
    "slots": [],                     # time slots: shows that air at set times (see timeslots.py)
    "balance": {"strength": 0,       # 0 = as the pool is, 100 = every show gets the same airtime
                "weights": {}},      # per-show fine tuning: {group key: multiplier, 1 = normal}
    "padding_minutes": 0,            # 0 = back-to-back, otherwise start programs on :00/:15/:30 boundaries
    "filler_sources": [],            # commercials / music videos / shorts used to fill gaps
    "audio_language": "",            # ISO 639-2, e.g. "jpn", "eng"
    "subtitles": {"mode": "off",     # off | always | forced (signs & songs only) | foreign (when the audio isn't in `language`)
                  "language": "eng", "font": "", "size": "medium", "style": "outline", "programs_only": True},
    "normalize_audio": False,
    "music_path": "",                # file or folder on THIS machine, played under slates / guide
    "logo": LOGO_DEFAULT,
    "clock": CLOCK_DEFAULT,
    "up_next": UP_NEXT_DEFAULT,
    "breaks": BREAKS_DEFAULT,
    "bumpers": BUMPERS_DEFAULT,
    "guide_scroll_speed": 40,        # guide channel only (pixels / second at 720p)
    "header_logo": HEADER_LOGO_DEFAULT,  # guide / weather channels: the artwork in the top-left corner
    "weather": {                     # weather channel only
        "location": {"mode": "auto",   # auto (from your internet connection) | zip | city | coords
                     "zip": "", "country": "US", "query": "", "lat": None, "lon": None, "name": ""},
        "units": "auto",               # auto | imperial | metric
        "slides": ["current", "hourly", "daily", "radar_local", "radar_regional", "radar_future", "almanac", "alerts"],
        "slides_version": 2,           # 2 = knows about the future radar screen
        "slide_seconds": 10,
        "radar_frames": 6,
        "radar_min_dbz": 10,           # hide radar echoes weaker than this (clear-air static, bugs, birds); "all" = raw
        "radar_zoom_local": 7,
        "radar_zoom_regional": 5,
        "radar_zoom_future": 6,
        "alerts": True,
        "crawl": True,
        "crawl_speed": 110,            # pixels / second at 720p
    },
    "theme": "",                     # "" = station theme; colours/fonts for this channel's slates (and the guide)
    "guide_font": "theme",           # guide channel only: listings font
    "guide_display_font": "theme",   # guide channel only: clock / channel numbers font
}

def clean_balance(b):
    b = b if isinstance(b, dict) else {}
    try:
        strength = max(0, min(100, int(round(float(b.get("strength") or 0)))))
    except (TypeError, ValueError):
        strength = 0
    weights = {}
    for k, v in (b.get("weights") or {}).items() if isinstance(b.get("weights"), dict) else ():
        try:
            v = max(0.0, min(8.0, float(v)))
        except (TypeError, ValueError):
            continue
        if abs(v - 1) > 1e-6:
            weights[str(k)[:200]] = round(v, 4)
    return {"strength": strength, "weights": weights}


SCHEDULE_KEYS = ("sources", "exclude", "item_types", "include_specials", "min_minutes", "no_repeat_show",
                 "max_minutes", "order", "padding_minutes", "filler_sources", "type", "breaks", "bumpers", "balance", "slots")

# A bumper can be limited to a time of day (checked when it's scheduled) or to the current weather (checked when
# it airs, from the weather channel's forecast).
BUMPER_TIME_WHEN = ("late_night", "morning", "daytime", "evening", "weekend")
BUMPER_WEATHER_WHEN = ("rain", "snow", "storm", "clear", "cloudy", "fog", "hot", "cold", "freezing", "windy", "nice")
BUMPER_WEATHER_VARS = ("weather", "temp", "feels_like", "conditions", "high", "low", "rain_chance", "wind", "humidity",
                       "tomorrow", "tomorrow_high", "sunset", "sunrise", "city", "weather_channel", "weather_number")

# Original starter bumpers (white-on-black text cards). Edit or delete them on the Bumpers page.
STARTER_BUMPERS = [
    {"name": "Right back", "kind": "into_break",
     "cards": [{"text": "{show}", "seconds": 2.5}, {"text": "will be right back.", "seconds": 3}]},
    {"name": "Back to the show", "kind": "out_of_break",
     "cards": [{"text": "and now,", "seconds": 2}, {"text": "back to {show}.", "seconds": 3}]},
    {"name": "Next up", "kind": "next",
     "cards": [{"text": "next:", "seconds": 2}, {"text": "{next}", "seconds": 3.5}]},
    {"name": "Remote check", "kind": "any",
     "cards": [{"text": "you're watching {channel}.", "seconds": 3}, {"text": "it's {time}.", "seconds": 2.5},
               {"text": "do you know where your remote is?", "seconds": 3.5}]},
    {"name": "Snacks", "kind": "any",
     "cards": [{"text": "we've been thinking.", "seconds": 2.5}, {"text": "about snacks.", "seconds": 2.5},
               {"text": "mostly about snacks.", "seconds": 3}]},
    {"name": "Still up", "kind": "any",
     "cards": [{"text": "it's {time}.", "seconds": 2.5}, {"text": "you're still up.", "seconds": 2.5},
               {"text": "so are we.", "seconds": 3}]},
]


def deep_merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _atomic_write(path: Path, data: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    for _ in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:  # Windows: file briefly locked by AV/indexer
            import time
            time.sleep(0.1)
    os.replace(tmp, path)


class Store:
    """config.json holds {"settings": {...}, "channels": [...]}."""

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir).resolve()
        for sub in ("state", "cache", "logos", "logs", "slates", "images"):
            (self.data_dir / sub).mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "config.json"
        self.lock = threading.RLock()
        self._settings = copy.deepcopy(DEFAULT_SETTINGS)
        self._channels = []
        self._bumpers = []
        self._themes = []
        self.load()

    # ---------- persistence ----------
    def load(self):
        with self.lock:
            if self.path.exists():
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                self._settings = deep_merge(DEFAULT_SETTINGS, raw.get("settings", {}))
                self._channels = [deep_merge(CHANNEL_DEFAULT, c) for c in raw.get("channels", [])]
                raw_wx = {c.get("id"): (c.get("weather") or {}) for c in raw.get("channels", [])}
                for c in self._channels:         # weather channels from before "Future radar": add that screen once
                    w = c.get("weather") or {}
                    if c.get("type") == "weather" and int(raw_wx.get(c.get("id"), {}).get("slides_version") or 1) < 2:
                        sl = list(w.get("slides") or [])
                        if "radar_future" not in sl:
                            sl.insert(sl.index("radar_regional") + 1 if "radar_regional" in sl else len(sl), "radar_future")
                        w["slides"], w["slides_version"] = sl, 2
                if self._settings.get("station_name") in ("", "Jellyfin Broadcast"):   # rebrand old installs
                    self._settings["station_name"] = "Barnes Television Broadcasting System"
                self._themes = [themes.normalize(t, t.get("id")) for t in raw.get("themes", []) if t.get("id")]
                themes.set_custom(self._themes)
                if "bumpers" in raw:
                    self._bumpers = [self._norm_bumper(b) for b in raw["bumpers"]]
                else:
                    self._bumpers = [self._norm_bumper(b) for b in STARTER_BUMPERS]
                    self.save()
                if self._add_new_packs():
                    self.save()
            else:
                self._channels = [self._make_channel({"type": "guide", "number": 1, "name": "TV Guide", "kids": True,
                                                      "clock": {"enabled": False}})]
                self._bumpers = [self._norm_bumper(b) for b in STARTER_BUMPERS]
                self._add_new_packs()
                self.save()

    def _add_new_packs(self):
        """Built-in bumper packs this install hasn't seen yet (added once; deleting them sticks)."""
        from .bumperpack import PACKS
        seen = list(self._settings.get("bumper_packs") or [])
        added = False
        for pid, bumpers in PACKS.items():
            if pid in seen:
                continue
            have = {b["id"] for b in self._bumpers}
            self._bumpers += [self._norm_bumper(b) for b in bumpers if b["id"] not in have]
            seen.append(pid)
            added = True
        self._settings["bumper_packs"] = seen
        return added

    def restore_pack_bumpers(self):
        """Put back built-in bumpers that were deleted (edited ones are left alone). Returns how many."""
        from .bumperpack import PACKS
        with self.lock:
            have = {b["id"] for b in self._bumpers}
            missing = [self._norm_bumper(b) for bs in PACKS.values() for b in bs if b["id"] not in have]
            self._bumpers += missing
            if missing:
                self.save()
            return len(missing)

    def missing_pack_bumpers(self):
        from .bumperpack import PACKS
        with self.lock:
            have = {b["id"] for b in self._bumpers}
        return sum(1 for bs in PACKS.values() for b in bs if b["id"] not in have)

    def save(self):
        with self.lock:
            _atomic_write(self.path, json.dumps({"settings": self._settings, "channels": self._channels,
                                                 "bumpers": self._bumpers, "themes": self._themes}, indent=2))

    # ---------- custom themes (theme builder) ----------
    def custom_themes(self):
        with self.lock:
            return copy.deepcopy(self._themes)

    def save_theme(self, data):
        with self.lock:
            tid = data.get("id") if any(t["id"] == data.get("id") for t in self._themes) else "my-" + uuid.uuid4().hex[:8]
            spec = themes.normalize(data, tid)
            self._themes = [t for t in self._themes if t["id"] != tid] + [spec]
            themes.set_custom(self._themes)
            self.save()
            return copy.deepcopy(spec)

    def delete_theme(self, tid):
        with self.lock:
            self._themes = [t for t in self._themes if t["id"] != tid]
            themes.set_custom(self._themes)
            # anything that used it falls back to the station theme / default
            if self._settings.get("theme") == tid:
                self._settings["theme"] = themes.DEFAULT_THEME
            for c in self._channels:
                if c.get("theme") == tid:
                    c["theme"] = ""
            self.save()

    # ---------- settings ----------
    @property
    def settings(self):
        with self.lock:
            return copy.deepcopy(self._settings)

    def update_settings(self, patch):
        with self.lock:
            for k, v in patch.items():
                if k in DEFAULT_SETTINGS:
                    self._settings[k] = v
            self.save()
            return self.settings

    # ---------- channels ----------
    def channels(self):
        with self.lock:
            return sorted(copy.deepcopy(self._channels), key=lambda c: (float(c.get("number") or 0), c["name"]))

    def channel(self, cid):
        with self.lock:
            for c in self._channels:
                if c["id"] == cid:
                    return copy.deepcopy(c)
            # allow lookup by channel number
            for c in self._channels:
                if str(c.get("number")) == str(cid):
                    return copy.deepcopy(c)
        return None

    def _make_channel(self, data):
        ch = deep_merge(CHANNEL_DEFAULT, data or {})
        ch["id"] = "c" + uuid.uuid4().hex[:10]
        return ch

    def add_channel(self, data):
        with self.lock:
            data = dict(data or {})
            data.pop("id", None)
            if not data.get("number"):
                nums = [float(c.get("number") or 0) for c in self._channels] or [1]
                data["number"] = int(max(nums)) + 1
            ch = self._make_channel(data)
            self._channels.append(ch)
            self.save()
            return copy.deepcopy(ch)

    def update_channel(self, cid, data):
        with self.lock:
            for i, c in enumerate(self._channels):
                if c["id"] == cid:
                    data = dict(data)
                    data["id"] = cid
                    self._channels[i] = deep_merge(c, data)
                    # lists are replaced, not merged
                    for k, v in data.items():
                        if isinstance(v, list):
                            self._channels[i][k] = v
                    if "slots" in data:
                        from .timeslots import clean_slots
                        self._channels[i]["slots"] = clean_slots(data["slots"])
                    if "balance" in data:       # replaced whole, so a show set back to "normal" really goes back
                        self._channels[i]["balance"] = clean_balance(data["balance"])
                    self.save()
                    return copy.deepcopy(self._channels[i])
        return None

    def delete_channel(self, cid):
        with self.lock:
            self._channels = [c for c in self._channels if c["id"] != cid]
            self.save()

    # ---------- bumpers (shared library of text bumpers) ----------
    @staticmethod
    def _norm_bumper(b):
        b = dict(b or {})
        out = {"id": b.get("id") or "b" + uuid.uuid4().hex[:10],
               "name": (b.get("name") or "Bumper")[:80],
               "kind": b.get("kind") if b.get("kind") in ("into_break", "out_of_break", "next", "any") else "any",
               "cards": [], "gap": float(b.get("gap", 0.35) or 0),
               "style": deep_merge(BUMPER_STYLE_DEFAULT, b.get("style") or {}),
               "music_path": b.get("music_path") or "",
               "when": b.get("when") if b.get("when") in BUMPER_TIME_WHEN + BUMPER_WEATHER_WHEN else ""}
        if b.get("pack"):
            out["pack"] = str(b["pack"])[:40]
        for c in b.get("cards") or []:
            text = str(c.get("text", ""))[:300]
            secs = max(0.5, min(30.0, float(c.get("seconds") or 3)))
            out["cards"].append({"text": text, "seconds": secs})
        if not out["cards"]:
            out["cards"] = [{"text": "{channel}", "seconds": 3}]
        return out

    @staticmethod
    def bumper_duration(b):
        return round(sum(c["seconds"] for c in b["cards"]) + b.get("gap", 0) * (len(b["cards"]) + 1), 2)

    def bumpers(self):
        with self.lock:
            return copy.deepcopy(self._bumpers)

    def bumper(self, bid):
        with self.lock:
            return copy.deepcopy(next((b for b in self._bumpers if b["id"] == bid), None))

    def save_bumper(self, data):
        with self.lock:
            b = self._norm_bumper(data)
            for i, old in enumerate(self._bumpers):
                if old["id"] == b["id"]:
                    self._bumpers[i] = b
                    break
            else:
                self._bumpers.append(b)
            self.save()
            return copy.deepcopy(b)

    def delete_bumper(self, bid):
        with self.lock:
            self._bumpers = [b for b in self._bumpers if b["id"] != bid]
            self.save()


# ---------- environment discovery ----------

def find_ffmpeg(configured="", remembered=""):
    """configured = Settings -> ffmpeg path; remembered = what an earlier run found (so the Windows startup task,
    which runs as SYSTEM without your PATH, still finds an ffmpeg installed just for your user account)."""
    cands = []
    if configured:
        cands.append(configured)
    if IS_WINDOWS:
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pd = os.environ.get("ProgramData", r"C:\ProgramData")
        cands += [os.path.join(pf, "Jellyfin", "Server", "ffmpeg.exe"),
                  r"C:\Program Files\Jellyfin\Server\ffmpeg.exe",
                  os.path.join(pd, "Jellyfin", "Server", "ffmpeg.exe")]
        which = shutil.which("ffmpeg")
        if which:
            cands.append(which)
        if remembered:
            cands.append(remembered)
        # per-user installs (winget, scoop) and chocolatey, for whichever account runs this
        import glob
        users = os.path.join(os.environ.get("SystemDrive", "C:") + os.sep, "Users")
        cands += sorted(glob.glob(os.path.join(users, "*", "AppData", "Local", "Microsoft", "WinGet", "Links", "ffmpeg.exe")))
        cands += sorted(glob.glob(os.path.join(users, "*", "AppData", "Local", "Microsoft", "WinGet", "Packages", "*",
                                               "*", "bin", "ffmpeg.exe")))
        cands += sorted(glob.glob(os.path.join(users, "*", "scoop", "shims", "ffmpeg.exe")))
        cands += [os.path.join(pd, "chocolatey", "bin", "ffmpeg.exe"), os.path.join(pf, "ffmpeg", "bin", "ffmpeg.exe"),
                  r"C:\ffmpeg\bin\ffmpeg.exe"]
        for c in cands:
            if c and os.path.isfile(c):
                return c
        return configured or "ffmpeg"
    else:
        cands += ["/usr/lib/jellyfin-ffmpeg/ffmpeg", "/usr/share/jellyfin-ffmpeg/ffmpeg",
                  "/opt/jellyfin-ffmpeg/ffmpeg"]
    which = shutil.which("ffmpeg")
    if which:
        cands.append(which)
    if remembered:
        cands.append(remembered)
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return configured or "ffmpeg"


def ffmpeg_version(path):
    try:
        out = subprocess.run([path, "-hide_banner", "-version"], capture_output=True, text=True, timeout=10,
                             creationflags=NO_WINDOW).stdout
        return out.splitlines()[0] if out else ""
    except Exception:
        return ""


NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_WIN_FONTS = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
FONT_CANDIDATES = {
    "regular": [os.path.join(_WIN_FONTS, f) for f in ("segoeui.ttf", "arial.ttf")] + [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/liberation-sans/LiberationSans-Regular.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf"],
    "bold": [os.path.join(_WIN_FONTS, f) for f in ("segoeuib.ttf", "arialbd.ttf")] + [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/liberation-sans/LiberationSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf"],
    "cjk": [os.path.join(_WIN_FONTS, f) for f in ("YuGothB.ttc", "meiryo.ttc", "msgothic.ttc", "malgun.ttf",
                                                  "msyh.ttc")] + [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc", "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        "/usr/share/fonts/wenquanyi/wqy-microhei/wqy-microhei.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"],
}


def _fc_match(pattern):
    if IS_WINDOWS or not shutil.which("fc-match"):
        return ""
    try:
        out = subprocess.run(["fc-match", "-f", "%{file}", pattern], capture_output=True, text=True, timeout=5).stdout
        return out.strip() if out and os.path.isfile(out.strip()) and out.strip().lower().endswith((".ttf", ".otf", ".ttc")) else ""
    except Exception:
        return ""


def find_fonts(settings):
    res = {}
    for kind, key, fc in (("regular", "font_path", "sans-serif"), ("bold", "font_bold_path", "sans-serif:bold"),
                          ("cjk", "cjk_font_path", "sans-serif:lang=ja")):
        val = settings.get(key) or ""
        if val and os.path.isfile(val):
            res[kind] = val
            continue
        res[kind] = next((p for p in FONT_CANDIDATES[kind] if os.path.isfile(p)), "") or _fc_match(fc)
    if not res["cjk"]:   # no Japanese-capable system font: use the bundled rounded gothic
        bundled = Path(__file__).resolve().parent.parent / "web" / "fonts" / "MPLUSRounded1c-Medium.ttf"
        res["cjk"] = str(bundled) if bundled.is_file() else ""
    if not res["bold"]:
        res["bold"] = res["regular"]
    if not res["regular"]:
        res["regular"] = res["bold"]
    return res

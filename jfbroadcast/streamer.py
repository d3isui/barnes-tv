"""Live channel sessions.

A session starts when the first viewer tunes in and stops shortly after the last one leaves, so idle channels cost
nothing. While running, it walks the channel timeline: one ffmpeg process per program (started at the right offset so
you join mid-show), each writing MPEG-TS with a running timestamp offset. The pieces are stitched into one continuous
transport stream (continuity counters rewritten) and fanned out to every viewer of that channel.
"""
import io
import json
import logging
import os
import queue
import random
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

from PIL import Image

from .config import NO_WINDOW
from .epg import channel_entries
from . import branding, themes
from .graphics import (readable, GuideRenderer, ImageCache, bumper_vars, bumper_needs_weather, bumper_time_ok,
                       bumper_weather_ok, default_logo, program_label, render_bumper,
                       render_slate)
from .jellyfin import JellyfinError, map_path

log = logging.getLogger("streamer")

EARLY_END = 3.0         # a segment that ends this much before plan gets the remainder filled with a slate
GUARD = 0.1             # tiny timestamp gap between segments so audio/video never overlap
# Running a little behind the schedule is normal (every hand-over costs a moment). Ads, bumpers and the rest of a
# show after a break always play from their first frame; the lag is won back by dropping a whole commercial when
# we're more than CATCH_UP seconds behind, and only past MAX_LAG does anything get cut into.
CATCH_UP = 6.0
MAX_LAG = 60.0
AUDIO_EXT = (".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wav")


VIDEO_PID = 0x100   # ffmpeg's first stream (we always map video first)
PAT_PID, PMT_PID = 0x0000, 0x1000


class CCFixer:
    """Rewrites MPEG-TS continuity counters so concatenated segments look like one stream, and notes where
    video keyframes begin so late joiners can start cleanly on one."""

    def __init__(self):
        self.cc = {}
        self.buf = bytearray()
        self.psi = {}        # last PAT / PMT packets, replayed to new viewers
        self.pcr = None      # latest program clock reference, in seconds (used to pace output to real time)
        self.seg_pcr0 = None # first PCR of the current segment
        self._wrap = 0.0

    def boundary(self):
        self.buf.clear()
        self.seg_pcr0 = None

    def segment_media_seconds(self):
        """How much media of the current segment has gone out, measured by the stream clock."""
        if self.pcr is None or self.seg_pcr0 is None:
            return None
        return max(0.0, self.pcr - self.seg_pcr0)

    def feed(self, data):
        """Returns (bytes, [byte offsets of video keyframe starts])."""
        buf = self.buf
        buf += data
        if buf and buf[0] != 0x47:
            i = buf.find(b"\x47")
            del buf[:i if i >= 0 else len(buf)]
        n = len(buf) // 188 * 188
        if not n:
            return b"", []
        out = buf[:n]
        del buf[:n]
        cc, keys = self.cc, []
        for i in range(0, n, 188):
            if out[i] != 0x47:
                continue
            b1, b3 = out[i + 1], out[i + 3]
            pid = ((b1 & 0x1F) << 8) | out[i + 2]
            if pid == 0x1FFF:
                continue
            if b3 & 0x10:  # has payload
                c = (cc.get(pid, -1) + 1) & 0x0F
                cc[pid] = c
                out[i + 3] = (b3 & 0xF0) | c
            if b3 & 0x20 and out[i + 4] >= 7 and out[i + 5] & 0x10:      # adaptation field carrying a PCR
                base = (out[i + 6] << 25) | (out[i + 7] << 17) | (out[i + 8] << 9) | (out[i + 9] << 1) | (out[i + 10] >> 7)
                pcr = base / 90000.0 + self._wrap
                if self.pcr is not None and pcr < self.pcr - 40000:     # 33-bit clock wrapped (~26.5 h)
                    self._wrap += (1 << 33) / 90000.0
                    pcr += (1 << 33) / 90000.0
                self.pcr = pcr
                if self.seg_pcr0 is None:
                    self.seg_pcr0 = pcr
            if pid == VIDEO_PID:
                if b1 & 0x40 and b3 & 0x20 and out[i + 4] and out[i + 5] & 0x40:
                    keys.append(i)
            elif pid in (PAT_PID, PMT_PID) and b1 & 0x40:
                self.psi[pid] = bytes(out[i:i + 188])
        return bytes(out), keys


class Broadcast:
    """Fan-out of one byte stream to many HTTP clients.

    Keeps the last ~20 s of the channel as whole GOPs (keyframe to keyframe). Live viewers start at the newest
    keyframe; HLS (Chromecast) gets the whole backlog so its player starts with a healthy buffer."""

    BACKLOG_SECONDS = 20
    MAX_BACKLOG_BYTES = 48_000_000

    def __init__(self):
        self.subs = set()
        self.lock = threading.Lock()
        self.gops = deque()      # [pcr_at_start, [chunks], bytes]
        self.backlog_bytes = 0
        self.psi = b""
        self.empty_since = time.time()
        self.total = 0

    def subscribe(self, backlog=False):
        q = queue.Queue(maxsize=2000 if backlog else 800)
        with self.lock:
            gops = list(self.gops) if backlog else list(self.gops)[-1:]
            if gops:
                q.put_nowait(self.psi)
                for g in gops:
                    for chunk in g[1]:
                        q.put_nowait(chunk)
            self.subs.add(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            self.subs.discard(q)
            if not self.subs:
                self.empty_since = time.time()

    @property
    def count(self):
        return len(self.subs)

    def _keep(self, data, keys, pcr):
        """Append to the GOP backlog, starting a new GOP at each keyframe and trimming old ones."""
        pos = 0
        for k in keys:
            if k > pos and self.gops:
                self.gops[-1][1].append(data[pos:k])
                self.gops[-1][2] += k - pos
            self.gops.append([pcr, [], 0])
            pos = k
        if pos < len(data) and self.gops:
            self.gops[-1][1].append(data[pos:])
            self.gops[-1][2] += len(data) - pos
        self.backlog_bytes = sum(g[2] for g in self.gops)
        while len(self.gops) > 1 and (
                self.backlog_bytes > self.MAX_BACKLOG_BYTES or
                (pcr is not None and self.gops[1][0] is not None and pcr - self.gops[1][0] > self.BACKLOG_SECONDS)):
            self.backlog_bytes -= self.gops.popleft()[2]

    def publish(self, data, keys=(), psi=b"", pcr=None):
        if not data:
            return
        self.total += len(data)
        with self.lock:
            if psi:
                self.psi = psi
            self._keep(data, keys, pcr)
            dead = []
            for q in self.subs:
                try:
                    q.put_nowait(data)
                except queue.Full:
                    dead.append(q)
            for q in dead:  # a viewer that can't keep up gets disconnected rather than stalling everyone
                self.subs.discard(q)
                try:
                    q.get_nowait()
                    q.put_nowait(None)
                except Exception:
                    pass

    def close(self):
        with self.lock:
            for q in self.subs:
                try:
                    q.put_nowait(None)
                except queue.Full:
                    pass
            self.subs.clear()


class Proc:
    """An ffmpeg process whose stdout is drained into a queue and stderr into the channel log."""

    def __init__(self, cmd, logf, label, stdin=False):
        self.label = label
        self.started = time.time()
        self.first_byte = None
        self.bytes = 0
        self.q = queue.Queue(maxsize=400)   # backpressure: a too-fast ffmpeg simply waits on its pipe
        self.logf = logf
        self.killed = False
        self.errors = deque(maxlen=20)
        self._mirrored = 0
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     stdin=subprocess.PIPE if stdin else subprocess.DEVNULL,
                                     bufsize=0, creationflags=NO_WINDOW)
        threading.Thread(target=self._out, daemon=True).start()
        threading.Thread(target=self._err, daemon=True).start()

    def _out(self):
        try:
            while True:
                data = self.proc.stdout.read(65536)
                if not data:
                    break
                if self.first_byte is None:
                    self.first_byte = time.time()
                self.bytes += len(data)
                if not self._put(data):
                    return
        except Exception:
            pass
        self._put(None)

    def _put(self, item):
        while True:
            try:
                self.q.put(item, timeout=1)
                return True
            except queue.Full:
                if self.killed:
                    return False

    def _err(self):
        try:
            for line in iter(self.proc.stderr.readline, b""):
                txt = line.decode("utf-8", "replace").rstrip()
                if txt:
                    self.errors.append(txt)
                    self.logf(f"[{self.label}] {txt}")
                    if self._mirrored < 8:          # surface the first few ffmpeg complaints in broadcast.log too
                        self._mirrored += 1
                        log.warning("ffmpeg (%s): %s", self.label, txt[:300])
        except Exception:
            pass

    def kill(self):
        self.killed = True
        try:
            if self.proc.poll() is None:
                self.proc.kill()
        except Exception:
            pass


class Play:
    def __init__(self, proc, entry, offset, duration, ts, kind):
        self.proc, self.entry, self.offset, self.duration, self.ts, self.kind = proc, entry, offset, duration, ts, kind
        self.next_at = entry["s"] + entry["d"]          # schedule time of the entry that follows this one

    def media_elapsed(self, now=None):
        return ((now or time.time()) - self.proc.first_byte) if self.proc.first_byte else 0.0


TEXT_SUBS = {"subrip", "srt", "ass", "ssa", "webvtt", "vtt", "mov_text", "text", "ttml", "microdvd", "smi", "sami"}
_LANG_ALIASES = {"eng": "en", "jpn": "ja", "spa": "es", "fre": "fr", "fra": "fr", "ger": "de", "deu": "de", "ita": "it",
                 "por": "pt", "chi": "zh", "zho": "zh", "kor": "ko", "rus": "ru", "dut": "nl", "nld": "nl", "swe": "sv"}


def _lang_match(a, b):
    a, b = (a or "").lower(), (b or "").lower()
    return bool(a and b) and (a == b or _LANG_ALIASES.get(a, a[:2]) == _LANG_ALIASES.get(b, b[:2]))


def pick_music(path):
    if not path:
        return None
    p = Path(path)
    if p.is_file():
        return str(p)
    if p.is_dir():
        files = [str(f) for f in p.rglob("*") if f.suffix.lower() in AUDIO_EXT]
        return random.choice(files) if files else None
    return None


class BaseSession(threading.Thread):
    def __init__(self, app, ch):
        super().__init__(daemon=True, name=f"ch-{ch['number']}")
        self.app = app
        self.cid = ch["id"]
        self.ch = ch
        self.broadcast = Broadcast()
        self.fixer = CCFixer()
        self.stop_evt = threading.Event()
        self.started_at = time.time()
        self.now_playing = None
        self.last_error = ""
        logdir = app.store.data_dir / "logs"
        self.log_path = logdir / f"channel-{ch['id']}.log"
        try:
            if self.log_path.exists() and self.log_path.stat().st_size > 2_000_000:
                self.log_path.unlink()
        except OSError:
            pass
        self._log_lock = threading.Lock()

    def logf(self, msg):
        if msg.startswith("start "):
            log.info("ch %s: %s", self.ch.get("number"), msg[6:])
        with self._log_lock:
            try:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
            except OSError:
                pass

    def idle(self):
        timeout = float(self.app.store.settings.get("idle_timeout_seconds") or 30)
        return self.broadcast.count == 0 and time.time() - self.broadcast.empty_since > timeout

    def stop(self):
        self.stop_evt.set()

    LEAD = 12.0     # never run more than this many seconds ahead of real time (room for the start-up burst)

    def publish(self, chunk):
        data, keys = self.fixer.feed(chunk)
        self._pace()
        self.broadcast.publish(data, keys, b"".join(self.fixer.psi.get(p, b"") for p in (PAT_PID, PMT_PID)),
                               self.fixer.pcr)

    def _pace(self):
        """Hold output to real time using the stream's own clock (PCR). Some ffmpeg builds/encoders, especially when
        seeking into the middle of a file, send far faster than real time; players then overflow and drop."""
        pcr = self.fixer.pcr
        if pcr is None:
            return
        now = time.monotonic()
        p0 = getattr(self, "_pcr0", None)
        if p0 is None or pcr < self._pcr_last - 5 or pcr - self._pcr_last > 30:
            self._pcr0, self._wall0 = pcr, now          # start, or a clock jump: re-anchor
        else:
            ahead = (pcr - self._pcr0) - (now - self._wall0)
            if ahead < -5:                               # we fell behind (stall): re-anchor, don't race to catch up
                self._pcr0, self._wall0 = pcr, now
            elif ahead > self.LEAD:
                self.stop_evt.wait(min(5.0, ahead - self.LEAD + 0.5))
        self._pcr_last = pcr
        # encoding speed: media seconds produced per wall second, measured over ~20 s windows
        w = getattr(self, "_speed_w", None)
        if w is None or pcr < w[0]:
            self._speed_w = (pcr, now)
        elif now - w[1] >= 20:
            self.speed = round((pcr - w[0]) / (now - w[1]), 2)
            self._speed_w = (pcr, now)
            if self.speed < 0.95 and time.time() - getattr(self, "_speed_warned", 0) > 120:
                self._speed_warned = time.time()
                log.warning("ch %s is only encoding at %.2fx real time - viewers will buffer. Use a faster preset, "
                            "a lower resolution, or a GPU encoder in Settings.", self.ch.get("number"), self.speed)


class ChannelSession(BaseSession):
    def __init__(self, app, ch):
        super().__init__(app, ch)
        self.reload_evt = threading.Event()
        self.details = {}
        self.no_subs = set()       # items whose subtitles made ffmpeg fail: play them without

    # ------------------------------------------------------------------ helpers
    def _channel(self):
        return self.app.store.channel(self.cid) or self.ch

    def _item_info(self, item):
        """Which audio track to use, whether there is audio, and whether the video is HDR."""
        iid = item["id"]
        if iid in self.details:
            return self.details[iid]
        info = {"audio_index": None, "has_audio": True, "hdr": False}
        try:
            d = self.app.sched.jellyfin().item_details(iid) or {}
            streams = d.get("MediaStreams") or []
            if not streams and d.get("MediaSources"):
                streams = d["MediaSources"][0].get("MediaStreams") or []
            audio = [s for s in streams if s.get("Type") == "Audio" and not s.get("IsExternal")]
            audio.sort(key=lambda s: s.get("Index", 0))
            info["has_audio"] = bool(audio) or not streams
            lang = (self._channel().get("audio_language") or "").lower()
            idx = None
            if lang and audio:
                idx = next((n for n, s in enumerate(audio) if (s.get("Language") or "").lower().startswith(lang[:2])
                            or (s.get("Language") or "").lower() == lang), None)
            if idx is None and audio:
                idx = next((n for n, s in enumerate(audio) if s.get("IsDefault")), 0)
            info["audio_index"] = idx
            info["audio_lang"] = ((audio[idx].get("Language") or "") if (audio and idx is not None) else "").lower()
            info["source_id"] = (d.get("MediaSources") or [{}])[0].get("Id") or iid
            embedded = sorted((s for s in streams if s.get("Type") == "Subtitle" and not s.get("IsExternal")),
                              key=lambda s: s.get("Index", 0))
            info["subs"] = [{"index": s.get("Index"), "codec": (s.get("Codec") or "").lower(),
                             "lang": (s.get("Language") or "").lower(), "forced": bool(s.get("IsForced")),
                             "default": bool(s.get("IsDefault")), "external": bool(s.get("IsExternal")),
                             "text": bool(s.get("IsTextSubtitleStream")) or (s.get("Codec") or "").lower() in TEXT_SUBS,
                             "rel": next((n for n, e in enumerate(embedded) if e is s), None),
                             "title": s.get("DisplayTitle") or s.get("Title") or ""}
                            for s in streams if s.get("Type") == "Subtitle"]
            video = next((s for s in streams if s.get("Type") == "Video"), {})
            vr = f"{video.get('VideoRange', '')} {video.get('VideoRangeType', '')}".upper()
            info["hdr"] = "HDR" in vr or "DOVI" in vr or "HLG" in vr
            if d.get("Path"):
                info["path"] = d["Path"]
        except (JellyfinError, OSError, ValueError) as e:
            self.logf(f"metadata lookup failed for {item.get('title')}: {e}")
        self.details[iid] = info
        if len(self.details) > 200:
            self.details.pop(next(iter(self.details)))
        return info

    def _subtitle(self, item, info, kind):
        return self.subtitle_choice(item, info, kind)[0]

    def subtitle_choice(self, item, info, kind):
        """(subtitle to burn in or None, plain-language reason) under the channel's subtitle settings."""
        cfg = self._channel().get("subtitles") or {}
        mode = cfg.get("mode", "off")
        if mode == "off":
            return None, "Subtitles are off for this channel."
        if cfg.get("programs_only", True) and kind != "program":
            return None, "Not a show or movie (commercials and filler don't get subtitles)."
        if item["id"] in self.no_subs:
            return None, "Turned off for this item after its subtitles made playback fail (see the channel Log)."
        subs = info.get("subs") or []
        if not subs:
            return None, "This video has no subtitle tracks in Jellyfin."
        want = (cfg.get("language") or "").lower()
        audio = info.get("audio_lang") or ""
        if mode == "foreign" and want and audio and _lang_match(audio, want):
            return None, f"The audio is already in your language ({audio})."
        picked = [x for x in subs if not want or _lang_match(x["lang"], want)]
        note = ""
        if not picked:
            # many files don't label their subtitle tracks: use unlabelled ones rather than nothing
            picked = [x for x in subs if x["lang"] in ("", "und", "unk", "unknown", "mis", "zxx")]
            note = " (unlabelled track)" if picked else ""
        if not picked:
            have = ", ".join(sorted({x["lang"] or "?" for x in subs}))
            return None, f"No {want} subtitles. This video has: {have}."
        if mode == "forced":
            picked = [x for x in picked if x["forced"]]
            if not picked:
                return None, "No forced subtitle track (only full tracks)."
        else:
            picked = sorted(picked, key=lambda x: (x["forced"], not x["text"], not x["default"]))   # full, text first
        text_ok = self.app.ffmpeg_has_filter("subtitles")
        why = []
        for x in picked:
            if x["text"]:
                if not text_ok:
                    why.append("text subtitles need an ffmpeg with libass (Jellyfin's own ffmpeg has it)")
                    continue
                path = self._fetch_subtitle(item, info, x)
                if path:
                    sub = {"kind": "text", "file": path, "title": (x["title"] or x["lang"]) + note,
                           **self.app.subtitle_style(cfg, x["lang"], x["codec"])}
                    return sub, f"Using {x['title'] or x['lang'] or 'subtitle'} ({x['codec']}, text){note}."
                why.append(f"couldn't download {x['title'] or x['codec']} from Jellyfin (see the channel Log)")
            elif x["rel"] is not None and not x["external"]:
                return ({"kind": "image", "rel": x["rel"], "title": (x["title"] or x["lang"]) + note},
                        f"Using {x['title'] or x['lang'] or 'subtitle'} ({x['codec']}, picture){note}.")
            else:
                why.append(f"{x['title'] or x['codec']} is a separate picture-subtitle file, which isn't supported")
        return None, "Couldn't use the subtitles: " + "; ".join(why) + "."

    def _fetch_subtitle(self, item, info, s):
        ass = s["codec"] in ("ass", "ssa")
        folder = self.app.store.data_dir / "cache" / "subs"
        path = folder / f"{item['id']}-{s['index']}.{'ass' if ass else 'srt'}"
        if path.exists() and path.stat().st_size > 0:
            return str(path)
        try:
            jf = self.app.sched.jellyfin()
            data = jf.fetch_bytes(jf.subtitle_url(item["id"], info.get("source_id"), s["index"], "ass" if ass else "srt"),
                                  timeout=30)
            if not data.strip():
                raise ValueError("empty subtitle file")
            folder.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            return str(path)
        except Exception as e:
            self.logf(f"couldn't get subtitles for {item.get('title')}: {e}")
            return None

    def _source(self, item, info):
        st = self.app.store.settings
        jf = self.app.sched.jellyfin()
        if st.get("media_access") == "direct":
            path = map_path(info.get("path") or item.get("path") or "", st.get("path_mappings"))
            if path and os.path.isfile(path):
                return path, None
            self.logf(f"direct path not found, streaming from Jellyfin instead: {path}")
        return jf.stream_url(item["id"]), f"Authorization: {jf.auth_header}\r\n"

    def _weather_swap(self, bumper, entry, now):
        """A weather bumper whose weather isn't happening (or with no forecast to quote): play another one of the
        same kind instead, the closest in length."""
        if not bumper_needs_weather(bumper):
            return bumper
        values, tags = self.app.weather.bumper_info()
        if bumper_weather_ok(bumper, values, tags):
            return bumper
        ch = self._channel()
        ids = set((ch.get("bumpers") or {}).get("ids") or [])
        place = entry.get("place")
        pool = [b for b in self.app.store.bumpers() if (not ids or b["id"] in ids) and b["kind"] in (place, "any")
                and bumper_time_ok(b, now) and bumper_weather_ok(b, values, tags)]
        if not pool:
            return None
        want = entry.get("d") or 8
        pool.sort(key=lambda b: abs(self.app.store.bumper_duration(b) - want))
        swap = random.choice(pool[:4])
        self.logf(f"bumper '{bumper['name']}' doesn't fit the weather right now: playing '{swap['name']}' instead")
        return swap

    def _logo(self, ch):
        p = self.app.store.data_dir / "logos" / f"{ch['id']}.png"
        return str(p) if (ch.get("logo") or {}).get("file") and p.exists() else None

    def _start(self, entry, ts, offset=None, force_kind=None, burst=0.0):
        """Launch ffmpeg for a timeline entry (or a slate for its remainder)."""
        ch = self._channel()
        b = self.app.builder()
        now = time.time()
        if offset is None:
            late = now - entry["s"]
            offset = late if late > 2 else 0.0
        duration = entry["d"] - offset
        kind = force_kind or entry["k"]
        logo = self._logo(ch)
        # real TV drops the channel bug and clock during commercials and bumpers (configurable)
        hide = (kind == "commercial" and not (ch.get("breaks") or {}).get("show_graphics")) or \
               (kind == "bumper" and not (ch.get("bumpers") or {}).get("show_graphics"))
        if hide:
            ch = dict(ch, clock=dict(ch.get("clock") or {}, enabled=False))
            logo = None
        common = dict(duration=duration, ts_offset=ts, logo_path=logo)
        label = kind
        if kind == "bumper" and entry.get("b"):
            bumper = self.app.store.bumper(entry["b"])
            if bumper is None:   # deleted since it was scheduled: use any other one of the same kind
                pool = [x for x in self.app.store.bumpers() if x["kind"] in (entry.get("place"), "any")]
                bumper = random.choice(pool) if pool else None
            if bumper:
                bumper = self._weather_swap(bumper, entry, now)
            if bumper:
                st = self.app.store.settings
                wx = self.app.weather.bumper_info((ch.get("clock") or {}).get("format", "12h"))[0] \
                    if bumper_needs_weather(bumper) else None
                values = bumper_vars(entry.get("ctx"), ch, st.get("station_name"), now,
                                     (ch.get("clock") or {}).get("format", "12h"), wx)
                pl = render_bumper(self.app.fonts(), self.app.store.data_dir / "slates", b.W, b.H, bumper, values,
                                   total=duration)
                cmd = b.segment(ch, concat=str(pl), music=pick_music(bumper.get("music_path") or st.get("bumper_music_path")
                                                                 or ch.get("music_path")),
                                **common)
                self.logf(f"start bumper: {bumper['name']} dur={duration:.1f}s ts={ts:.1f}")
                return Play(Proc(cmd, self.logf, f"bumper: {bumper['name']}"), entry, offset, duration, ts, kind)
            kind = "slate"
        if kind in ("program", "filler", "commercial", "bumper"):
            item = entry["i"]
            info = self._item_info(item)
            src, headers = self._source(item, info)
            up = None
            un = ch.get("up_next") or {}
            if kind == "program" and un.get("enabled") and entry["d"] > 300 and entry.get("last", True):
                nxt = self.app.sched.next_program(ch, entry["s"] + entry["d"])
                if nxt:
                    t1 = entry["d"] - offset - float(un.get("seconds_before_end") or 90)
                    t0 = t1 - float(un.get("duration") or 12)
                    if t0 > 2:
                        title, _ = program_label(nxt["i"])
                        up = self.app.up_next_overlay(ch, t0, t1, title)
            # start a few seconds back and send those seconds at once, so players begin with a buffer
            burst = min(burst, offset) if burst else 0.0
            if burst:
                offset -= burst
                duration += burst
                common["duration"] = duration
                if up:
                    up = (up[0] + burst, up[1] + burst) + tuple(up[2:])
            sub, why = self.subtitle_choice(item, info, kind)
            if (self._channel().get("subtitles") or {}).get("mode", "off") != "off" and kind == "program":
                self.logf(f"subtitles for {item.get('title')}: {why}")
            cmd = b.segment(ch, source=src, headers=headers, offset=offset + entry.get("o", 0.0),
                            audio_index=info["audio_index"], has_audio=info["has_audio"], hdr=info["hdr"],
                            up_next=up, initial_burst=burst, subtitle=sub, **common)
            label = f"{kind}: {item.get('title')}" + (f" [subtitles: {sub.get('title') or sub['kind']}]" if sub else "")
            self.now_playing = {"entry": entry, "started": now}
        else:
            if kind == "error":
                slate_kind = "error"
                nxt = None
            elif entry.get("msg") == "nocontent":
                slate_kind, nxt = "nocontent", None
            else:
                slate_kind = "upnext"
                nxt = self.app.sched.next_program(ch, entry["s"] + entry["d"] - 1)
            T = self.app.theme(ch)
            Ft, Fd = self.app.theme_fonts(T)
            img = render_slate(Ft, self.app.store.data_dir / "slates", b.W, b.H, slate_kind, ch, nxt, logo, T, Fd)
            cmd = b.segment(ch, image=str(img), music=pick_music(ch.get("music_path")), **common)
            label = f"slate:{slate_kind}"
            if self.now_playing is None or kind != "slate":
                self.now_playing = {"entry": entry, "started": now}
        self.logf(f"start {label} offset={offset:.1f}s dur={duration:.1f}s ts={ts:.1f}")
        play = Play(Proc(cmd, self.logf, label), entry, offset, duration, ts, kind)
        play.subs = bool(locals().get("sub"))
        return play

    def _entry_after(self, ch, t):
        _, e = self.app.sched.entry_at(ch, t + 0.5)
        return e or {"s": t, "d": 60, "k": "slate", "i": None}

    def _start_synced(self, e, ts):
        """Start entry e. When we're running behind the schedule: never start an ad, a bumper or a show's return
        from a break part-way in (that clips its opening); catch up by dropping whole commercials instead, and by
        trimming "up next" slates. Only a large lag (MAX_LAG) cuts into programs, to keep the guide honest."""
        ch = self._channel()
        for _ in range(200):
            drift = time.time() + self._lat(e) - e["s"]
            k = e["k"]
            if drift <= 4:
                return self._start(e, ts, offset=0.0)
            if k in ("commercial", "filler"):
                if drift > CATCH_UP and drift >= e["d"] - 1.0:        # we're a whole ad behind: skip that ad
                    self.logf(f"running {drift:.1f}s behind: skipping {k} '{(e.get('i') or {}).get('title')}' to catch up")
                    e = self._entry_after(ch, e["s"] + e["d"])
                    continue
                return self._start(e, ts, offset=0.0)
            if k == "bumper" or (k == "program" and e.get("p")):
                if drift <= MAX_LAG:
                    return self._start(e, ts, offset=0.0)
            elif k == "program" and drift <= MAX_LAG / 2:
                return self._start(e, ts, offset=0.0)
            # slates (and anything when far behind): skip into it, or past it if almost nothing is left
            if e["d"] - drift < 3:
                e = self._entry_after(ch, e["s"] + e["d"])
                continue
            return self._start(e, ts, offset=max(0.0, drift))
        return self._start(e, ts, offset=0.0)

    def _start_for_now(self, ts, burst=0.0):
        ch = self._channel()
        now = time.time()
        _, e = self.app.sched.entry_at(ch, now)
        if e is None:
            e = {"s": now, "d": 60, "k": "slate", "i": None}
        if e["s"] + e["d"] - now < 3:  # boundary is imminent: start the next entry instead
            e = self._entry_after(ch, e["s"] + e["d"])
        return self._start(e, ts, offset=max(0.0, now - e["s"]), burst=burst)

    def reload(self):
        self.reload_evt.set()

    # ------------------------------------------------------------------ main loop
    latency = 1.0   # running estimate of ffmpeg start-up time (launch -> first byte)

    @staticmethod
    def _lat_kind(entry, kind=None):
        """Start-up time differs a lot: a still image is instant, a file from its start is quick, and jumping into
        the middle of a file over the network (an ad inside a compilation, a show after a break) is the slowest."""
        kind = kind or (entry or {}).get("k")
        if kind in ("slate", "error") or (kind == "bumper" and (entry or {}).get("b")):
            return "local"
        return "seek" if (entry or {}).get("o") else "media"

    def _lat(self, entry, kind=None):
        lat = getattr(self, "lat", None)
        if lat is None:
            lat = self.lat = {"local": 0.6, "media": 1.0, "seek": 1.5}
        return lat[self._lat_kind(entry, kind)]

    def _emitted(self, play):
        """Media seconds of `play` already sent: the stream clock when known, else wall time since first byte."""
        m = self.fixer.segment_media_seconds()
        return (m + 1.0 / 30) if m is not None else play.media_elapsed()

    def _learn(self, play):
        p = play.proc
        if p.first_byte:
            took = p.first_byte - p.started
            self.latency = max(0.2, min(4.0, 0.7 * self.latency + 0.3 * took))
            k = self._lat_kind(play.entry, play.kind)
            self._lat(play.entry, play.kind)
            # rise fast (a stall is what viewers notice), settle slowly
            self.lat[k] = max(0.2, min(6.0, took if took > self.lat[k] else 0.8 * self.lat[k] + 0.2 * took))

    def run(self):
        cur = nxt = None
        last_check = time.time()
        try:
            cur = self._start_for_now(0.0, burst=8.0 if self.app.ffmpeg_supports("readrate_initial_burst") else 0.0)
            while not self.stop_evt.is_set():
                # showing "no programming"? check every few seconds whether real programming has arrived
                if cur.entry and cur.entry.get("msg") == "nocontent" and time.time() - last_check > 10:
                    last_check = time.time()
                    try:
                        _, e = self.app.sched.entry_at(self._channel(), time.time())
                        if e and e.get("msg") != "nocontent":
                            self.reload_evt.set()
                    except Exception:
                        pass
                if self.idle():
                    log.info("channel %s idle, stopping", self.ch["name"])
                    break
                now = time.time()
                if self.reload_evt.is_set():  # settings changed: restart the current entry in place
                    self.reload_evt.clear()
                    elapsed = self._emitted(cur)
                    for p in (cur, nxt):
                        if p:
                            p.proc.kill()
                    nxt = None
                    self.fixer.boundary()
                    cur = self._start_for_now(cur.ts + elapsed + 0.3)
                    continue
                # launch the next program just early enough to hide ffmpeg's start-up time
                # (generously early: the next ffmpeg's output just waits in its queue, while a late start stalls
                # the picture at the end of the current segment and pushes everything after it behind schedule)
                if nxt is None and cur.proc.first_byte:
                    if getattr(cur, "upcoming", None) is None:
                        self._learn(cur)
                        cur.upcoming = self._entry_after(self._channel(), cur.next_at)
                    if cur.media_elapsed(now) >= cur.duration - self._lat(cur.upcoming) - 0.5:
                        nxt = self._start_synced(cur.upcoming, cur.ts + cur.duration + GUARD)
                try:
                    chunk = cur.proc.q.get(timeout=0.25)
                except queue.Empty:
                    if cur.proc.first_byte is None and now - cur.proc.started > 30:
                        cur.proc.kill()  # stuck opening the source; EOF handling fills with a slate
                    continue
                if chunk is not None:
                    self.publish(chunk)
                    continue
                # ---- current segment finished
                elapsed = self._emitted(cur)
                self.fixer.boundary()
                short = cur.duration - elapsed
                if nxt is None and short > EARLY_END:
                    failed = cur.proc.first_byte is None or cur.proc.bytes < 50_000 or cur.proc.proc.poll() not in (0, None)
                    playable = ("program", "filler", "commercial", "bumper")
                    if failed and cur.kind in playable:
                        self.last_error = " | ".join(list(cur.proc.errors)[-3:]) or "ffmpeg exited"
                        log.warning("ch %s: segment failed: %s", self.ch["number"], self.last_error)
                    end = cur.next_at
                    if failed and getattr(cur, "subs", False) and cur.entry and cur.entry.get("i"):
                        # the subtitles were the problem more often than not: carry on without them
                        self.no_subs.add(cur.entry["i"]["id"])
                        self.logf(f"subtitles failed for {cur.entry['i'].get('title')}; playing it without them")
                        cur = self._start(cur.entry, cur.ts + max(elapsed, 0.0) + GUARD, offset=cur.offset + max(elapsed, 0.0))
                        cur.next_at = end
                        continue
                    slate = dict(cur.entry or {}, s=end - short, d=short)
                    cur = self._start(slate, cur.ts + max(elapsed, 0.0) + GUARD, offset=0.0,
                                      force_kind="error" if failed and cur.kind in playable else "slate")
                    cur.next_at = end
                    continue
                if nxt is None:
                    e = self._entry_after(self._channel(), cur.next_at)
                    cur = self._start_synced(e, cur.ts + cur.duration + GUARD)
                else:
                    cur, nxt = nxt, None
        except Exception as e:
            log.exception("session crashed on channel %s", self.ch.get("name"))
            self.last_error = str(e)
        finally:
            for p in (cur, nxt):
                if p:
                    p.proc.kill()
            self.broadcast.close()
            self.app.sessions.discard(self)


class GuideSession(BaseSession):
    """Renders the guide channel in Python (1 fps) and lets ffmpeg scroll + encode it."""

    def __init__(self, app, ch):
        super().__init__(app, ch)
        self.logo_cache = {}

    def _logo_img(self, ch):
        p = self.app.store.data_dir / "logos" / f"{ch['id']}.png"
        key = (ch["id"], ch.get("number"), ch.get("name"), p.stat().st_mtime if p.exists() else 0)
        if key not in self.logo_cache:
            try:
                if (ch.get("logo") or {}).get("file") and p.exists():
                    img = Image.open(p).convert("RGBA")
                else:
                    img = Image.open(io.BytesIO(default_logo(self.app.fonts(), ch, 160))).convert("RGBA")
            except Exception:
                img = None
            self.logo_cache[key] = img
        return self.logo_cache[key]

    def _rows(self, now):
        # schedules only change slowly: rebuild the row data every 10 s, not every frame
        if getattr(self, "_rows_at", 0) > now - 10 and int(now // 60) == getattr(self, "_rows_min", -1):
            return self._rows_cache
        self._rows_at, self._rows_min = now, int(now // 60)
        self._rows_cache = self._build_rows(now)
        return self._rows_cache

    def _build_rows(self, now):
        rows, spots = [], []
        win0 = now - ((now + time.localtime(now).tm_gmtoff) % 1800)
        for ch in self.app.store.channels():
            if ch.get("type") == "guide" or not ch.get("enabled", True):
                continue
            try:
                entries = channel_entries(self.app, ch, win0 - 6 * 3600, win0 + GuideRenderer.WINDOW_MIN * 60)
            except Exception:
                entries = []
            rows.append((ch, self._logo_img(ch), entries))
            cur = next((e for e in entries if e["s"] <= now < e["s"] + e["d"] and e["k"] == "program"), None)
            if cur:
                spots.append((ch, cur))
        return rows, spots

    def run(self):
        proc = None
        try:
            st = self.app.store.settings
            b = self.app.builder()
            gch = self.app.store.channel(self.cid) or self.ch
            images = ImageCache(self.app.store.data_dir / "images",
                                lambda iid, h: self.app.sched.jellyfin().fetch_bytes(
                                    self.app.sched.jellyfin().image_url(iid, "Primary", h)))
            def make_renderer(gch, st):
                T = self.app.theme(gch)
                Ft, Fd = self.app.theme_fonts(T, gch.get("guide_font"), gch.get("guide_display_font"))
                return GuideRenderer(Ft, images, b.W, b.H, branding.name(),
                                     (gch.get("clock") or {}).get("format", "12h"), T, Fd, self.app.header_logo(gch))

            def look_key(gch, st):
                return (self.app.theme(gch).key, gch.get("guide_font"), gch.get("guide_display_font"),
                        (gch.get("clock") or {}).get("format"), branding.version(), self.app.header_logo(gch)["look"])

            renderer = make_renderer(gch, st)
            look, look_at = look_key(gch, st), time.time()
            ts, layout_key, t_start = 0.0, None, time.time()
            k = 0
            while not self.stop_evt.is_set():
                if self.idle():
                    break
                now = time.time()
                if now - look_at > 3:       # theme / font changed in the admin page: restyle without a restart
                    look_at = now
                    gch2, st2 = self.app.store.channel(self.cid) or gch, self.app.store.settings
                    if look_key(gch2, st2) != look:
                        gch, st, look = gch2, st2, look_key(gch2, st2)
                        idx = renderer.spot_idx
                        renderer = make_renderer(gch, st)
                        renderer.spot_idx = idx
                rows, spots = self._rows(now)
                try:
                    frame, canvas_h, lay = renderer.frame(rows, now, None, spots)
                except Exception:
                    # a theme failed to draw something: keep the guide on the air in the classic look
                    log.exception("guide: theme %s failed to draw; falling back to the classic look", renderer.T.id)
                    self.last_error = f"theme {renderer.T.name} failed to draw; showing the classic look"
                    Ft, Fd = self.app.theme_fonts(themes.get(themes.DEFAULT_THEME))
                    idx = renderer.spot_idx
                    renderer = GuideRenderer(Ft, images, b.W, b.H, branding.name(),
                                             (gch.get("clock") or {}).get("format", "12h"),
                                             themes.get(themes.DEFAULT_THEME), Fd)
                    renderer.spot_idx = idx
                    frame, canvas_h, lay = renderer.frame(rows, now, None, spots)
                key = (canvas_h, lay["scroll"], lay["rows_h"])
                if key != layout_key or proc is None or proc.proc.poll() is not None:
                    if proc:
                        proc.kill()
                        ts += (time.time() - t_start) + 0.2
                        self.fixer.boundary()
                    cmd = b.guide(gch, canvas_h, renderer.head_h, renderer.body_view, lay["rows_h"], lay["scroll"],
                                  float(gch.get("guide_scroll_speed") or 40), pick_music(gch.get("music_path")), ts)
                    proc = Proc(cmd, self.logf, "guide", stdin=True)
                    threading.Thread(target=self._pump, args=(proc,), daemon=True).start()
                    layout_key, t_start, k = key, time.time(), 0
                try:
                    proc.proc.stdin.write(frame)
                except (BrokenPipeError, OSError, ValueError):
                    self.last_error = " | ".join(list(proc.errors)[-3:])
                    proc.kill()
                    time.sleep(1)
                    continue
                k += 1
                delay = t_start + k - time.time()
                if delay > 0:
                    self.stop_evt.wait(delay)
        except Exception as e:
            log.exception("guide session crashed")
            self.last_error = str(e)
        finally:
            if proc:
                proc.kill()
            self.broadcast.close()
            self.app.sessions.discard(self)

    def _pump(self, proc):
        while True:
            chunk = proc.q.get()
            if chunk is None:
                return
            self.publish(chunk)


class WeatherSession(GuideSession):
    """The Weather channel: rotating screens rendered in Python (1 fps), a radar loop, and a crawl ffmpeg scrolls."""

    def _write_crawl(self, path, text):
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        for _ in range(20):          # ffmpeg re-reads the file every second; on Windows it may be open right now
            try:
                os.replace(tmp, path)
                return
            except OSError:
                time.sleep(0.05)

    def run(self):
        from .weathergfx import WeatherRenderer, crawl_text
        from .weather import DEFAULT_SLIDES
        proc = None
        try:
            b = self.app.builder()
            st = self.app.store.settings
            ch = self.app.store.channel(self.cid) or self.ch
            crawl_path = self.app.store.data_dir / "cache" / "weather" / f"crawl-{self.cid}.txt"
            crawl_path.parent.mkdir(parents=True, exist_ok=True)

            def make(ch, st):
                T = self.app.theme(ch)
                Ft, Fd = self.app.theme_fonts(T, ch.get("guide_font"), ch.get("guide_display_font"))
                return WeatherRenderer(T, Ft, Fd, b.W, b.H, (ch.get("clock") or {}).get("format", "12h"),
                                       branding.name(), self.app.header_logo(ch)), Ft

            def look_key(ch, st):
                return (self.app.theme(ch).key, ch.get("guide_font"), ch.get("guide_display_font"),
                        (ch.get("clock") or {}).get("format"), json.dumps(ch.get("weather") or {}, sort_keys=True),
                        branding.version(), self.app.header_logo(ch)["look"])

            def proc_key(ch):     # things baked into the ffmpeg command: a change restarts the encoder
                w = ch.get("weather") or {}
                return (ch.get("music_path"), w.get("crawl", True), w.get("crawl_speed"), self.app.theme(ch).key,
                        ch.get("guide_font"))

            R, Ft = make(ch, st)
            look, pkey, look_at = look_key(ch, st), None, time.time()
            slide_i, slide_t0 = 0, time.time()
            crawl = None
            ts, t_start, k = 0.0, time.time(), 0
            while not self.stop_evt.is_set():
                if self.idle():
                    break
                now = time.time()
                if now - look_at > 3:
                    look_at = now
                    ch2, st2 = self.app.store.channel(self.cid) or ch, self.app.store.settings
                    if look_key(ch2, st2) != look:
                        ch, st = ch2, st2
                        look = look_key(ch, st)
                        R, Ft = make(ch, st)
                cfg = ch.get("weather") or {}
                snap = self.app.weather.snapshot(ch, R.map_size, R.T.light)
                slides = [x for x in (cfg.get("slides") or DEFAULT_SLIDES) if x in DEFAULT_SLIDES]
                if not snap.get("alerts"):
                    slides = [x for x in slides if x != "alerts"]
                fut = (snap.get("radar") or {}).get("future") or {}
                if fut.get("unsupported") or (fut.get("fetched") and not fut.get("frames")):
                    slides = [x for x in slides if x != "radar_future"]     # outside the US, or no forecast yet
                slides = slides or ["current"]
                slide = slides[slide_i % len(slides)]
                dur = max(5, int(cfg.get("slide_seconds") or 10))
                if slide.startswith("radar"):
                    n = len(((snap.get("radar") or {}).get(slide[6:]) or {}).get("frames") or [])
                    dur = max(dur, 2 * (n + 2))          # at least two trips round the loop
                if now - slide_t0 >= dur:
                    slide_i, slide_t0 = slide_i + 1, now
                    slide = slides[slide_i % len(slides)]
                sub = 0
                if slide.startswith("radar"):
                    n = len(((snap.get("radar") or {}).get(slide[6:]) or {}).get("frames") or [])
                    sub = min(int(now - slide_t0) % (n + 2), max(0, n - 1)) if n else 0   # play, then hold the newest
                try:
                    img = R.frame(snap, slide, sub, now, slides)
                except Exception:
                    log.exception("weather: drawing %s failed", slide)
                    self.last_error = f"couldn't draw the {slide} screen"
                    slide_i, slide_t0 = slide_i + 1, now
                    continue
                text = crawl_text(snap, (ch.get("clock") or {}).get("format", "12h")) if cfg.get("crawl", True) else ""
                if text != crawl:
                    crawl = text
                    self._write_crawl(crawl_path, text or " ")
                pk = proc_key(ch)
                if pk != pkey or proc is None or proc.proc.poll() is not None:
                    if proc:
                        proc.kill()
                        ts += (time.time() - t_start) + 0.2
                        self.fixer.boundary()
                    c, s = R.T.c, R.s
                    hexc = lambda rgb: "0x%02x%02x%02x" % tuple(rgb)
                    cmd = b.weather(ch, crawl_file=str(crawl_path) if cfg.get("crawl", True) else None,
                                    crawl_font=Ft.path_for(crawl or "", True), crawl_y=R.crawl_y,
                                    crawl_x0=int(200 * s), crawl_size=int(25 * s), crawl_color=hexc(c["timebar_text"]),
                                    crawl_speed=float(cfg.get("crawl_speed") or 110), label=R._case("Weather"),
                                    label_color=hexc(readable(c["chan"], c["accent"], c["chan_text"])),
                                    label_box=hexc(c["chan"]), band=R.crawl_band, band_color=hexc(c["timebar"]),
                                    music=pick_music(ch.get("music_path")), ts_offset=ts)
                    proc = Proc(cmd, self.logf, "weather", stdin=True)
                    threading.Thread(target=self._pump, args=(proc,), daemon=True).start()
                    pkey, t_start, k = pk, time.time(), 0
                try:
                    proc.proc.stdin.write(img.tobytes())
                except (BrokenPipeError, OSError, ValueError):
                    self.last_error = " | ".join(list(proc.errors)[-3:])
                    proc.kill()
                    time.sleep(1)
                    continue
                k += 1
                delay = t_start + k - time.time()
                if delay > 0:
                    self.stop_evt.wait(delay)
        except Exception as e:
            log.exception("weather session crashed")
            self.last_error = str(e)
        finally:
            if proc:
                proc.kill()
            self.broadcast.close()
            self.app.sessions.discard(self)


class Sessions:
    def __init__(self, app):
        self.app = app
        self.lock = threading.Lock()
        self.active = {}

    def get(self, ch):
        with self.lock:
            s = self.active.get(ch["id"])
            if s and s.is_alive() and not s.stop_evt.is_set():
                return s
            kind = {"guide": GuideSession, "weather": WeatherSession}.get(ch.get("type"), ChannelSession)
            s = kind(self.app, ch)
            self.active[ch["id"]] = s
            s.start()
            return s

    def discard(self, s):
        with self.lock:
            if self.active.get(s.cid) is s:
                del self.active[s.cid]

    def reload(self, cid):
        s = self.active.get(cid)
        if isinstance(s, ChannelSession):
            s.reload()
        elif s:
            s.stop()

    def stop(self, cid):
        s = self.active.get(cid)
        if s:
            s.stop()

    def stop_all(self):
        for s in list(self.active.values()):
            s.stop()

    def status(self):
        out = {}
        for cid, s in list(self.active.items()):
            out[cid] = {"viewers": s.broadcast.count, "uptime": int(time.time() - s.started_at),
                        "bytes": s.broadcast.total, "error": s.last_error, "speed": getattr(s, "speed", None)}
        return out

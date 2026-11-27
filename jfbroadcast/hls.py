"""On-demand HLS for Chromecast (and anything else that prefers HLS).

Chromecasts can't play a raw MPEG-TS-over-HTTP stream, but they do play live HLS. When an HLS playlist is requested,
we subscribe to the channel's live broadcast (like any other viewer) and let ffmpeg *remux* it into short HLS
segments - no re-encoding, so it costs almost nothing. It stops by itself once nobody fetches it any more.
"""
import logging
import queue
import shutil
import subprocess
import threading
import time
import uuid

from .config import NO_WINDOW

log = logging.getLogger("hls")

IDLE_AFTER = 25          # seconds without playlist/segment requests before an HLS stream is torn down
SEGMENT_SECONDS = 2
HOLD_BACK = 2            # newest segments hidden from players (they're complete, so the player never waits on them)
PLAYER_DELAY = 10        # seconds behind the visible live edge the player is asked to sit (its buffer)
STALL_AFTER = 15         # a watched stream whose playlist hasn't moved for this long is restarted


class HLSStream:
    def __init__(self, app, ch):
        self.app = app
        self.cid = ch["id"]
        self.fmt = (app.store.settings.get("cast_hls_format") or "fmp4").lower()
        root = app.store.data_dir / "hls"
        for old in root.glob(f"{ch['id']}-*"):            # leftovers from a previous run
            shutil.rmtree(old, ignore_errors=True)
        self.dir = root / f"{ch['id']}-{uuid.uuid4().hex[:8]}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.last_access = self.started = time.time()
        self.stopped = False
        self.session = app.sessions.get(ch)
        self.q = self.session.broadcast.subscribe(backlog=True)   # start with up to ~20 s already buffered
        ext = "m4s" if self.fmt == "fmp4" else "ts"
        cmd = [app.ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-fflags", "+genpts",
               "-f", "mpegts", "-i", "pipe:0", "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy",
               "-bsf:a", "aac_adtstoasc",
               "-f", "hls", "-hls_time", str(SEGMENT_SECONDS), "-hls_list_size", "20",
               "-hls_flags", "delete_segments+independent_segments+omit_endlist+temp_file",
               "-hls_segment_type", "fmp4" if self.fmt == "fmp4" else "mpegts",
               "-hls_segment_filename", f"seg%06d.{ext}"]
        if self.fmt == "fmp4":
            cmd += ["-hls_fmp4_init_filename", "init.mp4"]
        cmd.append("live.m3u8")
        # run inside the stream's own folder with plain file names: no Windows drive-letter/backslash surprises
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, cwd=str(self.dir),
                                     stderr=subprocess.PIPE, bufsize=0, creationflags=NO_WINDOW)
        threading.Thread(target=self._pump, daemon=True, name=f"hls-{self.cid}").start()
        threading.Thread(target=self._err, daemon=True).start()

    def _pump(self):
        try:
            while not self.stopped:
                try:
                    chunk = self.q.get(timeout=5)
                except queue.Empty:
                    continue
                if chunk is None:
                    break
                self.proc.stdin.write(chunk)
        except (BrokenPipeError, OSError, ValueError):
            pass
        self.stop()

    def _err(self):
        for line in iter(self.proc.stderr.readline, b""):
            txt = line.decode("utf-8", "replace").rstrip()
            if txt:
                self.session.logf(f"[hls] {txt}")

    @property
    def alive(self):
        return not self.stopped and self.proc.poll() is None

    def touch(self):
        self.last_access = time.time()

    def stop(self):
        if self.stopped:
            return
        self.stopped = True
        try:
            self.session.broadcast.unsubscribe(self.q)
        except Exception:
            pass
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.kill()
        except Exception:
            pass
        threading.Timer(3, lambda: shutil.rmtree(self.dir, ignore_errors=True)).start()

    def playlist_age(self):
        """Seconds since ffmpeg last rewrote the playlist (it does every ~2 s while video flows)."""
        try:
            return time.time() - (self.dir / "live.m3u8").stat().st_mtime
        except OSError:
            return time.time() - self.started

    def ready(self, min_segments=HOLD_BACK + 3):
        p = self.dir / "live.m3u8"
        try:
            return p.read_text(encoding="utf-8").count("#EXTINF") >= min_segments
        except OSError:
            return False


def hold_back(playlist, n=HOLD_BACK):
    """Drop the newest n segments from a live media playlist. The player then never sits right at the live edge
    (where it would stall every time it waits for the next segment); it always has n segments of slack."""
    lines = playlist.splitlines()
    seg_idx = [i for i, l in enumerate(lines) if l and not l.startswith("#")]
    if len(seg_idx) > n + 1:
        lines = lines[:seg_idx[-n - 1] + 1]    # keep everything up to and including the (n+1)-th newest segment
    # and ask the player itself to sit a further PLAYER_DELAY seconds behind what it can see
    tags = [f"#EXT-X-SERVER-CONTROL:HOLD-BACK={PLAYER_DELAY:.1f}", f"#EXT-X-START:TIME-OFFSET=-{PLAYER_DELAY:.1f}"]
    at = next((i + 1 for i, l in enumerate(lines) if l.startswith("#EXT-X-VERSION")), 1)
    lines[at:at] = [t for t in tags if t.split(":")[0] not in playlist]
    return "\n".join(lines) + "\n"

def master_playlist(settings):
    """Tell the player up front exactly what's in the stream (Chromecasts otherwise assume Main@3.0)."""
    try:
        w, h = (int(x) for x in str(settings.get("resolution") or "1280x720").lower().split("x"))
    except ValueError:
        w, h = 1280, 720
    fps = int(settings.get("framerate") or 30)
    level = "2a" if (h > 720 and fps > 30) else "29"          # High@4.2 for 1080p50/60, otherwise High@4.1
    bw = (int(settings.get("video_bitrate_kbps") or 4000) + int(settings.get("audio_bitrate_kbps") or 192)) * 1100
    return ("#EXTM3U\n#EXT-X-VERSION:7\n#EXT-X-INDEPENDENT-SEGMENTS\n"
            f'#EXT-X-STREAM-INF:BANDWIDTH={bw},AVERAGE-BANDWIDTH={int(bw * 0.9)},CODECS="avc1.6400{level},mp4a.40.2",'
            f"RESOLUTION={w}x{h},FRAME-RATE={fps:.3f}\nlive.m3u8\n")


class HLSManager:
    def __init__(self, app):
        self.app = app
        self.streams = {}
        self.lock = threading.Lock()
        self.hits = {}          # client ip -> {"t": last request time, "cid": channel, "n": request count}
        self.restarts = {}      # cid -> time of the last stall restart
        self._reaper_started = False

    def note(self, ip, cid, name):
        h = self.hits.get(ip)
        if not h or h["cid"] != cid or time.time() - h["t"] > 60:
            log.info("HLS: %s started loading channel %s (%s)", ip, cid, name)
            h = {"t": 0, "cid": cid, "n": 0, "first": time.time()}
        h.update(t=time.time(), n=h["n"] + 1)
        self.hits[ip] = h
        with self.lock:
            if not self._reaper_started:          # one janitor thread for all streams
                self._reaper_started = True
                threading.Thread(target=self._reaper, daemon=True, name="hls-reaper").start()

    def ensure(self, ch):
        with self.lock:
            s = self.streams.get(ch["id"])
            if s is None or not s.alive:
                s = HLSStream(self.app, ch)
                self.streams[ch["id"]] = s
            s.touch()
            return s

    def get(self, cid):
        s = self.streams.get(cid)
        return s if s and s.alive else None

    def stop(self, cid):
        with self.lock:
            s = self.streams.pop(cid, None)
        if s:
            s.stop()

    def stop_all(self):
        with self.lock:
            streams, self.streams = list(self.streams.values()), {}
        for s in streams:
            s.stop()

    def _reaper(self):
        while True:
            time.sleep(5)
            now = time.time()
            with self.lock:
                for cid, s in list(self.streams.items()):
                    try:
                        if not s.alive or now - s.last_access > IDLE_AFTER:
                            s.stop()
                            del self.streams[cid]
                            log.info("HLS for %s stopped (idle)", cid)
                        elif now - s.started > 30 and s.playlist_age() > STALL_AFTER:
                            # someone is watching but no new segments are being made: start it over (the cast
                            # watchdog then reloads the TV onto the fresh stream)
                            log.warning("HLS for %s stalled (no new segments for %.0f s); restarting", cid, s.playlist_age())
                            s.stop()
                            del self.streams[cid]
                            self.restarts[cid] = now
                    except Exception:
                        log.exception("HLS reaper error")

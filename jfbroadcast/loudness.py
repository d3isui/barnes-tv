"""Background-music loudness.

Music is mastered much louder than TV shows and movies (often -8 to -14 LUFS against roughly -23 for TV), so a bumper or
Up Next card with music jumps out at you. Each music file is measured once (EBU R128 integrated loudness, the same
measure broadcasters use), in the background at low priority, and remembered on disk. When a music bed plays it gets
a fixed gain that brings it to the target level: no pumping, and short bumpers sound right from the first second.
"""
import collections
import json
import logging
import os
import re
import subprocess
import threading
from pathlib import Path

from .config import NO_WINDOW

log = logging.getLogger("loudness")

TV_LUFS = -23.0          # broadcast TV level (EBU R128 / ATSC A/85 are -23 / -24)
NORMALIZED_LUFS = -16.0  # what "Even out loudness" brings shows to (loudnorm I=-16 in ffmpeg.segment)
ASSUMED_LUFS = -12.0     # a typical modern music master, used until a file has been measured
AUDIO_EXT = {".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wav"}

_lock = threading.Lock()
_cache = {}              # "path|mtime|size" -> LUFS (None = couldn't be measured)
_queue = collections.deque()
_queued = set()
_state = {"file": None, "ffmpeg": None, "thread": None, "dirty": 0}


def init(cache_file, ffmpeg_getter):
    """cache_file: where measurements are kept; ffmpeg_getter: callable returning the ffmpeg path."""
    _state["file"], _state["ffmpeg"] = Path(cache_file), ffmpeg_getter
    try:
        _cache.update(json.loads(_state["file"].read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass


def _key(path):
    try:
        s = os.stat(path)
    except OSError:
        return None
    return f"{os.path.abspath(path)}|{int(s.st_mtime)}|{s.st_size}"


def lufs(path):
    """Measured loudness of a music file, or None if it hasn't been measured yet (it is queued, and measured shortly)."""
    k = _key(path)
    if not k:
        return None
    with _lock:
        if k in _cache:
            return _cache[k]
    _enqueue([path], front=True)
    return None


def gain_db(path, target, extra_db=0.0):
    """dB to apply to this music file so it plays at `target` LUFS, plus the user's own adjustment."""
    measured = lufs(path)
    g = target - (ASSUMED_LUFS if measured is None else measured) + extra_db
    return max(-40.0, min(15.0, g))


def audio_files(path, limit=5000):
    p = Path(path or "")
    if not str(path or "").strip():
        return []
    if p.is_file():
        return [str(p)] if p.suffix.lower() in AUDIO_EXT else []
    out = []
    if p.is_dir():
        for f in p.rglob("*"):
            if f.suffix.lower() in AUDIO_EXT:
                out.append(str(f))
                if len(out) >= limit:
                    break
    return out


def prewarm(paths):
    """Queue every music file under these files/folders for measuring (skips ones already measured)."""
    files = []
    for p in {str(x).strip().strip('"') for x in paths if x}:
        try:
            files += audio_files(p)
        except OSError:
            pass
    _enqueue(files)


def status(path):
    """(measured, total) for the music files under a file/folder path."""
    files = audio_files(path)
    with _lock:
        done = sum(1 for f in files if _key(f) in _cache)
    return done, len(files)


def _enqueue(files, front=False):
    started = False
    with _lock:
        for f in files:
            k = _key(f)
            if not k or k in _cache or k in _queued:
                continue
            _queued.add(k)
            (_queue.appendleft if front else _queue.append)((f, k))
        if _queue and not (_state["thread"] and _state["thread"].is_alive()) and _state["ffmpeg"]:
            _state["thread"] = threading.Thread(target=_worker, daemon=True, name="music-loudness")
            started = True
    if started:
        _state["thread"].start()


def _worker():
    while True:
        with _lock:
            if not _queue:
                break
            path, k = _queue.popleft()
        val = measure(path)
        with _lock:
            _queued.discard(k)
            _cache[k] = val
            _state["dirty"] += 1
            if _state["dirty"] >= 10 or not _queue:
                _save()


def _save():
    if not _state["file"]:
        return
    try:
        _state["file"].parent.mkdir(parents=True, exist_ok=True)
        tmp = _state["file"].with_suffix(".tmp")
        tmp.write_text(json.dumps(_cache), encoding="utf-8")
        os.replace(tmp, _state["file"])
        _state["dirty"] = 0
    except OSError as e:
        log.warning("couldn't save music loudness: %s", e)


def measure(path):
    """Integrated loudness (LUFS) of the first 15 minutes of a file, or None."""
    ffmpeg = _state["ffmpeg"]() if callable(_state["ffmpeg"]) else _state["ffmpeg"]
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-nostats", "-vn", "-sn", "-dn", "-i", path, "-t", "900",
           "-af", "ebur128=framelog=verbose", "-f", "null", "-"]
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = NO_WINDOW | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
    else:
        kw["preexec_fn"] = lambda: os.nice(10)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=300, **kw)
    except Exception as e:
        log.info("couldn't measure %s: %s", path, e)
        return None
    m = re.findall(r"I:\s*(-?[\d.]+|-inf) LUFS", r.stderr)
    if not m or m[-1] == "-inf":
        log.info("no loudness for %s", os.path.basename(path))
        return None
    val = float(m[-1])
    return val if val > -70 else None

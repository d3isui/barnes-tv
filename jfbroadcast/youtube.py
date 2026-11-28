"""YouTube as a channel source: videos, playlists and whole channels, streamed straight from YouTube (nothing is
downloaded to disk).

yt-dlp does the talking to YouTube. It's run as a separate process (`python -m yt_dlp`), so updating it never needs
a server restart, and YouTube's JavaScript challenges are solved with the Deno runtime that comes with the `deno`
Python package. An optional cookies file (exported from a browser that's signed in to YouTube) is passed along for
age-restricted, members-only and private videos, and for YouTube Premium's higher-bitrate formats.

Items use ids like "yt-dQw4w9WgXcQ" (safe in file names) and type "YouTube".
"""
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path

from .config import NO_WINDOW

log = logging.getLogger("youtube")

PREFIX = "yt-"
LIST_LIMIT_DEFAULT = 500             # newest videos taken from a channel / playlist (set per source)
_state = {"data_dir": None, "settings": lambda: {}}
_resolved = {}                       # (video id, height) -> (expires, result)
_lock = threading.Lock()
_inflight = {}


def init(data_dir, settings_getter):
    _state["data_dir"] = Path(data_dir)
    _state["settings"] = settings_getter


def is_youtube(item_or_id):
    iid = item_or_id.get("id", "") if isinstance(item_or_id, dict) else (item_or_id or "")
    return str(iid).startswith(PREFIX)


def video_id(item_or_id):
    iid = item_or_id.get("id", "") if isinstance(item_or_id, dict) else item_or_id
    return str(iid)[len(PREFIX):]


def cookies_path():
    d = _state["data_dir"]
    return (d / "youtube" / "cookies.txt") if d else None


def has_cookies():
    p = cookies_path()
    return bool(p and p.is_file() and p.stat().st_size > 0)


# ---------------------------------------------------------------- running yt-dlp
def installed():
    """(yt-dlp version or None, JS runtime path or None)"""
    try:
        import yt_dlp.version as v
        ver = v.__version__
    except Exception:
        ver = None
    return ver, js_runtime()


def js_runtime():
    """Deno from the `deno` pip package, else a deno or node on PATH."""
    try:
        import deno
        p = deno.find_deno_bin()
        if p and os.path.isfile(p):
            return ("deno", p)
    except Exception:
        pass
    import shutil
    for name in ("deno", "node"):
        p = shutil.which(name)
        if p:
            return (name, p)
    home = Path.home() / ".deno" / "bin" / ("deno.exe" if os.name == "nt" else "deno")
    if home.is_file():
        return ("deno", str(home))
    return None


def _cmd(args):
    cmd = [sys.executable, "-m", "yt_dlp", "--no-warnings", "--ignore-config", "--no-cache-dir"]
    rt = js_runtime()
    if rt:
        cmd += ["--js-runtimes", f"{rt[0]}:{rt[1]}"]
    if has_cookies():
        cmd += ["--cookies", str(cookies_path())]
    return cmd + args


def _run(args, timeout):
    kw = {"creationflags": NO_WINDOW} if os.name == "nt" else {}
    r = subprocess.run(_cmd(args), capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout, stdin=subprocess.DEVNULL, **kw)
    if r.returncode != 0 and not r.stdout.strip():
        err = (r.stderr or "").strip().splitlines()
        msg = next((l for l in reversed(err) if "ERROR" in l), err[-1] if err else f"yt-dlp exited with {r.returncode}")
        raise YouTubeError(clean_error(msg))
    try:
        return json.loads(r.stdout)
    except ValueError:
        raise YouTubeError("YouTube didn't send anything readable back")


class YouTubeError(Exception):
    pass


def clean_error(msg):
    msg = re.sub(r"^ERROR:\s*(\[[^\]]+\]\s*)?", "", msg.strip())
    if "Sign in to confirm" in msg:
        return ("YouTube wants you to sign in to confirm you're not a bot. Add a cookies file under "
                "Settings → YouTube.")
    if "Private video" in msg or "members-only" in msg.lower():
        return msg + " (a cookies file from an account that can see it is needed: Settings → YouTube)"
    return msg[:300]


# ---------------------------------------------------------------- listing a source
_CHANNEL_RE = re.compile(r"^https?://(www\.|m\.)?youtube\.com/(@[^/?#]+|channel/[^/?#]+|c/[^/?#]+|user/[^/?#]+)/?$", re.I)


def normalize_url(url):
    url = (url or "").strip().strip('"')
    if url and not re.match(r"^https?://", url, re.I):
        if url.startswith("@"):
            url = "https://www.youtube.com/" + url
        elif re.fullmatch(r"[A-Za-z0-9_-]{11}", url):
            url = "https://www.youtube.com/watch?v=" + url
        else:
            url = "https://" + url
    m = _CHANNEL_RE.match(url.split("?")[0])
    if m:                                         # a channel's home page: take its uploads ("Videos" tab)
        url = url.split("?")[0].rstrip("/") + "/videos"
    return url


def kind_of(url):
    u = url.lower()
    if "list=" in u and "watch?" not in u:
        return "playlist"
    if re.search(r"youtube\.com/(@|channel/|c/|user/)", u):
        return "channel"
    return "video"


def _item(e, channel=None, channel_id=None, pos=0):
    vid = e.get("id")
    if not vid or not re.fullmatch(r"[A-Za-z0-9_-]{11}", str(vid)):
        return None
    if e.get("live_status") in ("is_live", "is_upcoming", "post_live"):
        return None
    dur = e.get("duration")
    if not dur or dur < 5:
        return None
    ch = e.get("channel") or e.get("uploader") or channel or "YouTube"
    cid = e.get("channel_id") or e.get("uploader_id") or channel_id or ch
    date = str(e.get("upload_date") or e.get("release_date") or "")
    premiere = f"{date[:4]}-{date[4:6]}-{date[6:8]}" if len(date) == 8 else ""
    desc = (e.get("description") or "").strip()
    return {"id": PREFIX + vid, "type": "YouTube", "title": (e.get("title") or vid).strip(), "episode_title": "",
            "series_id": "yt:" + str(cid), "channel": ch, "season": None, "episode": None,
            "year": int(date[:4]) if len(date) == 8 else None,
            "overview": desc[:400] if desc else f"On YouTube from {ch}.", "genres": [], "rating": "",
            "duration": float(dur), "premiere": premiere, "image_id": PREFIX + vid, "path": "", "location": "Remote",
            "chapters": [c.get("start_time") for c in (e.get("chapters") or []) if c.get("start_time")], "pos": pos}


def list_source(url, limit=None):
    """Every playable video of a YouTube URL, in viewing order (playlists as listed, channels oldest first).
    Returns (title, items, skipped)."""
    url = normalize_url(url)
    limit = int(limit or LIST_LIMIT_DEFAULT)
    kind = kind_of(url)
    if kind == "video":
        d = _run(["-J", "--no-playlist", url], timeout=90)
        it = _item(d)
        return d.get("title") or url, ([it] if it else []), (0 if it else 1)
    d = _run(["-J", "--flat-playlist", "--playlist-end", str(limit), url], timeout=300)
    entries = d.get("entries") or []
    # a channel URL that still came back as a list of tabs: use its Videos tab
    if entries and all((e.get("_type") == "playlist" or e.get("ie_key") == "YoutubeTab") and not e.get("duration")
                       for e in entries if e):
        vids = next((e for e in entries if e and "videos" in str(e.get("url", "")).lower()), entries[0])
        d = _run(["-J", "--flat-playlist", "--playlist-end", str(limit), vids.get("url")], timeout=300)
        entries = d.get("entries") or []
    owner, owner_id = d.get("channel") or d.get("uploader"), d.get("channel_id") or d.get("uploader_id")
    items, skipped = [], 0
    for n, e in enumerate(entries):
        it = _item(e or {}, owner, owner_id, n)
        if it:
            items.append(it)
        else:
            skipped += 1
    if kind == "channel":
        items.reverse()                               # uploads come newest first: play a channel oldest first
        for n, it in enumerate(items):
            it["pos"] = n
    title = d.get("title") or owner or url
    title = re.sub(r"\s*-\s*Videos$", "", title)
    return title, items, skipped


# ---------------------------------------------------------------- playing a video
FORMAT = ("bv*[height<={h}][vcodec^=avc1]+ba[ext=m4a]/bv*[height<={h}][vcodec^=avc1]+ba/"
          "bv*[height<={h}]+ba/b[height<={h}]/bv*+ba/b")


def _expiry(u):
    try:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(u).query)
        return float(q.get("expire", [0])[0]) or time.time() + 3 * 3600
    except Exception:
        return time.time() + 3 * 3600


def _headers(h):
    h = dict(h or {})
    return "".join(f"{k}: {v}\r\n" for k, v in h.items() if k.lower() in ("user-agent", "referer", "origin", "cookie",
                                                                              "accept", "accept-language"))


def resolve(item_or_id, height=720):
    """Stream addresses for a video: {"video": url, "audio": url or None, "headers": str, "title": ...}.
    Cached until shortly before YouTube's links expire; concurrent calls for the same video share one lookup."""
    vid = video_id(item_or_id) if is_youtube(item_or_id) else str(item_or_id)
    key = (vid, int(height))
    with _lock:
        hit = _resolved.get(key)
        if hit and hit[0] > time.time() + 600:
            return hit[1]
        ev = _inflight.get(key)
        owner = ev is None
        if owner:
            ev = _inflight[key] = threading.Event()
    if not owner:
        ev.wait(120)
        with _lock:
            hit = _resolved.get(key)
        if hit:
            return hit[1]
        raise YouTubeError("looking up the video took too long")
    try:
        d = _run(["-J", "--no-playlist", "-f", FORMAT.format(h=int(height)),
                  "https://www.youtube.com/watch?v=" + vid], timeout=90)
        fmts = d.get("requested_formats") or [d]
        v = fmts[0]
        a = fmts[1] if len(fmts) > 1 else None
        if not v.get("url"):
            raise YouTubeError("YouTube didn't give a playable stream for this video")
        out = {"video": v["url"], "audio": a["url"] if a else None, "headers": _headers(v.get("http_headers") or d.get("http_headers")),
               "audio_headers": _headers((a or {}).get("http_headers")), "title": d.get("title"),
               "format": "+".join(str(f.get("format_id")) for f in fmts), "height": v.get("height")}
        exp = min(_expiry(out["video"]), time.time() + 5 * 3600)
        with _lock:
            _resolved[key] = (exp, out)
            if len(_resolved) > 300:
                for k in sorted(_resolved, key=lambda k: _resolved[k][0])[:100]:
                    _resolved.pop(k, None)
        return out
    finally:
        with _lock:
            _inflight.pop(key, None)
        ev.set()


def prefetch(item, height=720):
    """Look a video up in the background (the streamer calls this for what's on next)."""
    if not is_youtube(item):
        return
    key = (video_id(item), int(height))
    with _lock:
        hit = _resolved.get(key)
        if (hit and hit[0] > time.time() + 900) or key in _inflight:
            return

    def run():
        try:
            resolve(item, height)
        except Exception as e:
            log.info("couldn't look up YouTube video %s ahead of time: %s", key[0], e)
    threading.Thread(target=run, daemon=True, name="yt-prefetch").start()


def thumbnail_bytes(item_id, h):
    """The video's thumbnail from YouTube's image server."""
    from . import net
    vid = video_id(item_id)
    for name in (("maxresdefault", "hqdefault") if h > 360 else ("hqdefault", "mqdefault")):
        try:
            with net.urlopen(f"https://i.ytimg.com/vi/{vid}/{name}.jpg", timeout=15) as r:
                data = r.read()
            if len(data) > 2000:                       # YouTube's grey "no thumbnail" placeholder is tiny
                return data
        except Exception:
            continue
    raise YouTubeError("no thumbnail")


# ---------------------------------------------------------------- keeping yt-dlp current
_update = {"running": False, "last": None, "message": ""}


def update(packages=("yt-dlp", "yt-dlp-ejs", "deno")):
    """pip install -U yt-dlp (YouTube changes often; a new yt-dlp is usually the fix)."""
    if _update["running"]:
        return False
    _update["running"] = True

    def run():
        try:
            kw = {"creationflags": NO_WINDOW} if os.name == "nt" else {}
            r = subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q", "-U", *packages],
                               capture_output=True, text=True, timeout=600, **kw)
            ok = r.returncode == 0
            _update["message"] = "Up to date." if ok else (r.stderr or r.stdout or "pip failed").strip()[-400:]
            if ok:
                import importlib
                import yt_dlp.version
                importlib.reload(yt_dlp.version)
        except Exception as e:
            _update["message"] = str(e)
        finally:
            _update["running"], _update["last"] = False, time.time()
            with _lock:
                _resolved.clear()
    threading.Thread(target=run, daemon=True, name="yt-update").start()
    return True


def update_status():
    return dict(_update)

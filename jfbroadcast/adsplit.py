"""Find the individual spots inside long commercial compilations.

Compilations ("80s commercials, 12 minutes") are usually a string of 10/15/30/60-second ads with a few black,
silent frames between them. One low-resolution pass of ffmpeg over the file finds:
  * black frames (blackdetect),
  * silence (silencedetect),
  * hard scene cuts (scdet),
and `find_spots` turns those into [start, end] times for each ad. Nothing is cut or re-encoded: the scheduler plays
each spot straight from the original file by seeking to its start. Results are cached per file, so each file is
scanned once (one at a time, at low priority, in the background).
"""

import json
import logging
import os
import re
import subprocess
import threading
import time
from collections import deque

from .config import NO_WINDOW
from .jellyfin import map_path

log = logging.getLogger("adsplit")

SCAN_VERSION = 1
STANDARD = (10.0, 15.0, 20.0, 30.0, 45.0, 60.0, 90.0, 120.0)   # common ad lengths (seconds)
MIN_SPOT = 4.0          # shorter pieces are glued to a neighbour
LONG_SPOT = 62.0        # longer than any usual spot: look harder for a cut inside it
VERY_LONG = 125.0
BELOW_NORMAL = 0x00004000  # Windows: BELOW_NORMAL_PRIORITY_CLASS


def near_standard(d, tol=1.5):
    return any(abs(d - s) <= tol for s in STANDARD)


PREFER = {30.0: 0.0, 15.0: 0.15, 60.0: 0.35, 20.0: 0.4, 10.0: 0.45, 45.0: 0.6, 90.0: 0.8, 120.0: 0.9}


def piece_cost(length, tol=1.0):
    best = None
    for std, pen in PREFER.items():
        d = abs(length - std)
        if d <= tol:
            c = pen + d / 2
            best = c if best is None else min(best, c)
    return best


def partition(a, b, gaps):
    """Cheapest way to cut [a, b] at some of `gaps` so every part is a standard ad length; None if impossible."""
    gaps = sorted(gaps)[:400]
    nodes = [(None, a)] + [(g, g[1]) for g in gaps]          # (gap, where the next part starts)
    ends = [g[0] for g in gaps] + [b]                         # where a part may end
    INF = float("inf")
    best = [INF] * len(nodes)
    prev = [None] * len(nodes)
    best[0] = 0.0
    final = (INF, None)
    for i, (_, start) in enumerate(nodes):
        if best[i] == INF:
            continue
        for j, end in enumerate(ends):
            if end <= start:
                continue
            c = piece_cost(end - start)
            if c is None:
                continue
            if j == len(ends) - 1:
                if best[i] + c < final[0]:
                    final = (best[i] + c, i)
            elif best[i] + c < best[j + 1]:
                best[j + 1], prev[j + 1] = best[i] + c, i
    if final[1] is None:
        return None
    out, i = [], final[1]
    while i:
        out.append(nodes[i][0])
        i = prev[i]
    return out


def find_spots(blacks, silences, scenes, total, chapters=None):
    """blacks / silences: [(start, end)], scenes: [t], total: file length (s).
    Returns (spots [[start, end]], method)."""
    total = float(total)
    # chapter marks that look like one chapter per ad win outright
    if chapters:
        marks = sorted({0.0, *[c for c in chapters if 0 < c < total - 1]}, key=float) + [total]
        pieces = [(a, b) for a, b in zip(marks, marks[1:])]
        if len(pieces) >= 2 and all(MIN_SPOT <= b - a <= 180 for a, b in pieces):
            return [[round(a, 3), round(b, 3)] for a, b in pieces], "chapters"
    blacks = sorted((float(a), float(b)) for a, b in blacks if b > a)
    silences = sorted((float(a), float(min(b, total))) for a, b in silences if b > a)

    def silent_near(a, b, pad=0.3):
        return any(ss < b + pad and se > a - pad for ss, se in silences)

    # where the picture actually starts / ends (compilations often open and close on black)
    start, end = 0.0, total
    for a, b in blacks:
        if a <= 0.5:
            start = max(start, b)
        if b >= total - 0.5:
            end = min(end, a)
    if end - start < MIN_SPOT:
        return [[0.0, round(total, 3)]], "whole"
    # candidate gaps between ads: (a, b, strength)  3 = black + silence, 2 = black only, 1 = silence only
    gaps = []
    for a, b in blacks:
        if start + 1 < a and b < end - 1:
            if b - a > 2.5 and not silent_near(a, b):
                continue                 # a long dark scene with sound: part of an ad, not a gap
            gaps.append((a, b, 3 if silent_near(a, b) else 2))
    for a, b in silences:
        if b - a >= 0.35 and start + 1 < a and b < end - 1 and not any(ga - 0.3 < b and gb + 0.3 > a for ga, gb, _ in gaps):
            gaps.append((a, b, 1))
    for t in scenes:                     # a hard cut is a zero-length gap
        if start + 1 < t < end - 1 and not any(ga - 0.5 < t < gb + 0.5 for ga, gb, _ in gaps):
            gaps.append((t, t, 0))
    gaps.sort()
    strong = [g for g in gaps if g[2] == 3]
    if not strong:                       # no silence between ads (music runs on): black alone is the separator
        strong = [g for g in gaps if g[2] == 2]
    cuts = list(strong)

    def pieces_of(cs):
        cs = sorted(cs)
        edges = [(None, start)] + [(g[0], g[1]) for g in cs] + [(end, None)]
        return [(edges[i][1], edges[i + 1][0]) for i in range(len(edges) - 1)]

    # refine 1: black without silence between two pieces that each look like a whole ad (30 + 30 ...)
    changed = True
    while changed:
        changed = False
        for a, b in pieces_of(cuts):
            best = None
            for g in gaps:
                if g[2] != 2 or g in cuts or not (a + MIN_SPOT <= g[0] and g[1] <= b - MIN_SPOT):
                    continue
                left, right = g[0] - a, b - g[1]
                if (near_standard(left) and (near_standard(right) or right > LONG_SPOT)) or b - a > LONG_SPOT:
                    score = (0 if near_standard(left) else 1, abs(left - 30))
                    if best is None or score < best[0]:
                        best = (score, g)
            if best:
                cuts.append(best[1])
                changed = True
                break
    # refine 2: a piece too long to be one ad is probably several joined by hard cuts / short pauses:
    # partition it so every part is a standard ad length (30 s preferred, then 15, 60, ...)
    for a, b in pieces_of(cuts):
        if b - a > LONG_SPOT:
            inside = [g for g in gaps if g not in cuts and a + MIN_SPOT <= g[0] and g[1] <= b - MIN_SPOT]
            cuts += partition(a, b, inside) or []
    spots = [[a, b] for a, b in pieces_of(cuts)]
    # glue slivers to a neighbour
    i = 0
    while i < len(spots) and len(spots) > 1:
        a, b = spots[i]
        if b - a < MIN_SPOT:
            if i > 0:
                spots[i - 1][1] = b
            else:
                spots[1][0] = a
            spots.pop(i)
        else:
            i += 1
    return [[round(a, 3), round(b, 3)] for a, b in spots], ("detected" if len(spots) > 1 else "whole")


_RX = {
    "black": re.compile(r"black_start:\s*([\d.]+)\s+black_end:\s*([\d.]+)"),
    "s_start": re.compile(r"silence_start:\s*(-?[\d.]+)"),
    "s_end": re.compile(r"silence_end:\s*([\d.]+)"),
    "scene": re.compile(r"lavfi\.scd\.score:\s*([\d.]+),\s*lavfi\.scd\.time:\s*([\d.]+)"),
    "dur": re.compile(r"Duration:\s*(\d+):(\d+):([\d.]+)"),
}


def parse_log(text):
    blacks, silences, scenes, s0, dur = [], [], [], None, None
    for line in text.splitlines():
        m = _RX["black"].search(line)
        if m:
            blacks.append((float(m.group(1)), float(m.group(2))))
            continue
        m = _RX["s_start"].search(line)
        if m:
            s0 = max(0.0, float(m.group(1)))
            continue
        m = _RX["s_end"].search(line)
        if m and s0 is not None:
            silences.append((s0, float(m.group(1))))
            s0 = None
            continue
        m = _RX["scene"].search(line)
        if m:
            scenes.append(float(m.group(2)))
            continue
        m = _RX["dur"].search(line)
        if m and dur is None:
            dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    return blacks, silences, scenes, s0, dur


class AdSplitter:
    """Background scanner + cache of compilation spots."""

    def __init__(self, app):
        self.app = app
        self.dir = app.store.data_dir / "cache" / "adsplit"
        self.queue = deque()
        self.queued = set()
        self.current = None          # {"id", "title", "progress"}
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.thread = None
        self.done_since_refresh = 0
        self._mem = {}

    # ---- cache
    def _path(self, iid):
        return self.dir / f"{re.sub(r'[^A-Za-z0-9_-]', '_', iid)}.json"

    def result(self, item):
        """The cached scan for an item, or None if it hasn't been scanned (or the file changed)."""
        iid = item["id"]
        r = self._mem.get(iid)
        if r is None:
            p = self._path(iid)
            try:
                r = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
            except Exception:
                r = None
            self._mem[iid] = r
        if not r or r.get("version") != SCAN_VERSION:
            return None
        if abs(float(r.get("duration") or 0) - float(item.get("duration") or 0)) > 2:
            return None              # the file was replaced
        return r

    def _save(self, iid, r):
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self._path(iid).with_suffix(".tmp")
        tmp.write_text(json.dumps(r), encoding="utf-8")
        os.replace(tmp, self._path(iid))
        self._mem[iid] = r

    def set_mode(self, item, mode):
        """mode: auto (split) | whole (play the file as one commercial)."""
        r = self.result(item) or {"version": SCAN_VERSION, "duration": item.get("duration"), "spots": None,
                                  "title": item.get("title")}
        r["mode"] = mode
        self._save(item["id"], r)

    def forget(self, item):
        r = self.result(item)
        mode = (r or {}).get("mode", "auto")
        try:
            self._path(item["id"]).unlink()
        except OSError:
            pass
        self._mem.pop(item["id"], None)
        if mode != "auto":
            self.set_mode(item, mode)

    # ---- what the scheduler uses
    def spots(self, item):
        """[(start, end)] for a compilation, ["whole"] if the user wants it whole, or None while not scanned yet
        (the item is queued for scanning)."""
        r = self.result(item)
        if r and r.get("mode") == "whole":
            return "whole"
        if r and r.get("spots"):
            return r["spots"]
        if r and r.get("error") and time.time() - r.get("scanned", 0) < 6 * 3600:
            return None              # failed recently: don't hammer it
        self.enqueue(item)
        return None

    def status(self, item):
        r = self.result(item)
        with self.lock:
            cur = self.current if self.current and self.current["id"] == item["id"] else None
            queued = item["id"] in self.queued
        out = {"id": item["id"], "title": item.get("title"), "duration": item.get("duration"),
               "mode": (r or {}).get("mode", "auto")}
        if cur:
            out["state"], out["progress"] = "scanning", cur.get("progress", 0)
        elif r and r.get("spots"):
            out["state"], out["spots"], out["method"] = "done", r["spots"], r.get("method")
        elif r and r.get("error"):
            out["state"], out["error"] = "failed", r["error"]
        elif queued:
            out["state"] = "queued"
        else:
            out["state"] = "new"
        return out

    def enqueue(self, item, front=False):
        with self.lock:
            if item["id"] in self.queued or (self.current and self.current["id"] == item["id"]):
                return
            self.queued.add(item["id"])
            (self.queue.appendleft if front else self.queue.append)(dict(item))
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._worker, name="adsplit", daemon=True)
                self.thread.start()
        self.wake.set()

    # ---- scanning
    def _source(self, item):
        st = self.app.store.settings
        jf = self.app.sched.jellyfin()
        if st.get("media_access") == "direct":
            path = map_path(item.get("path") or "", st.get("path_mappings"))
            if path and os.path.isfile(path):
                return path, None
        return jf.stream_url(item["id"]), f"Authorization: {jf.auth_header}\r\n"

    def scan(self, item, progress=None):
        src, headers = self._source(item)
        cmd = [self.app.ffmpeg_path(), "-hide_banner", "-nostdin", "-nostats", "-threads", "2"]
        if headers:
            cmd += ["-headers", headers]
        cmd += ["-i", src, "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn",
                "-vf", "scale=192:-2,blackdetect=d=0.06:pix_th=0.08:pic_th=0.92,scdet=threshold=6",
                "-af", "silencedetect=noise=-42dB:d=0.12",
                "-f", "null", "-progress", "pipe:1", "-"]
        kw = {}
        if os.name == "nt":
            kw["creationflags"] = NO_WINDOW | BELOW_NORMAL
        else:
            kw["preexec_fn"] = lambda: os.nice(10)
        total = float(item.get("duration") or 0)
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, **kw)
        err = []
        t = threading.Thread(target=lambda: err.extend(x.decode("utf-8", "replace") for x in p.stderr), daemon=True)
        t.start()
        limit = time.time() + max(300, total * 4)
        for line in p.stdout:
            if line.startswith(b"out_time_us=") and total and progress:
                try:
                    progress(min(99, int(line.split(b"=")[1]) / 1e6 / total * 100))
                except ValueError:
                    pass
            if time.time() > limit:
                p.kill()
                raise RuntimeError("scan took too long")
        p.wait()
        t.join(5)
        text = "".join(err)
        blacks, silences, scenes, open_s, dur = parse_log(text)
        if p.returncode != 0 and not (blacks or silences or scenes):
            last = [x for x in text.splitlines() if x.strip()][-1:] or ["ffmpeg failed"]
            raise RuntimeError(last[0][-200:])
        total = dur or total
        if open_s is not None:
            silences.append((open_s, total))
        spots, method = find_spots(blacks, silences, scenes, total, item.get("chapters"))
        return {"spots": spots, "method": method, "found": {"black": len(blacks), "silence": len(silences),
                                                            "scenes": len(scenes)}, "media_duration": total}

    def _worker(self):
        while True:
            with self.lock:
                item = self.queue.popleft() if self.queue else None
                if item:
                    self.queued.discard(item["id"])
                    self.current = {"id": item["id"], "title": item.get("title"), "progress": 0}
            if item is None:
                if self.done_since_refresh:
                    self._refresh_channels()
                self.wake.clear()
                if not self.wake.wait(600):
                    with self.lock:
                        if not self.queue:
                            self.thread = None
                            return
                continue
            old = self.result(item) or {}
            r = {"version": SCAN_VERSION, "duration": item.get("duration"), "title": item.get("title"),
                 "mode": old.get("mode", "auto"), "scanned": time.time()}
            t0 = time.time()
            try:
                def prog(pc):
                    self.current["progress"] = round(pc)
                r.update(self.scan(item, prog))
                log.info("commercials: %s -> %d spots (%s, %.0fs to scan)", item.get("title"), len(r["spots"]),
                         r["method"], time.time() - t0)
            except Exception as e:
                r["error"] = str(e)
                log.warning("commercials: couldn't scan %s: %s", item.get("title"), e)
            self._save(item["id"], r)
            with self.lock:
                self.current = None
            self.done_since_refresh += 1
            if self.done_since_refresh >= 5:     # make spots available while a big folder is still scanning
                self._refresh_channels()

    def _refresh_channels(self):
        self.done_since_refresh = 0
        sched = self.app.sched
        for ch in self.app.store.channels():
            br = ch.get("breaks") or {}
            if not (br.get("enabled") and br.get("sources") and br.get("split", True)):
                continue
            try:
                before = len(getattr(sched.pools.get(ch["id"]), "commercials", []) or [])
                pool = sched.pool(ch, force=True)
                if not before and pool.commercials:     # first spots for this channel: schedule breaks from now on
                    sched.reset(ch, keep_current=True)
            except Exception as e:
                log.info("commercials: refreshing %s failed: %s", ch.get("name"), e)


def expand(item, spots):
    """One compilation -> one pseudo-item per spot (same file, played from `offset`)."""
    out = []
    for n, (a, b) in enumerate(spots):
        out.append(dict(item, duration=round(b - a, 3), offset=a, spot=n, spots=len(spots),
                        title=f"{item.get('title')} · spot {n + 1}"))
    return out

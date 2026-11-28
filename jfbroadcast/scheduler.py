"""Persistent, wall-clock-anchored channel schedules.

Every channel owns a timeline of entries ({"s": start_epoch, "d": seconds, "k": kind, "i": item}) that is
extended a few days ahead and saved to disk. Because the timeline is fixed in advance, the EPG is always truthful
and tuning in drops you into the middle of whatever is "on", exactly like real TV.
"""
import hashlib
import json
import logging
import math
import random
import threading
import time

from .config import SCHEDULE_KEYS, _atomic_write
from .jellyfin import Jellyfin, JellyfinError, normalize_item
from .timeslots import all_occurrences, clean_slots

log = logging.getLogger("scheduler")

MIN_GAP = 8          # gaps shorter than this are not filled (next show just starts a few seconds early)
NO_CONTENT_BLOCK = 1800
KEEP_PAST = 6 * 3600


def is_placeholder(e):
    return e.get("msg") == "nocontent"


def keep_through_current(tl, now):
    """Entries up to the end of whatever program is on now (including its remaining parts and breaks).
    "No programming" placeholders are never kept - they get replaced as soon as there is something to play."""
    out = [e for e in tl if e["s"] <= now and not is_placeholder(e)]
    if out and out[-1]["s"] + out[-1]["d"] <= now:
        return out          # nothing real is on right now
    for e in (e for e in tl if e["s"] > now):
        if (e["k"] == "program" and not e.get("p")) or is_placeholder(e):
            break
        out.append(e)
    return out


def schedule_hash(ch):
    return hashlib.sha1(json.dumps({k: ch.get(k) for k in SCHEDULE_KEYS}, sort_keys=True).encode()).hexdigest()[:16]


def pool_hash(ch):
    """Fingerprint of the settings that decide what's fetched from Jellyfin. Other changes (order, start times,
    break lengths, time slot times ...) re-plan the schedule from the items already in hand: no library query."""
    br, bu = ch.get("breaks") or {}, ch.get("bumpers") or {}
    d = {k: ch.get(k) for k in ("sources", "exclude", "item_types", "include_specials", "min_minutes", "max_minutes",
                                "filler_sources", "type")}
    d["breaks"] = {k: br.get(k) for k in ("enabled", "sources", "split", "split_over_seconds")}
    d["bumpers"] = {k: bu.get(k) for k in ("enabled", "sources")}
    d["slots"] = [[s.get("id"), s.get("sources"), bool(s.get("exclusive"))] for s in ch.get("slots") or []]
    return hashlib.sha1(json.dumps(d, sort_keys=True).encode()).hexdigest()[:16]


def local_offset(t):
    return time.localtime(t).tm_gmtoff


def align_up(t, minutes):
    if not minutes:
        return t
    p = minutes * 60
    off = local_offset(t)
    return math.ceil((t + off - 0.001) / p) * p - off


def align_down(t, minutes):
    p = (minutes or 30) * 60
    off = local_offset(t)
    return math.floor((t + off) / p) * p - off


def show_key(it):
    """Which 'show' an item belongs to: the series for episodes, the item itself for movies and videos."""
    if not it:
        return None
    if it.get("type") == "Episode":
        return "s:" + (it.get("series_id") or it.get("title") or it["id"])
    return "i:" + it["id"]


def group_key(it):
    """How shows are grouped for airtime balancing: each series on its own, all movies together, all other clips together."""
    if it.get("type") == "Episode":
        return show_key(it)
    return "movies" if it.get("type") == "Movie" else "clips"


def group_title(key, items):
    if key == "movies":
        return "Movies"
    if key == "clips":
        return "Videos & clips"
    return items[0].get("title") or "Show"


def balance_on(ch):
    b = ch.get("balance") or {}
    return int(b.get("strength") or 0) > 0 or any(abs(float(v) - 1) > 1e-6 for v in (b.get("weights") or {}).values())


def target_shares(groups, balance):
    """{group key: share of airtime 0..1}. groups = {key: total seconds}. Strength blends between the pool's own
    proportions (0) and equal time for every show (100); then each show's multiplier is applied."""
    b = balance or {}
    a = max(0.0, min(1.0, float(b.get("strength") or 0) / 100))
    weights = b.get("weights") or {}
    total = sum(groups.values()) or 1
    raw = {}
    for k, secs in groups.items():
        natural = secs / total
        raw[k] = (natural ** (1 - a) if natural > 0 else 0) * max(0.0, float(weights.get(k, 1)))
    s = sum(raw.values())
    if s <= 0:
        return {k: 1 / len(groups) for k in groups} if groups else {}
    return {k: v / s for k, v in raw.items()}


def spread_shuffle(items, rnd=random):
    """Shuffle so each show's items are spread evenly through the deck instead of clumping together.
    Returns ids in play order (first = plays first)."""
    groups = {}
    for i in items:
        groups.setdefault(show_key(i), []).append(i)
    keyed = []
    for g in groups.values():
        rnd.shuffle(g)
        n, off = len(g), rnd.random()
        for k, it in enumerate(g):      # evenly spaced slots with a random phase, plus a little jitter
            keyed.append(((k + off) / n + rnd.uniform(-0.15, 0.15) / n, it["id"]))
    keyed.sort()
    return [i for _, i in keyed]


def sort_key(it):
    if it["type"] == "Episode":
        return (it["title"].lower(), it["season"] if it["season"] is not None else 999,
                it["episode"] if it["episode"] is not None else 9999, it["episode_title"].lower())
    return (it["premiere"] or str(it["year"] or "9999"), it["title"].lower(), 0, "")


def _ep_label(it):
    if it.get("type") == "Episode" and it.get("season") is not None and it.get("episode") is not None:
        return f"S{int(it['season']):02d}E{int(it['episode']):02d}"
    return str(it.get("year") or "")


class Pool:
    """The playable items for one channel (cached on disk, refreshed periodically)."""

    def __init__(self, items=None, fillers=None, fetched=0, error="", commercials=None, bumpers=None, compilations=None,
                 slots=None, hash=""):
        self.hash = hash
        self.items = items or []
        self.slots = slots or {}     # time slot id -> its items
        self.compilations = compilations or []
        self.fillers = fillers or []
        self.commercials = commercials or []
        self.bumpers = bumpers or []
        self.fetched = fetched
        self.error = error
        self.by_id = {i["id"]: i for i in self.items}
        for its in self.slots.values():
            for i in its:
                self.by_id.setdefault(i["id"], i)

    @property
    def total_seconds(self):
        return sum(i["duration"] for i in self.items)


class ScheduleManager:
    def __init__(self, store):
        self.store = store
        self.locks = {}
        self.pools = {}
        self.states = {}
        self._glock = threading.Lock()
        self.splitter = None         # AdSplitter (set by the app)
        self.jobs = {}               # channel id -> background rebuild after a settings change
        self.refreshing = {}         # channel id -> time a background library refresh started
        self._rlocks = {}
        self._fetch_slots = threading.BoundedSemaphore(2)    # at most 2 channels query Jellyfin at once

    # ---------- helpers ----------
    def jellyfin(self):
        s = self.store.settings
        return Jellyfin(s["jellyfin_url"], s["jellyfin_api_key"], s.get("jellyfin_user_id", ""))

    def lock(self, cid):
        with self._glock:
            return self.locks.setdefault(cid, threading.RLock())

    def _state_path(self, cid):
        return self.store.data_dir / "state" / f"{cid}.json"

    def _pool_path(self, cid):
        return self.store.data_dir / "cache" / f"pool-{cid}.json"

    # ---------- pools ----------
    def _resolve(self, jf, sources, ch, allow_types=None):
        types = allow_types or ch.get("item_types") or ["Movie", "Episode"]
        seen, out = set(), []
        for src in sources:
            for raw in jf.resolve_source(src, types):
                if raw["Id"] in seen:
                    continue
                seen.add(raw["Id"])
                it = normalize_item(raw)
                if it["type"] not in types or it["duration"] < 5 or it["location"] == "Virtual":
                    continue
                out.append(it)
        return out

    def _compilations_changed(self, pool):
        if not (self.splitter and pool.compilations):
            return False
        have = {c["id"] for c in pool.commercials}
        changed = False
        for comp in pool.compilations:
            spots = self.splitter.spots(comp)       # also queues anything not scanned yet
            if spots and comp["id"] not in have and (spots != "whole" or comp["duration"] <= 600):
                changed = True
        return changed

    def _commercials(self, jf, ch, br, types):
        """(commercials, compilations): long commercial videos are split into their separate ads (see adsplit)."""
        from .adsplit import expand
        if not (br.get("enabled") and br.get("sources")):
            return [], []
        split = br.get("split", True) and self.splitter is not None
        over = max(20.0, float(br.get("split_over_seconds") or 90))
        commercials, compilations = [], []
        for c in self._resolve(jf, br.get("sources") or [], ch, types):
            if split and over < c["duration"] <= 4 * 3600:
                compilations.append({k: c.get(k) for k in ("id", "title", "duration", "path", "chapters", "type")})
                spots = self.splitter.spots(c)
                if spots == "whole":
                    if c["duration"] <= 10 * 60:
                        commercials.append(c)
                elif spots:
                    commercials += expand(c, spots)
            elif c["duration"] <= 10 * 60:
                commercials.append(c)
        return commercials, compilations

    def refresh_pool(self, ch):
        cid = ch["id"]
        jf = self.jellyfin()
        try:
            items = self._resolve(jf, ch.get("sources", []), ch)
            if ch.get("exclude"):
                ex = {i["id"] for i in self._resolve(jf, ch["exclude"], ch)}
                items = [i for i in items if i["id"] not in ex]
            if not ch.get("include_specials"):
                items = [i for i in items if not (i["type"] == "Episode" and i["season"] == 0)]
            mn, mx = (ch.get("min_minutes") or 0) * 60, (ch.get("max_minutes") or 0) * 60
            items = [i for i in items if i["duration"] >= mn and (not mx or i["duration"] <= mx)]
            slots = {}
            for sl in clean_slots(ch.get("slots")):
                if sl["sources"]:
                    its = self._resolve(jf, sl["sources"], ch, ["Movie", "Episode", "MusicVideo", "Video"])
                    if not ch.get("include_specials"):
                        its = [i for i in its if not (i["type"] == "Episode" and i["season"] == 0)]
                    slots[sl["id"]] = its
            excl = {i["id"] for sl in clean_slots(ch.get("slots")) if sl["exclusive"] for i in slots.get(sl["id"], [])}
            if excl and any(i["id"] not in excl for i in items):     # only in their time slots
                items = [i for i in items if i["id"] not in excl]
            fillers = self._resolve(jf, ch.get("filler_sources", []), ch,
                                    ["Movie", "Episode", "MusicVideo", "Video", "Trailer"]) if ch.get("filler_sources") else []
            fillers = [f for f in fillers if f["duration"] <= 15 * 60]
            short_types = ["Movie", "Episode", "MusicVideo", "Video", "Trailer"]
            br, bu = ch.get("breaks") or {}, ch.get("bumpers") or {}
            commercials, compilations = self._commercials(jf, ch, br, short_types)
            vbumpers = [c for c in self._resolve(jf, bu.get("sources") or [], ch, short_types)
                        if c["duration"] <= 5 * 60] if bu.get("enabled") and bu.get("sources") else []
            pool = Pool(items, fillers, time.time(), commercials=commercials, bumpers=vbumpers, compilations=compilations,
                        slots=slots, hash=pool_hash(ch))
            _atomic_write(self._pool_path(cid), json.dumps({"items": items, "fillers": fillers, "fetched": pool.fetched,
                                                            "slots": slots,
                                                            "commercials": commercials, "bumpers": vbumpers,
                                                            "compilations": compilations,
                                                            "hash": pool_hash(ch)}))
            log.info("channel %s (%s): %d items, %d fillers, %d commercials, %d video bumpers%s", ch["number"],
                     ch["name"], len(items), len(fillers), len(commercials), len(vbumpers),
                     f", {len(slots)} time slots ({sum(len(v) for v in slots.values())} items)" if slots else "")
        except (JellyfinError, OSError) as e:
            log.warning("pool refresh failed for %s: %s", ch["name"], e)
            old = self.pools.get(cid) or self._load_pool(ch, any_hash=True)
            pool = Pool(old.items if old else [], old.fillers if old else [], old.fetched if old else 0, str(e),
                        old.commercials if old else [], old.bumpers if old else [], old.compilations if old else [],
                        old.slots if old else {}, hash=pool_hash(ch))
        self.pools[cid] = pool
        return pool

    def _load_pool(self, ch, any_hash=False):
        p = self._pool_path(ch["id"])
        if not p.exists():
            return None
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if not any_hash and d.get("hash") != pool_hash(ch):
                return None
            return Pool(d["items"], d.get("fillers", []), d.get("fetched", 0), commercials=d.get("commercials", []),
                        bumpers=d.get("bumpers", []), compilations=d.get("compilations", []), slots=d.get("slots") or {},
                        hash=d.get("hash", ""))
        except Exception:
            return None

    def _rlock(self, cid):
        with self._glock:
            return self._rlocks.setdefault(cid, threading.Lock())

    def pool(self, ch, force=False):
        """The channel's items. Waits for Jellyfin only when there's nothing usable yet (new channel, or its sources
        changed); an out-of-date list keeps being used while a fresh one is fetched in the background."""
        cid, h = ch["id"], pool_hash(ch)
        p = self.pools.get(cid)
        if p is not None and p.hash != h:
            p = None
        stale = False
        if p is None and not force:
            p = self._load_pool(ch)
            if p:
                self.pools[cid] = p
                stale = self._compilations_changed(p)     # scanned since this list was saved (or still to scan)
        if force or p is None:
            with self._rlock(cid):                        # one fetch at a time per channel
                q = self.pools.get(cid)
                if not force and q is not None and q.hash == h:
                    return q                              # someone else just fetched it
                with self._fetch_slots:
                    return self.refresh_pool(ch)
        max_age = float(self.store.settings.get("library_refresh_hours") or 6) * 3600
        if not p.items and not any(p.slots.values()):
            max_age = 120   # empty channel: look again soon (sources may have just been added or scanned)
        if stale or time.time() - p.fetched > max_age:
            self._refresh_later(ch)
        return p

    def _refresh_later(self, ch):
        cid = ch["id"]
        with self._glock:
            if time.time() - self.refreshing.get(cid, 0) < 90:      # running, or tried a moment ago
                return
            self.refreshing[cid] = time.time()

        def run():
            try:
                with self._rlock(cid), self._fetch_slots:
                    fresh = self.store.channel(cid) or ch
                    before = self.pools.get(cid)
                    p = self.refresh_pool(fresh)
                if before is not None and not before.commercials and p.commercials:
                    self.reset(fresh, keep_current=True)    # first commercials: plan breaks from now on
            except Exception as e:
                log.warning("background refresh of %s failed: %s", ch.get("name"), e)
        threading.Thread(target=run, daemon=True, name=f"refresh-{cid}").start()

    # ---------- background re-planning (after a settings change) ----------
    def busy(self, cid):
        job = self.jobs.get(cid)
        return bool(job and job["thread"].is_alive())

    MODES = ("fetch", "replan", "refresh", "now")

    def rebuild_async(self, cid, on_done=None, mode="replan"):
        """Re-plan a channel in the background. fetch: just read the library and plan ahead as usual (a web page
        found nothing at hand); replan: after a settings change (re-reads the library only if
        its sources changed); refresh: re-read the library, then re-plan after what's on; now: also replace what's
        on. Calls arriving while one runs are folded into one more pass (the strongest mode wins)."""
        with self._glock:
            job = self.jobs.get(cid)
            if job and job["thread"].is_alive():
                job["again"] = True
                job["cbs"].append(on_done)
                job["mode"] = max(job["mode"], mode, key=self.MODES.index)
                return
            job = self.jobs[cid] = {"again": False, "cbs": [on_done], "started": time.time(), "mode": mode}
            job["thread"] = threading.Thread(target=self._rebuild_job, args=(cid,), daemon=True, name=f"rebuild-{cid}")
            job["thread"].start()

    def _rebuild_job(self, cid):
        while True:
            ch = self.store.channel(cid)
            with self._glock:
                mode, self.jobs[cid]["mode"] = self.jobs[cid]["mode"], "fetch"
            if ch:
                try:
                    t0 = time.time()
                    if ch.get("type") not in ("guide", "weather"):
                        if mode == "now":
                            self.rebuild_now(ch)
                        elif mode == "fetch":
                            self.pool(ch)
                            self.ensure(ch)
                        else:
                            self.pool(ch, force=mode == "refresh")    # library query (if needed), outside the lock
                            self.reset(ch, keep_current=True)
                    log.info("channel %s re-planned in %.1f s", ch.get("name"), time.time() - t0)
                except Exception as e:
                    log.warning("re-planning %s failed: %s", ch.get("name"), e)
            with self._glock:
                job = self.jobs[cid]
                if job["again"]:
                    job["again"] = False
                    continue
                cbs = job["cbs"]
                del self.jobs[cid]
            for cb in cbs:
                try:
                    if cb:
                        cb()
                except Exception as e:
                    log.warning("after re-planning %s: %s", cid, e)
            return

    # ---------- state ----------
    def _load_state(self, cid):
        st = self.states.get(cid)
        if st is None:
            p = self._state_path(cid)
            try:
                st = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
            except Exception:
                st = {}
            st.setdefault("timeline", [])
            st.setdefault("deck", [])
            st.setdefault("cursor", {})
            st.setdefault("seq", 0)
            st.setdefault("recent", [])
            self.states[cid] = st
        return st

    def _save_state(self, cid):
        _atomic_write(self._state_path(cid), json.dumps(self.states[cid]))

    def reset(self, ch, keep_current=True):
        """Throw away the future of a channel's timeline (after config changes)."""
        cid = ch["id"]
        with self.lock(cid):
            st = self._load_state(cid)
            now = time.time()
            if keep_current:
                st["timeline"] = keep_through_current(st["timeline"], now)
            else:
                st["timeline"] = []
            st["deck"], st["recent"] = [], []
            st.pop("queued", None)
            st.pop("deferred", None)
            st.pop("passes", None)
            st.pop("gdeck", None)
            st.pop("deferred", None)
            st["hash"] = schedule_hash(ch)
            self._save_state(cid)
        return self.ensure(ch)

    @staticmethod
    def _cut_at(tl, now):
        """Index of the entry on the air at `now` (cut to end right now), or None."""
        for i, e in enumerate(tl):
            if e["s"] <= now < e["s"] + e["d"]:
                e["d"] = round(max(0.1, now - e["s"]), 3)
                return i
        return None

    def skip(self, ch, now=None):
        """Skip what's on the air. A show is dropped (with the rest of its parts and breaks) and a new one starts
        right away; an ad, bumper or filler is cut short and everything after it moves up."""
        cid = ch["id"]
        now = now or time.time()
        with self.lock(cid):
            st = self._load_state(cid)
            tl = st["timeline"]
            cur = next((e for e in tl if e["s"] <= now < e["s"] + e["d"]), None)
            if cur is None:
                return None
            label = (cur.get("i") or {}).get("title") or cur["k"]
            rem = cur["s"] + cur["d"] - now
            i = self._cut_at(tl, now)
            if cur["k"] in ("commercial", "bumper", "filler"):
                for e in tl[i + 1:]:
                    e["s"] = round(e["s"] - rem, 3)
            else:
                del tl[i + 1:]
                st.pop("queued", None)
                st.pop("deferred", None)
            self._save_state(cid)
        log.info("channel %s: skipped %s", ch.get("name"), label)
        self.ensure(ch, now)
        return label

    def rebuild_now(self, ch, now=None):
        """Re-read the library and plan everything again starting this second (the current show included)."""
        cid = ch["id"]
        self.pool(ch, force=True)
        now = now or time.time()           # after the library query, which can take a while
        with self.lock(cid):
            st = self._load_state(cid)
            tl = st["timeline"]
            i = self._cut_at(tl, now)
            st["timeline"] = tl[:i + 1] if i is not None else [e for e in tl if e["s"] + e["d"] <= now]
            st["deck"], st["recent"] = [], []
            st.pop("queued", None)
            st.pop("deferred", None)
            st["hash"] = schedule_hash(ch)
            self._save_state(cid)
        return self.ensure(ch, now)

    def delete(self, cid):
        with self.lock(cid):
            self.states.pop(cid, None)
            self.pools.pop(cid, None)
            for p in (self._state_path(cid), self._pool_path(cid)):
                try:
                    p.unlink()
                except OSError:
                    pass

    # ---------- picking ----------
    def _pick_balanced(self, ch, st, pool):
        """Airtime balancing: choose the show first (stride scheduling: each show is due again after airing for
        its share of the time), then the next item of that show in the channel's order."""
        groups = {}
        for i in pool.items:
            groups.setdefault(group_key(i), []).append(i)
        shares = target_shares({k: sum(i["duration"] for i in v) for k, v in groups.items()}, ch.get("balance"))
        live = [k for k in groups if shares.get(k, 0) > 0] or list(groups)
        passes = st.setdefault("passes", {})
        floor = min((passes[k] for k in live if k in passes), default=0.0)
        for k in live:
            passes.setdefault(k, floor + random.random() * 60)        # newcomers join at the front, a little shuffled
        for k in list(passes):
            if k not in groups:
                del passes[k]
        last = st.get("last_show")
        no_repeat = ch.get("no_repeat_show", True)
        cand = [k for k in live if not (no_repeat and last and k == last)] or live
        key = min(cand, key=lambda k: passes[k])
        members = groups[key]
        order = ch.get("order", "shuffle")
        recent = st["recent"]
        if order == "sequential" or (order == "series_rotation" and key.startswith("s:")):
            eps = sorted(members, key=sort_key)
            pos = st["cursor"].get(key, 0) % len(eps)
            it = eps[pos]
            st["cursor"][key] = pos + 1
        elif order == "random":
            ids = {i["id"] for i in members}
            mine = [r for r in recent if r in ids][-min(len(members) - 1, 20):] if len(members) > 1 else []
            fresh = [i for i in members if i["id"] not in mine] or members
            it = random.choice(fresh)
        else:   # shuffle (and movies in the other orders): every item of the show once before any repeats
            decks = st.setdefault("gdeck", {})
            deck = [d for d in decks.get(key, []) if d in pool.by_id]
            if not deck:
                deck = [i["id"] for i in members]
                random.shuffle(deck)
            it = pool.by_id[deck.pop()]
            decks[key] = deck
        passes[key] += max(60.0, it["duration"]) / max(shares.get(key, 0), 1e-4)
        recent.append(it["id"])
        del recent[:-50]
        st["last_show"] = show_key(it) if key.startswith("s:") else key
        return it

    def breakdown(self, ch):
        """What the channel's pool is made of, per show: items, hours, share of the pool, the share of airtime the
        balancing aims for, and what the schedule actually holds for the next few days."""
        pool = self._pool_ready(ch)
        if pool is None:                       # still being read from Jellyfin
            self.rebuild_async(ch["id"], mode="fetch")
            return {"groups": [], "balanced": balance_on(ch), "strength": 0, "scheduled_hours": 0, "loading": True}
        groups = {}
        for i in pool.items:
            groups.setdefault(group_key(i), []).append(i)
        secs = {k: sum(i["duration"] for i in v) for k, v in groups.items()}
        total_s, total_n = sum(secs.values()) or 1, sum(len(v) for v in groups.values()) or 1
        target = target_shares(secs, ch.get("balance")) if balance_on(ch) else {k: v / total_s for k, v in secs.items()}
        aired, now = {}, time.time()
        for e in self.entries_between(ch, now, now + 8 * 86400, wait=False):
            if e["k"] == "program" and e.get("i") and e["s"] + e["d"] > now:
                k = group_key(e["i"])
                aired[k] = aired.get(k, 0) + e["d"]
        aired_total = sum(aired.values()) or 1
        out = [{"key": k, "title": group_title(k, v), "items": len(v), "seconds": round(secs[k]),
                "share_items": len(v) / total_n, "share_time": secs[k] / total_s, "target": target.get(k, 0),
                "scheduled": aired.get(k, 0) / aired_total,
                "weight": float(((ch.get("balance") or {}).get("weights") or {}).get(k, 1))}
               for k, v in groups.items()]
        out.sort(key=lambda g: -g["seconds"])
        return {"groups": out, "balanced": balance_on(ch), "strength": int((ch.get("balance") or {}).get("strength") or 0),
                "scheduled_hours": round(aired_total / 3600, 1) if aired else 0}

    def _pick(self, ch, st, pool):
        items = pool.items
        if not items:
            return None
        if balance_on(ch):
            return self._pick_balanced(ch, st, pool)
        order = ch.get("order", "shuffle")
        recent = st["recent"]
        last = st.get("last_show")
        no_repeat = ch.get("no_repeat_show", True)
        other = (lambda i: show_key(i) != last) if no_repeat and last else (lambda i: True)
        if order == "random":
            choices = [i for i in items if i["id"] not in recent[-min(len(items) - 1, 20):]] or items
            it = random.choice([i for i in choices if other(i)] or [i for i in items if other(i)] or choices)
        elif order == "sequential":
            seq = sorted(items, key=sort_key) if not any(s.get("type") == "playlist" for s in ch["sources"]) else items
            shows = list(dict.fromkeys(show_key(i) for i in seq))
            if no_repeat and len(shows) > 1 and sum(1 for k in shows if k.startswith("s:")):
                # in order *per show*, taking turns between shows: A1 B1 C1 A2 B2 C2 ...
                runs = {}
                for i in seq:
                    runs.setdefault(show_key(i), []).append(i)
                turn = st.get("turn", 0)
                order_keys = [k for k in shows]
                for step in range(len(order_keys)):
                    key = order_keys[(turn + step) % len(order_keys)]
                    if key != last or len(order_keys) == 1:
                        break
                st["turn"] = (order_keys.index(key) + 1) % len(order_keys)
                eps = runs[key]
                pos = st["cursor"].get(key, 0) % len(eps)
                it = eps[pos]
                st["cursor"][key] = pos + 1
            else:
                idx = st["seq"] % len(seq)
                it = seq[idx]
                st["seq"] = idx + 1
        elif order == "series_rotation":
            groups = {}
            for i in items:
                groups.setdefault(i["series_id"] or ("movie:" + i["id"] if i["type"] != "Episode" else i["title"]), []).append(i)
            movie_keys = [k for k in groups if k.startswith("movie:")]
            show_keys = [k for k in groups if not k.startswith("movie:")]
            keys = show_keys + (["__movies__"] if movie_keys else [])
            last_group = st.get("last_group")
            cand = [k for k in keys if k != last_group] or keys
            key = random.choice(cand)
            st["last_group"] = key
            if key == "__movies__":
                mv = [groups[k][0] for k in movie_keys]
                fresh = [m for m in mv if m["id"] not in recent] or mv
                it = random.choice([m for m in fresh if other(m)] or fresh)
            else:
                eps = sorted(groups[key], key=sort_key)
                pos = st["cursor"].get(key, 0) % len(eps)
                it = eps[pos]
                st["cursor"][key] = pos + 1
        else:  # shuffle: every item once before any repeats, shows spread out, never the same show twice in a row
            deck = [d for d in st["deck"] if d in pool.by_id]
            if not deck:
                deck = list(reversed(spread_shuffle(items) if no_repeat else random.sample([i["id"] for i in items], len(items))))
            if no_repeat and last:
                # take the next card that's a different show (the deck is popped from the end)
                for j in range(len(deck) - 1, -1, -1):
                    if show_key(pool.by_id[deck[j]]) != last:
                        deck.append(deck.pop(j))
                        break
                else:   # only this show is left in the deck: borrow a different show from the whole pool
                    alt = [i for i in items if show_key(i) != last]
                    if alt:      # the least recently played one
                        when = {iid: n for n, iid in enumerate(recent)}
                        deck.append(min(alt, key=lambda i: when.get(i["id"], -1))["id"])
            it = pool.by_id[deck.pop()]
            st["deck"] = deck
        recent.append(it["id"])
        del recent[:-50]
        st["last_show"] = show_key(it)
        return it

    @staticmethod
    def _slim(it):
        return {k: it[k] for k in ("id", "type", "title", "episode_title", "season", "episode", "year", "overview",
                                   "genres", "rating", "duration", "image_id", "path", "series_id", "premiere")}

    @staticmethod
    def _lru_pick(candidates, history, key=lambda c: c["id"]):
        """Random pick among the least recently used third of the candidates (fast path for big libraries:
        anything not played recently at all is fair game, no sorting needed)."""
        last = {k: n for n, k in enumerate(history)}
        fresh = [c for c in candidates if key(c) not in last]
        if fresh and len(fresh) >= max(1, len(candidates) // 3):
            choice = random.choice(fresh)
        else:
            ordered = sorted(candidates, key=lambda c: last.get(key(c), -1))
            choice = random.choice(ordered[:max(1, len(ordered) // 3)])
        history.append(key(choice))
        del history[:-200]
        return choice

    # ---------- commercial breaks ----------
    @staticmethod
    def cut_points(item, br):
        """Where in a program the breaks go (seconds into the file)."""
        dur = item["duration"]
        if not br.get("enabled"):
            return []
        if (item["type"] == "Episode" and not br.get("episodes", True)) or \
                (item["type"] != "Episode" and not br.get("movies", True)):
            return []
        interval = max(30.0, float(br.get("interval_minutes") or 8) * 60)
        tail = max(0.0, float(br.get("min_tail_minutes") if br.get("min_tail_minutes") is not None else 3) * 60)
        limit = int(br.get("max_per_program") or 0)
        chapters = item.get("chapters") or [] if br.get("use_chapters", True) else []
        window = min(180.0, interval * 0.35)
        cuts, t = [], interval
        while t < dur - tail and (not limit or len(cuts) < limit):
            cut = t
            prev = cuts[-1] if cuts else 0.0
            near = [c for c in chapters if abs(c - t) <= window and c > prev + 30 and c < dur - tail]
            if near:
                cut = min(near, key=lambda c: abs(c - t))
            cuts.append(round(cut, 3))
            t = cut + interval
        return cuts

    def _bumper_candidates(self, ch, pool, placement, t=None):
        from .graphics import bumper_needs_weather, bumper_time_ok
        bu = ch.get("bumpers") or {}
        if not bu.get("enabled"):
            return []
        ids = set(bu.get("ids") or [])
        # planning days ahead calls this thousands of times: read the bumper library once every few seconds
        cache = getattr(self, "_bump_cache", None)
        if cache is None or time.time() - cache[0] > 5:
            cache = self._bump_cache = (time.time(), self.store.bumpers(),
                                        any(c.get("type") == "weather" for c in self.store.channels()))
        _, library, has_weather = cache
        out = [("text", b) for b in library
               if (not ids or b["id"] in ids) and (b["kind"] == placement or b["kind"] == "any")
               and bumper_time_ok(b, t) and (has_weather or not bumper_needs_weather(b))]
        out += [("video", v) for v in pool.bumpers]
        return out

    def _add_bumper(self, ch, st, pool, placement, t, entries, ctx):
        cands = self._bumper_candidates(ch, pool, placement, t)
        if not cands:
            return t
        # prefer bumpers written for this exact spot; "any" ones and video bumpers sprinkle in
        exact = [c for c in cands if c[0] == "text" and c[1]["kind"] == placement]
        if exact and random.random() < 0.6:
            cands = exact
        kind, b = self._lru_pick(cands, st.setdefault("recent_bump", []),
                                 key=lambda c: c[1]["id"])
        if kind == "text":
            d = self.store.bumper_duration(b)
            entries.append({"s": t, "d": d, "k": "bumper", "b": b["id"], "place": placement, "ctx": ctx, "i": None})
        else:
            d = b["duration"]
            entries.append({"s": t, "d": d, "k": "bumper", "i": self._slim(b), "place": placement, "ctx": ctx})
        return t + d

    def _add_break(self, ch, st, pool, t, entries, show):
        br, bu = ch.get("breaks") or {}, ch.get("bumpers") or {}
        ctx = {"show": show["title"], "episode": show.get("episode_title", "")}
        every = max(1, int(bu.get("every_breaks") or 1))
        st["breaks_seen"] = st.get("breaks_seen", 0) + 1
        bump = (st["breaks_seen"] - 1) % every == 0
        if bump and bu.get("into_break", True):
            t = self._add_bumper(ch, st, pool, "into_break", t, entries, ctx)
        target = max(5.0, float(br.get("length_seconds") or 120))
        used, hist = 0.0, st.setdefault("recent_ads", [])
        while pool.commercials:
            fits = [c for c in pool.commercials if c["duration"] <= target - used]
            if not fits:
                if used == 0:   # always play at least one spot
                    fits = [min(pool.commercials, key=lambda c: c["duration"])]
                else:
                    break
            c = self._lru_pick(fits, hist, key=lambda c: f"{c['id']}@{c.get('spot', 0)}")
            e = {"s": t, "d": c["duration"], "k": "commercial", "i": self._slim(c)}
            if c.get("offset"):
                e["o"] = c["offset"]     # one ad inside a compilation: play the file from there
            entries.append(e)
            t += c["duration"]
            used += c["duration"]
            if len(entries) > 4000:
                break
        if bump and bu.get("out_of_break", True):
            t = self._add_bumper(ch, st, pool, "out_of_break", t, entries, ctx)
        return t

    def _fill_gap(self, st, pool, t, gap, entries):
        """Fill [t, t+gap) with filler items, then an 'up next' slate for whatever is left."""
        fillers = pool.fillers
        rec = st.setdefault("recent_fill", [])
        count = 0
        while gap >= MIN_GAP and count < 60:   # cap keeps a long gap from becoming hundreds of tiny clips
            count += 1
            fits = [f for f in fillers if f["duration"] <= gap]
            if not fits:
                break
            last = {fid: n for n, fid in enumerate(rec)}
            fits.sort(key=lambda f: last.get(f["id"], -1))      # least recently used first
            f = random.choice(fits[:max(1, len(fits) // 3)])
            rec.append(f["id"])
            del rec[:-200]
            entries.append({"s": t, "d": f["duration"], "k": "filler", "i": self._slim(f)})
            t += f["duration"]
            gap -= f["duration"]
        if gap >= MIN_GAP:
            entries.append({"s": t, "d": gap, "k": "slate", "i": None})
            t += gap
        return t

    # ---------- building blocks ----------
    def _program(self, ch, st, pool, it, t, out, br, slot_id=None, breaks=True):
        """One program (in parts, with commercial breaks between them) from time t. Returns the end time."""
        slim = self._slim(it)
        cuts = self.cut_points(it, br) if pool.commercials and breaks else []
        pos = 0.0
        for n, cut in enumerate(cuts + [it["duration"]]):
            part = {"s": t, "d": round(cut - pos, 3), "k": "program", "i": slim}
            if cuts:
                part.update(p=n, o=pos, last=(n == len(cuts)))
            if slot_id:
                part["slot"] = slot_id
            out.append(part)
            t += cut - pos
            pos = cut
            if n < len(cuts):
                t = self._add_break(ch, st, pool, t, out, it)
        return t

    @staticmethod
    def _truncate(entries, limit):
        """Cut a run of entries off at `limit` (the program just ends there)."""
        while entries and entries[-1]["s"] >= limit - 0.5:
            entries.pop()
        if entries:
            e = entries[-1]
            e["d"] = round(max(0.5, limit - e["s"]), 3)
            if e["k"] == "program" and "p" in e:
                e["last"] = True
            e["cut"] = True
        return limit

    def _next_regular(self, ch, st, pool):
        """The next regular program: one that had to wait for a time slot comes first."""
        d = st.get("deferred") or []
        last = st.get("last_show") if ch.get("no_repeat_show", True) else None
        regular = {i["id"] for i in pool.items} if d else ()
        for iid in list(d):
            it = pool.by_id.get(iid)
            if not it or iid not in regular:          # gone from the channel's rotation
                d.remove(iid)
                continue
            if last and show_key(it) == last and len(regular) > 1:
                continue                              # same show as the one just on: it waits a little longer
            d.remove(iid)
            st["last_show"] = show_key(it)
            return it
        return self._pick(ch, st, pool)

    @staticmethod
    def _defer(st, it):
        d = st.setdefault("deferred", [])
        if it["id"] in d:
            d.remove(it["id"])
        d.insert(0, it["id"])
        del d[4:]

    def _fit_before(self, ch, st, pool, t, limit, out, br):
        """Fill the time before a slot starts: a shorter program that fits, else filler and an Up Next card."""
        gap = limit - t
        brk = (float(br.get("length_seconds") or 120) + 20) if pool.commercials else 0
        est = lambda i: i["duration"] + len(self.cut_points(i, br)) * brk if brk else i["duration"]
        cands = [i for i in pool.items if est(i) <= gap]
        last = st.get("last_show")
        if ch.get("no_repeat_show", True) and last:
            cands = [i for i in cands if show_key(i) != last] or cands
        when = {iid: n for n, iid in enumerate(st["recent"])}
        cands.sort(key=lambda i: when.get(i["id"], -1))      # least recently played first
        head = cands[:max(3, len(cands) // 3)]
        random.shuffle(head)
        for it in head[:6]:
            tmp = []
            t2 = self._program(ch, st, pool, it, t, tmp, br)
            if t2 <= limit + 1:
                out += tmp
                st["recent"].append(it["id"])
                del st["recent"][:-50]
                st["last_show"] = show_key(it)
                return t2
        return self._fill_gap(st, pool, t, gap, out)

    # ---------- time slots ----------
    @staticmethod
    def slot_label(sl, pool):
        if sl.get("name"):
            return sl["name"]
        its = pool.slots.get(sl["id"]) or []
        titles = list(dict.fromkeys(i["title"] for i in its))
        if len(titles) == 1:
            return titles[0]
        return ", ".join(s.get("name", "") for s in sl.get("sources") or [] if s.get("name")) or "Special programming"

    @staticmethod
    def _slot_sorted(sl, items):
        return list(items) if any(s.get("type") == "playlist" for s in sl.get("sources") or []) else sorted(items, key=sort_key)

    def _note_slot_airings(self, st, now):
        """Remember the last episode each slot actually aired (the timeline only keeps a few hours of history)."""
        aired, starts = st.setdefault("slot_aired", {}), st.setdefault("slot_start", {})
        for e in st["timeline"]:
            sid = e.get("slot")
            if sid and e["k"] == "program" and e.get("i") and not e.get("p") and e["s"] <= now:
                aired[sid] = e["i"]["id"]
                if starts.get(sid) and e["s"] >= starts[sid].get("at", 0) - 1:
                    starts.pop(sid)

    def _slot_next_seq(self, st, sl, items, tl, new):
        """In-order slots: the episode after the last one planned (or aired, or the one picked by hand)."""
        eps = self._slot_sorted(sl, items)
        pos = {i["id"]: n for n, i in enumerate(eps)}
        sid = sl["id"]
        ref = next((e for e in reversed(new) if e.get("slot") == sid and e["k"] == "program" and e.get("i")), None) or \
            next((e for e in reversed(tl) if e.get("slot") == sid and e["k"] == "program" and e.get("i")), None)
        start = (st.get("slot_start") or {}).get(sid)
        if start and start.get("id") in pos and (ref is None or ref["s"] < start.get("at", 0) - 1):
            return eps[pos[start["id"]]]
        if not ref and sl.get("kind") == "marathon" and not (st.get("slot_aired") or {}).get(sid):
            return eps[pos[sl["start_id"]]] if sl.get("start_id") in pos else eps[0]
        last = ref["i"]["id"] if ref else (st.get("slot_aired") or {}).get(sid)
        if last in pos:
            return eps[(pos[last] + 1) % len(eps)]
        return eps[0]

    def _slot_pick(self, st, sl, items, tl, new, skip=()):
        sid = sl["id"]
        if sl["order"] == "sequential":
            return self._slot_next_seq(st, sl, items, tl, new)
        ids = {i["id"]: i for i in items}
        if sl["order"] == "random":
            last = (st.get("slot_aired") or {}).get(sid)
            cands = [i for i in items if i["id"] not in skip and i["id"] != last] or [i for i in items if i["id"] not in skip]
            return random.choice(cands) if cands else None
        decks = st.setdefault("slot_deck", {})
        deck = [d for d in decks.get(sid, []) if d in ids]
        if not deck:
            deck = list(reversed(spread_shuffle(items)))
        for j in range(len(deck) - 1, -1, -1):
            if deck[j] not in skip:
                it = ids[deck.pop(j)]
                decks[sid] = deck
                return it
        decks[sid] = deck
        return None

    @staticmethod
    def _slot_unpick(st, sl, it):
        if sl["order"] == "shuffle":
            st.setdefault("slot_deck", {}).setdefault(sl["id"], []).append(it["id"])

    def _play_slot(self, ch, st, pool, o, t, tl, new, shift=0.0):
        """Plan one airing of a time slot from time t. Returns the time regular programming picks up again."""
        sl = o["slot"]
        items = pool.slots.get(sl["id"]) or []
        if not items:
            return t               # nothing found for it in Jellyfin: regular programming carries on
        fill = sl["play"] == "fill"
        end = o["end"] + shift
        br = ch.get("breaks") or {}
        count, last_it, tried = 0, None, set()
        while count < 200:
            if (not fill and count >= 1) or (fill and end - t < MIN_GAP):
                break
            it = self._slot_pick(st, sl, items, tl, new, tried)
            if it is None:
                break
            tmp = []
            t2 = self._program(ch, st, pool, it, t, tmp, br, slot_id=sl["id"], breaks=sl["breaks"])
            if fill and t2 > end + 1:                 # this one would run past the end of the slot
                if sl["overrun"] == "cut":
                    t2 = self._truncate(tmp, end)
                elif sl["overrun"] == "fit":
                    if sl["order"] != "sequential" and len(tried) < 8 and len(tried) < len(items) - 1:
                        tried.add(it["id"])           # try a shorter one
                        self._slot_unpick(st, sl, it)
                        continue
                    if count > 0:
                        self._slot_unpick(st, sl, it)
                        break
                    # nothing shorter to play: the first program of a slot always airs, in full
            new += tmp
            t = t2
            count += 1
            last_it = it
        if fill and end - t >= MIN_GAP:
            t = self._fill_gap(st, pool, t, end - t, new)
        if last_it:
            st["last_show"] = show_key(last_it)
        return t

    def slot_next(self, ch, sid, item_id):
        """Pick the episode an in-order slot plays next (re-plans the future after what's on now)."""
        with self.lock(ch["id"]):
            st = self._load_state(ch["id"])
            st.setdefault("slot_start", {})[sid] = {"id": item_id, "at": time.time()}
            st["timeline"] = keep_through_current(st["timeline"], time.time())
            st.pop("queued", None)
            st.pop("deferred", None)
            self._save_state(ch["id"])
        return self.ensure(ch)

    def slots_info(self, ch):
        """For the admin page: what each slot found in Jellyfin and its next airings."""
        pool = self._pool_ready(ch) or Pool()
        tl = self.entries_between(ch, time.time() - 86400, time.time() + 9 * 86400, wait=False)
        now = time.time()
        out = []
        for sl in clean_slots(ch.get("slots")):
            items = pool.slots.get(sl["id"]) or []
            airings, cur = [], None
            for e in tl:
                if e.get("slot") != sl["id"] or e["k"] != "program" or e.get("p") or e["s"] + e["d"] < now:
                    continue
                if cur is None or e["s"] - cur["end"] > 600:
                    cur = {"start": e["s"], "end": e["s"], "programs": []}
                    airings.append(cur)
                cur["programs"].append({"start": e["s"], "title": e["i"]["title"], "id": e["i"]["id"],
                                        "subtitle": _ep_label(e["i"])})
                cur["end"] = e["s"] + e["i"]["duration"]
            info = {"id": sl["id"], "items": len(items), "hours": round(sum(i["duration"] for i in items) / 3600, 1),
                    "label": self.slot_label(sl, pool), "airings": airings[:4]}
            if sl["order"] == "sequential" and items:
                eps = self._slot_sorted(sl, items)
                info["episodes"] = [{"id": i["id"], "label": (_ep_label(i) + " · " if i["type"] == "Episode" else "") +
                                     (i.get("episode_title") or i["title"]) if i["type"] == "Episode" else i["title"]}
                                    for i in eps[:2000]]
                nxt = next((p for a in airings for p in a["programs"] if p["start"] > now - 1), None)
                info["next_id"] = nxt["id"] if nxt else None
            out.append(info)
        return out

    # ---------- the main entry point ----------
    def _pool_ready(self, ch):
        """The channel's items if they're at hand (memory or disk) without asking Jellyfin, else None."""
        p = self.pools.get(ch["id"])
        if p is not None and p.hash == pool_hash(ch):
            return p
        p = self._load_pool(ch)
        if p is not None:
            self.pools[ch["id"]] = p
        return p

    def ensure(self, ch, now=None, quick=False):
        """Make sure the channel's timeline covers now .. now + schedule_days. Returns the timeline.
        quick=True (web pages): never wait for Jellyfin; if planning needs a library query first, answer with what's
        planned so far and let a background job do the rest."""
        if ch.get("type") in ("guide", "weather"):
            return []
        cid = ch["id"]
        now = now or time.time()
        with self.lock(cid):
            st = self._load_state(cid)
            h = schedule_hash(ch)
            if st.get("hash") != h:
                st["timeline"] = keep_through_current(st["timeline"], now)
                st["deck"], st["recent"], st["cursor"], st["seq"] = [], [], {}, 0
                st.pop("queued", None)
                st.pop("deferred", None)
                st.pop("passes", None)
                st.pop("gdeck", None)
                st.pop("deferred", None)
                st["hash"] = h
            tl = st["timeline"]
            if ch.get("slots") or st.get("slot_aired"):
                self._note_slot_airings(st, now)
            tl[:] = [e for e in tl if e["s"] + e["d"] > now - KEEP_PAST]
            # the channel was empty before (no sources yet, or Jellyfin unreachable) but now has media: replace
            # the "no programming" placeholders right away instead of waiting for them to run out
            horizon = now + float(self.store.settings.get("schedule_days") or 3) * 86400
            if any(x.get("kind") == "marathon" for x in ch.get("slots") or []):   # plan far enough ahead for marathons
                runs = [o["end"] for o in all_occurrences([x for x in clean_slots(ch["slots"]) if x["kind"] == "marathon"],
                                                          now, now + 8 * 86400)]
                horizon = max([horizon] + [min(e, now + 8 * 86400) for e in runs])
            placeholders = any(is_placeholder(e) and e["s"] + e["d"] > now for e in tl)
            if not placeholders and tl and tl[-1]["s"] + tl[-1]["d"] >= horizon - 3600:
                return list(tl)                          # planned far enough ahead already
            if quick and self._pool_ready(ch) is None:   # needs a library query: not on a web page's time
                self.rebuild_async(cid, mode="fetch")
                return list(tl)
            pool = self.pool(ch)
            if placeholders and pool.items:
                tl[:] = keep_through_current(tl, now)
                log.info("channel %s now has programming; replacing placeholders", ch["name"])
            if tl and tl[-1]["s"] + tl[-1]["d"] >= horizon - 3600:
                return list(tl)
            pad = int(ch.get("padding_minutes") or 0)
            t = tl[-1]["s"] + tl[-1]["d"] if tl else None
            if t is None or t < now - 3600:
                t = align_down(now, pad or 30)
            new = []
            last_prog = next((e for e in reversed(tl) if e["k"] == "program" and e.get("i")), None)
            st["last_show"] = show_key(last_prog["i"]) if last_prog else None
            queued = st.pop("queued", None)
            queued = pool.by_id.get(queued) if queued else None
            br, bu = ch.get("breaks") or {}, ch.get("bumpers") or {}
            between = bu.get("enabled") and bu.get("between_programs", True)
            slots = clean_slots(ch.get("slots"))
            occs = all_occurrences(slots, t - 86400, horizon + 86400) if slots else []
            # airings already behind us (they're in the part of the timeline that's kept) don't get planned again
            done = {o["key"] for o in occs if o["start"] < t - MIN_GAP and (o["slot"]["play"] == "one" or o["end"] <= t + MIN_GAP)}
            shift = {}
            while t < horizon:
                o = next((o for o in occs if o["key"] not in done and o["end"] > t), None)
                if o and t >= o["start"] - MIN_GAP:            # a time slot is on
                    done.add(o["key"])
                    t = self._play_slot(ch, st, pool, o, t, tl, new, shift.get(o["key"], 0.0))
                    continue
                limit = o["start"] if o else None             # regular programming has to make way at this time
                if queued:
                    st["last_show"] = show_key(queued)
                before = st.get("last_show")
                it = queued or self._next_regular(ch, st, pool)
                queued = None
                if it is None:
                    d = NO_CONTENT_BLOCK if limit is None else max(MIN_GAP, min(NO_CONTENT_BLOCK, limit - t))
                    new.append({"s": t, "d": d, "k": "slate", "i": None, "msg": "nocontent"})
                    t += d
                    continue
                tmp = []
                t2 = self._program(ch, st, pool, it, t, tmp, br)
                if limit is not None and t2 > limit + 1:      # it would still be on when the slot starts
                    how = o["slot"]["lead_in"]
                    if how == "late":                         # let it finish: the slot starts late, same length
                        shift[o["key"]] = t2 - limit
                    elif how == "cut":
                        t2 = self._truncate(tmp, limit)
                    else:                                     # start on time: this one waits until after the slot
                        self._defer(st, it)
                        st["last_show"] = before
                        t = self._fit_before(ch, st, pool, t, limit, new, br)
                        continue
                    new += tmp
                    t = t2
                    continue
                new += tmp
                t = t2
                if between:
                    queued = self._next_regular(ch, st, pool)
                    nxt = queued["title"] if queued else ""
                    if limit is not None and (not queued or t + queued["duration"] > limit):
                        nxt = self.slot_label(o["slot"], pool)    # the time slot is what's on next
                    ctx = {"show": it["title"], "next": nxt}
                    probe = []
                    self._add_bumper(ch, st, pool, "next", t, probe, ctx)
                    bdur = probe[0]["d"] if probe else 0
                    if limit is not None and t + bdur > limit:
                        probe, bdur = [], 0
                    if pad:
                        target = align_up(t + bdur, pad) - bdur
                        if limit is not None:
                            target = min(target, limit - bdur)
                        t = self._fill_gap(st, pool, t, target - t, new)
                    if probe:
                        probe[0]["s"] = t
                        probe[0]["ctx"]["next_start"] = t + bdur
                        new.append(probe[0])
                        t += bdur
                elif pad:
                    target = align_up(t, pad)
                    if limit is not None:
                        target = min(target, limit)
                    t = self._fill_gap(st, pool, t, target - t, new)
            if queued:
                st["queued"] = queued["id"]
            tl += new
            self._save_state(cid)
            return list(tl)

    # ---------- queries ----------
    def timeline(self, ch):
        return self.ensure(ch)

    def entry_at(self, ch, t):
        tl = self.ensure(ch)
        lo, hi = 0, len(tl) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            e = tl[mid]
            if t < e["s"]:
                hi = mid - 1
            elif t >= e["s"] + e["d"]:
                lo = mid + 1
            else:
                return mid, e
        return None, None

    def entries_between(self, ch, t0, t1, wait=True):
        """wait=False (web pages): if the channel is busy being planned, answer from what's planned so far."""
        if not wait:
            lk = self.lock(ch["id"])
            if self.busy(ch["id"]) or not lk.acquire(timeout=0.25):
                st = self.states.get(ch["id"]) or {}
                return [e for e in list(st.get("timeline") or []) if e["s"] + e["d"] > t0 and e["s"] < t1]
            try:
                return [e for e in self.ensure(ch, quick=True) if e["s"] + e["d"] > t0 and e["s"] < t1]
            finally:
                lk.release()
        return [e for e in self.ensure(ch) if e["s"] + e["d"] > t0 and e["s"] < t1]

    def next_program(self, ch, after_t):
        for e in self.ensure(ch):
            if e["s"] >= after_t - 0.5 and e["k"] == "program" and not e.get("p"):
                return e
        return None

"""Time slots: a show, movie or collection that airs at set times on a channel ("The Simpsons, Mon-Fri 8-9 PM").

A slot is part of the channel's config:
    {"id", "enabled", "name", "sources": [...],
     "repeat": "weekly" | "once", "days": [0..6] (Monday = 0), "date": "YYYY-MM-DD" (repeat == once),
     "start": "20:00", "end": "21:00" (may be past midnight), "from_date"/"until_date": optional "YYYY-MM-DD",
     "play": "fill" (keep playing until the end time) | "one" (one episode/movie, then regular programming),
     "order": "sequential" | "shuffle" | "random",
     "lead_in": "fit" (start on time) | "cut" (cut off what's on) | "late" (let it finish; the slot starts late),
     "overrun": "fit" (end on time) | "finish" (let the last one finish) | "cut" (cut off at the end time),
     "breaks": True (the channel's commercial breaks), "exclusive": False (keep it out of regular programming)}
"""
import time
from datetime import date, datetime, timedelta

DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
CHOICES = {"repeat": ("weekly", "once"), "play": ("fill", "one"), "order": ("sequential", "shuffle", "random"),
           "lead_in": ("fit", "cut", "late"), "overrun": ("fit", "finish", "cut")}


def _hm(s, default):
    try:
        h, m = str(s).split(":")[:2]
        h, m = int(h), int(m)
        if 0 <= h <= 24 and 0 <= m < 60 and h * 60 + m <= 1440:
            return f"{h:02d}:{m:02d}"
    except (TypeError, ValueError):
        pass
    return default


def _date(s):
    try:
        return date.fromisoformat(str(s)[:10]).isoformat() if s else ""
    except ValueError:
        return ""


def clean_slot(s, n=0):
    s = s if isinstance(s, dict) else {}
    out = {"id": str(s.get("id") or f"ts{int(time.time() * 1000) % 10 ** 10}{n}")[:40],
           "enabled": s.get("enabled", True) is not False,
           "name": str(s.get("name") or "")[:80],
           "sources": [x for x in (s.get("sources") or []) if isinstance(x, dict) and x.get("type") and x.get("id")],
           "days": sorted({int(d) for d in (s.get("days") if isinstance(s.get("days"), list) else [0, 1, 2, 3, 4])
                           if str(d).lstrip("-").isdigit() and 0 <= int(d) <= 6}),
           "date": _date(s.get("date")), "from_date": _date(s.get("from_date")), "until_date": _date(s.get("until_date")),
           "start": _hm(s.get("start"), "20:00"), "end": _hm(s.get("end"), "21:00"),
           "breaks": s.get("breaks", True) is not False, "exclusive": bool(s.get("exclusive"))}
    for k, opts in CHOICES.items():
        out[k] = s.get(k) if s.get(k) in opts else opts[0]
    return out


def clean_slots(slots):
    seen, out = set(), []
    for n, s in enumerate(slots if isinstance(slots, list) else []):
        c = clean_slot(s, n)
        while c["id"] in seen:
            c["id"] += "x"
        seen.add(c["id"])
        out.append(c)
    return out[:50]


def _local(d, hm):
    h, m = map(int, hm.split(":"))
    extra, h = divmod(h, 24)                 # "24:00" = midnight at the end of the day
    d2 = d + timedelta(days=extra)
    return time.mktime((d2.year, d2.month, d2.day, h, m, 0, 0, 0, -1))


def occurrences(slot, t0, t1):
    """[(start, end)] of one slot between t0 and t1 (epoch seconds, local time rules incl. daylight saving)."""
    out = []
    if not slot.get("enabled", True):
        return out
    d = datetime.fromtimestamp(t0).date() - timedelta(days=1)
    last = datetime.fromtimestamp(t1).date()
    lo = date.fromisoformat(slot["from_date"]) if slot.get("from_date") else None
    hi = date.fromisoformat(slot["until_date"]) if slot.get("until_date") else None
    once = date.fromisoformat(slot["date"]) if slot.get("repeat") == "once" and slot.get("date") else None
    if slot.get("repeat") == "once" and not once:
        return out
    while d <= last:
        ok = (d == once) if once else (d.weekday() in slot["days"] and (not lo or d >= lo) and (not hi or d <= hi))
        if ok:
            s = _local(d, slot["start"])
            if slot.get("play") == "one":
                e = s + 1
            else:
                e = _local(d, slot["end"])
                if e <= s:
                    e = _local(d + timedelta(days=1), slot["end"])
            if e > t0 and s < t1:
                out.append((s, e))
        d += timedelta(days=1)
    return out


def all_occurrences(slots, t0, t1):
    """Every enabled slot's airings in time order, as {"slot", "start", "end", "key"}. When two overlap, the one that
    starts first wins and the other is skipped (on a tie, the slot higher in the list wins)."""
    occ = []
    for n, sl in enumerate(slots):
        if sl.get("enabled", True) and sl.get("sources"):
            occ += [{"slot": sl, "start": s, "end": e, "key": f"{sl['id']}@{int(s)}", "n": n} for s, e in occurrences(sl, t0, t1)]
    occ.sort(key=lambda o: (o["start"], o["n"]))
    out = []
    for o in occ:
        if out and o["start"] < out[-1]["end"] and out[-1]["slot"].get("play") != "one":
            continue
        out.append(o)
    return out

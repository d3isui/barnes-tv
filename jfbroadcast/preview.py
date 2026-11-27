"""Still previews of the guide channel and slates for the theme picker (no Jellyfin needed)."""
import io
import time

from PIL import Image

from .graphics import GuideRenderer, default_logo, render_slate

SAMPLE = [
    ("c-s1", 2, "Cartoon Corner", [("Space Pups", "S2E4 · The Moon Is Cheese", 22, ["Animation", "Kids"]),
                                   ("Robo Racers", "S1E9 · Pit Stop", 22, ["Animation"]),
                                   ("Space Pups", "S2E5 · Comet Chase", 22, ["Animation", "Kids"])]),
    ("c-s2", 3, "Japan Station", [("となりのアニメ", "第12話 · 夏祭り", 24, ["Anime"]),
                                  ("Tokyo Night Drive", "S1E3", 45, ["Drama"]),
                                  ("深夜ニュース", "", 30, ["News"])]),
    ("c-s3", 4, "Movie Palace", [("The Long Weekend", "1987 · PG · Comedy", 104, ["Comedy"]),
                                 ("Midnight Express Train", "1974 · Thriller", 118, ["Thriller"])]),
    ("c-s4", 5, "Sci-Fi Zone", [("Starship Delta", "S4E1 · New Frontiers", 44, ["Science Fiction"]),
                                ("The Last Signal", "S1E7 · Static", 44, ["Mystery"])]),
    ("c-s5", 6, "Retro TV", [("Family Hour", "S3E14 · The Bake Sale", 25, ["Comedy"]),
                             ("Detective Lane", "S1E2 · Smoke", 50, ["Crime"])]),
    ("c-s6", 7, "Nature & Docs", [("Ocean Giants", "Episode 3", 52, ["Documentary"]),
                                  ("Desert Bloom", "", 48, ["Documentary"])]),
]


class _NoImages:
    def get(self, *_a, **_k):
        return None


def _rows(fonts, now):
    win0 = now - ((now + time.localtime(now).tm_gmtoff) % 1800)
    rows, spots = [], []
    for k, (cid, num, name, progs) in enumerate(SAMPLE):
        ch = {"id": cid, "number": num, "name": name}
        t = win0 - (7 + k * 9) * 60
        entries = []
        for j in range(8):
            title, sub, mins, genres = progs[j % len(progs)]
            se = sub.split(" · ")
            item = {"title": title, "type": "Movie" if mins > 90 else "Episode", "genres": genres}
            if item["type"] == "Episode":
                item["episode_title"] = se[-1] if len(se) > 1 else ""
                if se and se[0].startswith("S") and "E" in se[0]:
                    try:
                        item["season"], item["episode"] = (int(x) for x in se[0][1:].split("E"))
                    except ValueError:
                        pass
                elif se and se[0]:
                    item["episode_title"] = sub
            else:
                item["year"] = sub.split(" · ")[0] if sub else ""
            e = {"s": t, "d": mins * 60, "k": "program", "i": item}
            entries.append(e)
            if e["s"] <= now < e["s"] + e["d"]:
                spots.append((ch, e))
            t += mins * 60
            if k == 4 and j == 0:
                entries.append({"s": t, "d": 240, "k": "commercial", "i": None})
                t += 240
        logo = Image.open(io.BytesIO(default_logo(fonts, ch, 160))).convert("RGBA")
        rows.append((ch, logo, entries))
    return rows, spots


def guide_preview(T, Ft, Fd, system_fonts, W=1280, H=720, station="", clock_fmt="12h", rows=None, spots=None, header=None):
    now = time.time()
    if rows is None:
        rows, spots = _rows(system_fonts, now)
    r = GuideRenderer(Ft, _NoImages(), W, H, station, clock_fmt, T, Fd, header)
    raw, canvas_h, lay = r.frame(rows, now, None, spots or [])
    img = Image.frombytes("RGB", (W, canvas_h), raw).crop((0, 0, W, H))
    return img


def slate_preview(T, Ft, Fd, out_dir, W=1280, H=720):
    ch = {"name": "Cartoon Corner", "number": 2, "clock": {"format": "12h"}}
    nxt = {"s": time.time() + 600, "d": 1800, "k": "program",
           "i": {"title": "Space Pups", "type": "Episode", "season": 2, "episode": 5, "episode_title": "Comet Chase"}}
    return Image.open(render_slate(Ft, out_dir, W, H, "upnext", ch, nxt, None, T, Fd))


def jpeg(img, size=(960, 540), quality=86):
    img = img.convert("RGB")
    if size:
        img = img.resize(size, Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()

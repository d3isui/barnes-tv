"""Everything drawn with Pillow: channel logos, slates (up next / stand by), and the guide channel."""
import hashlib
import io
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from . import fontlib, themes, branding


log = logging.getLogger("graphics")


BRAND_DIR = Path(__file__).resolve().parent.parent / "web" / "brand"
_brand_cache = {}


BRAND_KIND = {"barnes-wordmark.png": "wordmark", "orbital-b.png": "mark", "wordmark": "wordmark", "mark": "mark"}


def brand_image(name, max_w, max_h, opacity=1.0, tint=None):
    """The station artwork (Appearance -> Branding, else the Barnes logos), scaled to fit and optionally recoloured
    to the theme; None if missing."""
    from . import branding
    kind = BRAND_KIND.get(name, name)
    if not branding.recolor():
        tint = None                  # full-colour logos keep their own colours
    key = (kind, branding.version(), int(max_w), int(max_h), round(opacity, 2), tint)
    if key not in _brand_cache:
        try:
            src = branding.path(kind) if kind in ("wordmark", "mark") else BRAND_DIR / name
            im = Image.open(src).convert("RGBA")
            k = min(max_w / im.width, max_h / im.height)
            im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
            if tint:
                solid = Image.new("RGBA", im.size, tuple(tint) + (255,))
                solid.putalpha(im.getchannel("A"))
                im = solid
            if opacity < 1:
                im.putalpha(im.getchannel("A").point(lambda a: int(a * opacity)))
            if len(_brand_cache) > 64:
                _brand_cache.clear()
            _brand_cache[key] = im
        except Exception:
            _brand_cache[key] = None
    return _brand_cache[key]


_fit_cache = {}


def fit_image(img, max_w, max_h, tint=None):
    """A user's logo trimmed of empty borders and scaled (up or down) to fit the box, optionally recoloured."""
    key = (id(img), int(max_w), int(max_h), tint)
    if key in _fit_cache:
        return _fit_cache[key]
    im = img.convert("RGBA")
    box = im.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    if box:
        im = im.crop(box)
    k = min(max_w / im.width, max_h / im.height)
    im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
    if tint and im.getchannel("A").getextrema()[0] < 200:     # an opaque picture would just become a solid block
        solid = Image.new("RGBA", im.size, tuple(tint) + (255,))
        solid.putalpha(im.getchannel("A"))
        im = solid
    if len(_fit_cache) > 32:
        _fit_cache.clear()
    _fit_cache[key] = (im, img)      # keep the source alive so id() stays unique
    return _fit_cache[key]


def corner_logo(header, brand_name, box, image_box, tint, recolor_ink):
    """The artwork for a guide / weather header: the station mark, the user's chosen logo, or None
    (header["mode"] "name" / "none" are handled by the caller)."""
    header = header or {}
    k = (header.get("size") or 100) / 100
    if header.get("mode") in ("channel", "custom") and header.get("image") is not None:
        w, h = image_box
        return fit_image(header["image"], w * k, h * k, recolor_ink if header.get("recolor") else None)[0]
    w, h = box
    return brand_image(brand_name, w * k, h * k, 1.0, tint)


def is_cjk(text):
    for ch in text or "":
        o = ord(ch)
        if 0x3000 <= o <= 0x9FFF or 0xAC00 <= o <= 0xD7AF or 0xFF00 <= o <= 0xFFEF or 0xF900 <= o <= 0xFAFF:
            return True
    return False


CLOCK_FORMATS = {"12h": "6:30 PM", "12h_plain": "6:30", "12h_sec": "6:30:05 PM", "24h": "18:30",
                 "24h_sec": "18:30:05"}


def fmt_time(t, fmt="12h"):
    d = datetime.fromtimestamp(t)
    if fmt == "24h":
        return d.strftime("%H:%M")
    if fmt == "24h_sec":
        return d.strftime("%H:%M:%S")
    if fmt == "12h_plain":
        return d.strftime("%I:%M").lstrip("0")
    if fmt == "12h_sec":
        return d.strftime("%I:%M:%S %p").lstrip("0")
    return d.strftime("%I:%M %p").lstrip("0")


_cover_cache = {}
SUBSTITUTES = {"\u00b7": ("\u2022", "-"), "\u2013": ("-",), "\u2014": ("-",), "\u2026": ("...",),
               "\u2019": ("'",), "\u2018": ("'",), "\u201c": ('"',), "\u201d": ('"',), "\u2022": ("-",)}


def has_glyph(path, ch):
    """Whether a font file has a real glyph for a character (not the .notdef box)."""
    key = (path, ch)
    if key not in _cover_cache:
        try:
            f = ImageFont.truetype(path, 24)
            nd, m = f.getmask("\U000F0001"), f.getmask(ch)
            _cover_cache[key] = not (m.size == nd.size and bytes(m) == bytes(nd))
        except Exception:
            _cover_cache[key] = True
    return _cover_cache[key]


class Fonts:
    """A font family for Pillow. Library fonts get a size correction (scale) and fall back to the system fonts
    for characters they don't have (e.g. Japanese titles in a Latin-only display font)."""

    def __init__(self, paths, scale=1.0, fallback=None, has_cjk=False, font_id="system"):
        self.paths = paths
        self.scale = scale
        self.fallback = fallback
        self.has_cjk = has_cjk
        self.id = font_id
        self._cache = {}

    def covers(self, path, text):
        return all(has_glyph(path, c) for c in set(text or "") if ord(c) > 126 and not c.isspace())

    def _pick(self, text, bold):
        p = self.paths.get("bold" if bold else "regular") or ""
        if is_cjk(text) and not self.has_cjk:
            if self.paths.get("cjk"):
                return self.paths["cjk"], 1.0
            if self.fallback:
                return self.fallback._pick(text, bold)
        if p and self.fallback and not self.covers(p, text):
            return self.fallback._pick(text, bold)
        return p, self.scale

    def path_for(self, text="", bold=False):
        return self._pick(text, bold)[0]

    def text(self, text, bold=False):
        """Swap punctuation this font lacks (middle dot, dashes, curly quotes...) for plain ASCII."""
        p = self.paths.get("bold" if bold else "regular") or ""
        if not p or not text or text.isascii():
            return text
        for ch, subs in SUBSTITUTES.items():
            if ch in text and not has_glyph(p, ch):
                rep = next((x for x in subs if all(has_glyph(p, c) for c in x if ord(c) > 126)), subs[-1])
                text = text.replace(ch, rep)
        return text

    def ellipsis(self, bold=False):
        p = self.paths.get("bold" if bold else "regular") or ""
        return "\u2026" if not p or has_glyph(p, "\u2026") else "..."

    def get(self, size, bold=False, text=""):
        p, sc = self._pick(text, bold)
        size = max(6, int(size * sc))
        key = (p, size)
        if key not in self._cache:
            try:
                self._cache[key] = ImageFont.truetype(p, size) if p else ImageFont.load_default(size)
            except Exception:
                self._cache[key] = ImageFont.load_default(size)
        return self._cache[key]


_fontsets = {}


def font_set(font_id, system):
    """Pillow fonts for a library font id. "system", "" or an unknown id give the system fonts."""
    f = fontlib.get(font_id)
    reg = fontlib.file_path(f) if f else ""
    if not reg:
        return system
    bold = fontlib.file_path(f, True) or reg
    key = (font_id, reg, bold, id(system))
    if key not in _fontsets:
        if len(_fontsets) > 64:
            _fontsets.clear()
        _fontsets[key] = Fonts({"regular": reg, "bold": bold, "cjk": "" if f.get("cjk") else system.paths.get("cjk", "")},
                               f.get("scale", 1.0), system, bool(f.get("cjk")), font_id)
    return _fontsets[key]


def text_w(draw, text, font):
    return draw.textlength(text, font=font)


def ellipsize(draw, text, font, maxw, ell="…"):
    if maxw <= 0:
        return ""
    if text_w(draw, text, font) <= maxw:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if text_w(draw, text[:mid].rstrip() + ell, font) <= maxw:
            lo = mid
        else:
            hi = mid - 1
    return (text[:lo].rstrip() + ell) if lo else ""


def wrap(draw, text, font, maxw, max_lines=2, ell="…"):
    words, lines, cur = text.split(), [], ""
    if is_cjk(text):  # no spaces in CJK - wrap per character
        words, joiner = list(text), ""
    else:
        joiner = " "
    for w in words:
        trial = (cur + joiner + w) if cur else w
        if text_w(draw, trial, font) <= maxw:
            cur = trial
        else:
            lines.append(cur)
            cur = w
            if len(lines) == max_lines:
                break
    if len(lines) < max_lines and cur:
        lines.append(cur)
    if len(lines) == max_lines and (len(" ".join(lines)) < len(text)):
        lines[-1] = ellipsize(draw, lines[-1] + ell, font, maxw, ell)
    return [l for l in lines if l]


def program_label(item):
    if not item:
        return "", ""
    if item.get("type") == "Weather":
        return item["title"], item.get("summary") or ""
    if item.get("type") == "Episode":
        se = ""
        if item.get("season") is not None and item.get("episode") is not None:
            se = f"S{item['season']}E{item['episode']}"
        sub = " · ".join(x for x in (se, item.get("episode_title")) if x)
        return item["title"], sub
    sub = " · ".join(str(x) for x in (item.get("year"), item.get("rating"), ", ".join(item.get("genres", [])[:2])) if x)
    return item["title"], sub


# ---------------------------------------------------------------- logos

PALETTE = [(230, 57, 70), (29, 120, 255), (255, 183, 3), (46, 196, 182), (155, 93, 229), (241, 91, 181),
           (0, 187, 249), (254, 127, 45)]


def default_logo(fonts, ch, size=400):
    """A simple generated bug: rounded badge with the channel number and name."""
    num, name = str(ch.get("number", "")), ch.get("name", "")
    color = PALETTE[int(hashlib.md5(ch["id"].encode()).hexdigest(), 16) % len(PALETTE)]
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((8, 8, size - 8, size - 8), radius=size // 6, fill=color + (255,),
                        outline=(255, 255, 255, 255), width=size // 40)
    f = fonts.get(size * 0.42, True)
    tw = text_w(d, num, f)
    d.text(((size - tw) / 2, size * 0.12), num, font=f, fill="white")
    nf = fonts.get(size * 0.13, True, name)
    label = ellipsize(d, name.upper(), nf, size * 0.84)
    d.text(((size - text_w(d, label, nf)) / 2, size * 0.68), label, font=nf, fill="white")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def normalize_logo(data, dest: Path):
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img).convert("RGBA")
    img.thumbnail((800, 800))
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "PNG")
    return img.size


def image_size(path):
    with Image.open(path) as im:
        return im.size


# ---------------------------------------------------------------- slates

def _gradient(W, H, top, bottom):
    return themes.gradient(W, H, top, bottom)


def color_bars(W, H):
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    cols = [(192, 192, 192), (192, 192, 0), (0, 192, 192), (0, 192, 0), (192, 0, 192), (192, 0, 0), (0, 0, 192)]
    bw = W / 7
    for i, c in enumerate(cols):
        d.rectangle((i * bw, 0, (i + 1) * bw, H * 0.67), fill=c)
    low = [(0, 0, 192), (19, 19, 19), (192, 0, 192), (19, 19, 19), (0, 192, 192), (19, 19, 19), (192, 192, 192)]
    for i, c in enumerate(low):
        d.rectangle((i * bw, H * 0.67, (i + 1) * bw, H * 0.75), fill=c)
    d.rectangle((0, H * 0.75, W, H), fill=(16, 16, 16))
    return img


def _lum(c):
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def readable(bg, *choices):
    """The choice with the most contrast against bg."""
    return max(choices, key=lambda c: abs(_lum(c) - _lum(bg)))


def _case(T, text):
    return text.upper() if T.upper else text


def panel(d, box, T, s, fill=None, outline=None, width=2):
    """Spotlight / slate panels drawn in the theme's cell style."""
    x0, y0, x1, y1 = box
    fill = fill or T.c["spot_bg"]
    outline = outline or T.c["spot_border"]
    r = int(max(T.radius, 8 if T.radius else 0) * s)
    st = T.cell
    if st == "chunky":
        off = int(7 * s)
        d.rounded_rectangle((x0 + off, y0 + off, x1 + off, y1 + off), radius=r, fill=T.c["cell_border"])
        d.rounded_rectangle(box, radius=r, fill=fill, outline=T.c["cell_border"], width=max(2, int(3 * s)))
    elif st == "deco":
        d.rectangle(box, fill=fill, outline=outline, width=max(1, int(2 * s)))
        k = int(7 * s)
        d.rectangle((x0 + k, y0 + k, x1 - k, y1 - k), outline=outline, width=1)
    elif st == "pixel":
        p = max(3, int(5 * s))
        d.rectangle((x0 + p, y0, x1 - p, y1), fill=outline)
        d.rectangle((x0, y0 + p, x1, y1 - p), fill=outline)
        d.rectangle((x0 + p, y0 + p, x1 - p, y1 - p), fill=fill)
    elif st == "cut":
        c = 22 * s
        d.polygon([(x0 + c, y0), (x1, y0), (x1, y1 - c), (x1 - c, y1), (x0, y1), (x0, y0 + c)], fill=fill, outline=outline)
        d.line((x0 + c, y0, x0 + c + 120 * s, y0), fill=outline, width=max(2, int(3 * s)))
    elif st in ("bevel", "outline") or not r:
        d.rectangle(box, fill=fill, outline=outline, width=max(1, int(width * s)))
    else:
        d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=max(1, int(width * s)))


class _Text:
    """Draws text on its own layer so themes with glow can light it up in one blur pass."""

    def __init__(self, size, T, s):
        self.layer = Image.new("RGBA", size, (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.layer)
        self.T, self.s = T, s

    def onto(self, img, at=(0, 0)):
        lay = themes.text_glow(self.layer, self.s) if self.T.glow else self.layer
        img.alpha_composite(lay, at)


def render_slate(fonts, out_dir: Path, W, H, kind, ch, next_entry=None, logo_path=None, theme=None, dfonts=None):
    """kind: upnext | nocontent | error. Returns a PNG path (cached by content)."""
    T = theme or themes.get(themes.DEFAULT_THEME)
    D = dfonts or fonts
    title, sub = program_label(next_entry["i"]) if next_entry and next_entry.get("i") else ("", "")
    when = fmt_time(next_entry["s"], ch.get("clock", {}).get("format", "12h")) if next_entry else ""
    key = hashlib.md5(repr((kind, W, H, ch.get("name"), ch.get("number"), title, sub, when,
                            str(logo_path), "brand5", branding.version(), T.key, fonts.id, D.id)).encode()).hexdigest()[:16]
    path = out_dir / f"slate-{key}.png"
    if path.exists():
        return path
    s = H / 720
    ell = fonts.ellipsis(True)
    if kind == "error":
        img = color_bars(W, H).convert("RGBA")
        d = ImageDraw.Draw(img)
        msg = "PLEASE STAND BY"
        f = D.get(54 * s, True, msg)
        tw = text_w(d, msg, f)
        d.rectangle(((W - tw) / 2 - 30 * s, H * 0.32, (W + tw) / 2 + 30 * s, H * 0.32 + 90 * s), fill=(0, 0, 0))
        d.text((W / 2, H * 0.32 + 45 * s), msg, font=f, fill="white", anchor="mm")
        f2 = fonts.get(24 * s)
        m2 = "We are experiencing technical difficulties"
        d.text(((W - text_w(d, m2, f2)) / 2, H * 0.80), m2, font=f2, fill=(220, 220, 220))
    else:
        c = T.c
        img = themes.background(T, W, H, s, "slate")
        d = ImageDraw.Draw(img)
        pbox = [46 * s, 250 * s, W * 0.74, 640 * s]
        tx = _Text(img.size, T, s)
        td = tx.d
        if logo_path and Path(logo_path).exists():
            lg = Image.open(logo_path).convert("RGBA")
            lg.thumbnail((int(260 * s), int(160 * s)))
            img.alpha_composite(lg, (int(70 * s), int(60 * s)))
        else:
            label = fonts.text(f"{ch.get('number', '')}  {ch.get('name', '')}", True)
            cf = D.get(40 * s, True, label)
            plate = readable(c["head1"], c["accent"], c["text"])
            td.text((70 * s, 70 * s), label, font=cf, fill=plate)
        x, maxw = 80 * s, pbox[2] - 120 * s
        txt, mut, acc = c["text"], c["muted"], c["accent"]
        if kind == "nocontent":
            msg = _case(T, "Programming will resume shortly")
            f = D.get(46 * s, True, msg)
            y = 300 * s
            for line in wrap(td, msg, f, maxw, 2, ell):
                td.text((x, y), line, font=f, fill=txt)
                y += 62 * s
            f2 = fonts.get(24 * s)
            for line in wrap(td, "This channel has no playable media yet. Add sources in the admin page.", f2, maxw, 2, ell):
                td.text((x, y + 14 * s), line, font=f2, fill=mut)
                y += 34 * s
        else:
            label_f = D.get(34 * s, True, "UP NEXT")
            td.text((x, 282 * s), "UP NEXT", font=label_f, fill=acc)
            td.rectangle((x, 330 * s, x + 180 * s, 336 * s), fill=acc)
            ttl = _case(T, fonts.text(title or "Stay tuned", True))
            tf = fonts.get(66 * s, True, ttl)
            y = 352 * s
            for line in wrap(td, ttl, tf, maxw, 2, ell):
                td.text((x, y), line, font=tf, fill=txt)
                y += 78 * s
            if sub:
                sub = fonts.text(sub)
                sf = fonts.get(30 * s, False, sub)
                td.text((x, y + 6 * s), ellipsize(td, sub, sf, maxw, ell), font=sf, fill=mut)
                y += 46 * s
            if when:
                wl = f"Starting at {when}"
                wf = fonts.get(34 * s, True, wl)
                td.text((x, y + 18 * s), _case(T, wl), font=wf, fill=txt)
                y += 60 * s
        # a panel behind the words keeps them readable over busy decorations
        pbox[3] = min(H - 40 * s, y + 44 * s)
        veil = Image.new("RGBA", img.size, (0, 0, 0, 0))
        panel(ImageDraw.Draw(veil), tuple(pbox), T, s, fill=c["spot_bg"] + (232,), outline=c["spot_border"] + (255,))
        img.alpha_composite(veil)
        tx.onto(img)
    tint = T.c.get("brand") if kind != "error" and isinstance(T.c.get("brand"), tuple) else None
    mark = brand_image("orbital-b.png", 150 * s, 76 * s, 0.55 if not tint else 0.8, tint)
    if mark is not None:              # station bug in the corner of every slate
        img = img.convert("RGBA")
        img.alpha_composite(mark, (int(W - mark.width - 40 * s), int(H - mark.height - 32 * s)))
    out_dir.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(path, "PNG")
    return path


# ---------------------------------------------------------------- guide channel

class ImageCache:
    """Downloads Jellyfin artwork in the background so the guide never blocks on the network."""

    def __init__(self, folder: Path, fetch):
        self.folder = folder
        self.fetch = fetch
        self.pending = set()
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.lock = threading.Lock()
        self.mem = {}

    def get(self, item_id, max_h):
        if not item_id:
            return None
        key = (item_id, max_h)
        if key in self.mem:
            return self.mem[key]
        p = self.folder / f"{item_id}-{max_h}.jpg"
        if p.exists():
            try:
                im = Image.open(p).convert("RGB")
                self.mem[key] = im
                if len(self.mem) > 64:
                    self.mem.pop(next(iter(self.mem)))
                return im
            except Exception:
                return None
        with self.lock:
            if key not in self.pending:
                self.pending.add(key)
                self.pool.submit(self._download, item_id, max_h, p, key)
        return None

    def _download(self, item_id, max_h, p, key):
        try:
            data = self.fetch(item_id, max_h)
            if data:
                Image.open(io.BytesIO(data)).convert("RGB").save(p, "JPEG", quality=88)
        except Exception as e:
            log.debug("image fetch failed for %s: %s", item_id, e)
            try:
                Image.new("RGB", (2, 3), (8, 18, 56)).save(p, "JPEG")
            except Exception:
                pass
        finally:
            with self.lock:
                self.pending.discard(key)


def _arrow(d, x, ymid, size, left, color):
    if left:
        d.polygon([(x, ymid), (x + size, ymid - size * 0.7), (x + size, ymid + size * 0.7)], fill=color)
    else:
        d.polygon([(x + size, ymid), (x, ymid - size * 0.7), (x, ymid + size * 0.7)], fill=color)


class GuideRenderer:
    """Builds guide frames: a static header (clock, spotlight) above smoothly scrolling channel rows."""

    WINDOW_MIN = 90

    def __init__(self, fonts, images, W, H, station, clock_fmt="12h", theme=None, dfonts=None, header=None):
        self.fonts, self.images = fonts, images
        self.header = header or {"mode": "station"}
        self.dfonts = dfonts or fonts
        self.T = theme or themes.get(themes.DEFAULT_THEME)
        self.W, self.H = W, H
        self.s = s = H / 720
        self.station = station
        self.clock_fmt = clock_fmt
        self.head_h = self._even(340 * s)
        self.timebar_h = self._even(40 * s)
        self.top_h = self.head_h - self.timebar_h
        self.row_h = self._even(66 * s)
        self.chan_w = int(250 * s)
        self.body_view = H - self.head_h
        self._body = None
        self._body_key = None
        self._bg = None
        self.spot_idx = 0
        self.spot_switch = 0

    @staticmethod
    def _even(v):
        return int(v) // 2 * 2

    def layout(self, n_rows):
        rows_h = max(1, n_rows) * self.row_h
        scroll = rows_h > self.body_view
        canvas_h = self.head_h + (rows_h * 2 if scroll else self.body_view)
        return {"rows_h": rows_h, "scroll": scroll, "canvas_h": self._even(canvas_h + 1)}

    # rows = [(channel, logo_path, [entries])]
    def _render_rows(self, rows, now, logos):
        s, W, T, F, D = self.s, self.W, self.T, self.fonts, self.dfonts
        c = T.c
        ell = F.ellipsis(True)
        win0 = now - ((now + time.localtime(now).tm_gmtoff) % 1800)
        win1 = win0 + self.WINDOW_MIN * 60
        grid_w = W - self.chan_w
        px = grid_w / (win1 - win0)
        g = max(2, int(T.gap * s))
        img = Image.new("RGBA", (W, max(1, len(rows)) * self.row_h), c["bg"] + (255,))
        d = ImageDraw.Draw(img)
        tx = _Text(img.size, T, s)
        td = tx.d
        for r, (ch, logo, entries) in enumerate(rows):
            y0 = r * self.row_h + g // 2
            y1 = y0 + self.row_h - g
            themes.draw_cell(img, d, (g // 2, y0, self.chan_w - g, y1), c["chan"], T, s)
            num = str(ch.get("number", ""))
            nf = D.get(30 * s, True, num)
            td.text((14 * s, (y0 + y1) / 2), num, font=nf, fill=c["num"], anchor="lm")
            x_name = 14 * s + text_w(td, num, nf) + 12 * s
            if logo is not None:
                lg = logo.copy()
                lg.thumbnail((int(56 * s), int(self.row_h - 18 * s)))
                img.alpha_composite(lg, (int(x_name), int((y0 + y1 - lg.size[1]) / 2)))
                x_name += lg.size[0] + 10 * s
            name = F.text(ch["name"], True)
            name_f = F.get(21 * s, True, name)
            td.text((x_name, (y0 + y1) / 2), ellipsize(td, _case(T, name), name_f, self.chan_w - x_name - 10 * s, ell),
                    font=name_f, fill=c["chan_text"], anchor="lm")
            # merge consecutive non-program entries into "station break" cells
            cells = []
            for e in entries:
                if e["k"] != "program" and cells and cells[-1]["k"] != "program":
                    cells[-1] = dict(cells[-1], d=e["s"] + e["d"] - cells[-1]["s"])
                else:
                    cells.append(e)
            if not cells:
                cells = [{"s": win0, "d": win1 - win0, "k": "slate", "i": None}]
            for i, e in enumerate(cells):
                a, b = max(e["s"], win0), min(e["s"] + e["d"], win1)
                if b <= a:
                    continue
                x0 = self.chan_w + (a - win0) * px
                x1 = self.chan_w + (b - win0) * px - g
                if x1 - x0 < 2:
                    continue
                prog = e["k"] == "program"
                fill = T.cell_fill(i, e.get("i")) if prog else c["filler"]
                current = prog and e["s"] <= now < e["s"] + e["d"]
                themes.draw_cell(img, d, (x0, y0, x1, y1), fill, T, s, current)
                if x1 - x0 < 28 * s:
                    continue
                if prog:
                    title, sub = program_label(e["i"])
                else:
                    title, sub = ("Station Break" if e.get("msg") != "nocontent" else "No programming"), ""
                title = _case(T, F.text(title, True))
                ink = readable(fill, c["cell_text"], (255, 255, 255), (20, 20, 30)) if T.genre_colors else c["cell_text"]
                sub_ink = themes.mix(ink, fill, 0.32)
                tx0 = x0 + 10 * s
                maxw = x1 - x0 - 20 * s
                aw = 10 * s
                if e["s"] < win0 - 1:      # continues from earlier
                    _arrow(td, tx0, y0 + 20 * s, aw, True, sub_ink)
                    tx0 += aw + 6 * s
                    maxw -= aw + 6 * s
                if e["s"] + e["d"] > win1 + 1:
                    _arrow(td, x1 - 10 * s - aw, y0 + 20 * s, aw, False, sub_ink)
                    maxw -= aw + 6 * s
                tf = F.get(21 * s, True, title)
                tt = ellipsize(td, title, tf, maxw, ell)
                if sub and self.row_h >= 56 * s:
                    td.text((tx0, y0 + 6 * s), tt, font=tf, fill=ink)
                    sub = F.text(sub)
                    sf = F.get(16 * s, False, sub)
                    td.text((x0 + 10 * s, y0 + 34 * s), ellipsize(td, sub, sf, x1 - x0 - 20 * s, ell), font=sf, fill=sub_ink)
                else:
                    td.text((tx0, (y0 + y1) / 2), tt, font=tf, fill=ink, anchor="lm")
        tx.onto(img)
        if T.body == "scanlines":
            themes.scanlines(img, s, 46)
        # "now" marker
        xn = self.chan_w + (now - win0) * px
        ImageDraw.Draw(img).line((xn, 0, xn, img.size[1]), fill=c["now"], width=max(2, int(2 * s)))
        return img.convert("RGB"), win0

    def _header_bg(self):
        if self._bg is None:
            self._bg = themes.background(self.T, self.W, self.top_h, self.s, "header")
        return self._bg

    def frame(self, rows, now, logos, spotlights):
        """Returns (raw RGB bytes, canvas height, layout)."""
        s, W, T, F, D = self.s, self.W, self.T, self.fonts, self.dfonts
        c = T.c
        lay = self.layout(len(rows))
        body_key = (int(now // 60), len(rows), tuple(r[0]["id"] for r in rows))
        if body_key != self._body_key:
            self._body, self._win0 = self._render_rows(rows, now, logos)
            self._body_key = body_key
        canvas = Image.new("RGB", (W, lay["canvas_h"]), c["bg"])
        # ---- header
        head = self._header_bg().copy()
        d = ImageDraw.Draw(head)
        tx = _Text(head.size, T, s)
        td = tx.d
        dt = datetime.fromtimestamp(now)
        clock = fmt_time(now, self.clock_fmt)
        date = dt.strftime("%A, %B ") + str(dt.day)
        brand = c.get("brand")
        cf = D.get(70 * s, True, clock)
        hmode = self.header.get("mode", "station")
        tint = brand if isinstance(brand, tuple) else None
        # the corner artwork: at most 150 px tall (720p) so the clock and date still fit under it
        mark = None if hmode in ("name", "none") else corner_logo(
            self.header, "barnes-wordmark.png", (330 * s, 112 * s), (330 * s, 112 * s), tint, tint or c["text"])
        if mark is not None and (mark.height > 150 * s or mark.width > 500 * s):
            mark = mark.copy()
            mark.thumbnail((int(500 * s), int(150 * s)), Image.LANCZOS)
        if brand == "text" and hmode not in ("channel", "custom", "none"):     # teletext: page header line + double-height station name
            short = branding.short()
            line = f"P100  {short.upper()[:18]}  100  {dt.strftime('%a %d %b')}  {dt.strftime('%H:%M:%S')}"
            td.text((30 * s, 12 * s), line, font=F.get(26 * s, False, line), fill=c["text"])
            big = F.get(44 * s, True, short)
            bw = int(text_w(td, short.upper(), big)) + 4
            tmp = Image.new("RGBA", (bw, int(50 * s)), (0, 0, 0, 0))
            ImageDraw.Draw(tmp).text((0, 0), short.upper(), font=big, fill=c["accent"])
            tmp = tmp.resize((bw, int(92 * s)), Image.NEAREST)
            head.alpha_composite(tmp, (int(30 * s), int(40 * s)))
            y = 132 * s
        elif hmode == "none":
            y = 26 * s
        else:
            if mark is not None:
                head.alpha_composite(mark, (int(34 * s), int(16 * s)))
                y = 16 * s + mark.height + 6 * s
            elif hmode == "name":      # the station name as a title
                st = D.text(branding.short(), True)
                k = (self.header.get("size") or 100) / 100
                sz = 46 * s * k
                nf = D.get(sz, True, st)
                while text_w(td, _case(T, st), nf) > 500 * s and sz > 20 * s:
                    sz *= 0.9
                    nf = D.get(sz, True, st)
                td.text((38 * s, 24 * s), _case(T, st), font=nf, fill=c["accent"])
                y = 24 * s + nf.size * 1.25
            else:
                st = F.text(self.station.upper(), True)
                td.text((40 * s, 30 * s), st, font=F.get(30 * s, True, st), fill=c["accent"])
                y = 70 * s
        td.text((40 * s, y), clock, font=cf, fill=c["text"])
        td.text((44 * s, y + 84 * s), _case(T, date), font=F.get(26 * s, False, date), fill=c["muted"])
        self._spotlight(head, d, td, now, spotlights)
        tx.onto(head)
        canvas.paste(head.convert("RGB"), (0, 0))
        # ---- time bar
        cd = ImageDraw.Draw(canvas)
        y = self.top_h
        tb = c["timebar"]
        cd.rectangle((0, y, W, y + self.timebar_h), fill=tb)
        tf = F.get(20 * s, True)
        lab = readable(tb, c["accent"], c["timebar_text"])
        cd.text((14 * s, y + self.timebar_h / 2), _case(T, dt.strftime("%a %b ") + str(dt.day)), font=tf, fill=lab,
                anchor="lm")
        grid_w = W - self.chan_w
        tick = themes.mix(c["timebar_text"], tb, 0.5)
        for i in range(self.WINDOW_MIN // 30):
            x = self.chan_w + i * grid_w / (self.WINDOW_MIN // 30)
            cd.line((x, y + 6 * s, x, y + self.timebar_h - 6 * s), fill=tick, width=max(1, int(s)))
            cd.text((x + 10 * s, y + self.timebar_h / 2), _case(T, fmt_time(self._win0 + i * 1800, self.clock_fmt)),
                    font=tf, fill=c["timebar_text"], anchor="lm")
        # ---- body
        canvas.paste(self._body, (0, self.head_h))
        if lay["scroll"]:
            canvas.paste(self._body, (0, self.head_h + lay["rows_h"]))
        return canvas.tobytes(), lay["canvas_h"], lay

    def _spotlight(self, head, d, td, now, spots):
        s, W, T, F, D = self.s, self.W, self.T, self.fonts, self.dfonts
        c = T.c
        ell = F.ellipsis(True)
        x0, y0, x1, y1 = 560 * s, 22 * s, W - 24 * s, self.top_h - 26 * s
        panel(d, (x0, y0, x1, y1), T, s)
        if not spots:
            td.text((x0 + 24 * s, y0 + 24 * s), _case(T, "Welcome!"), font=D.get(40 * s, True), fill=c["text"])
            return
        if now >= self.spot_switch:
            self.spot_idx = (self.spot_idx + 1) % len(spots)
            self.spot_switch = now + 8
        ch, e = spots[self.spot_idx % len(spots)]
        item = e.get("i") or {}
        px = x0 + 20 * s
        poster = self.images.get(item.get("image_id"), int(240 * s)) if item else None
        if poster is not None and poster.size[0] > 4:
            p = poster.copy()
            p.thumbnail((int(180 * s), int(y1 - y0 - 40 * s)))
            head.paste(p, (int(px), int(y0 + (y1 - y0 - p.size[1]) / 2)))
            px += p.size[0] + 22 * s
        maxw = x1 - px - 22 * s
        lab = F.text(f"NOW ON {ch['number']} · {ch['name'].upper()}", True)
        lf = F.get(20 * s, True, lab)
        td.text((px, y0 + 20 * s), ellipsize(td, lab, lf, maxw, ell), font=lf, fill=c["accent"])
        title, sub = program_label(item)
        title = _case(T, F.text(title, True))
        tf = F.get(38 * s, True, title)
        y = y0 + 52 * s
        for line in wrap(td, title, tf, maxw, 2, ell):
            td.text((px, y), line, font=tf, fill=c["text"])
            y += 44 * s
        if sub:
            sub = F.text(sub)
            sf = F.get(20 * s, False, sub)
            td.text((px, y + 2 * s), ellipsize(td, sub, sf, maxw, ell), font=sf, fill=c["muted"])
            y += 30 * s
        fmt = self.clock_fmt
        tl = F.text(f"{fmt_time(e['s'], fmt)} – {fmt_time(e['s'] + e['d'], fmt)}")
        td.text((px, y + 6 * s), tl, font=F.get(20 * s, False, tl), fill=c["muted"])
        # progress bar
        frac = min(1, max(0, (now - e["s"]) / max(1, e["d"])))
        by = y1 - 26 * s
        rr = int(4 * s) if T.radius else 0
        d.rounded_rectangle((px, by, x1 - 22 * s, by + 8 * s), radius=rr, fill=c["track"])
        if frac > 0.01:
            d.rounded_rectangle((px, by, px + (x1 - 22 * s - px) * frac, by + 8 * s), radius=rr, fill=c["accent"])


# ---------------------------------------------------------------- text bumpers (white-on-black cards)

VAR_RE = re.compile(r"\{(\w+)\}")
BUMPER_SIZES = {"small": 0.05, "medium": 0.066, "large": 0.09, "huge": 0.13}
_last_cleanup = [0.0]


def bumper_vars(ctx, ch, station, now=None, clock_fmt="12h", weather=None):
    now = now or time.time()
    ctx = ctx or {}
    nxt = ctx.get("next_start")
    out = {"show": ctx.get("show", ""), "episode": ctx.get("episode", ""), "next": ctx.get("next", ""),
           "next_time": fmt_time(nxt, clock_fmt) if nxt else "", "channel": ch.get("name", ""),
           "number": str(ch.get("number", "")), "station": station or "", "time": fmt_time(now, clock_fmt),
           "day": datetime.fromtimestamp(now).strftime("%A")}
    out.update(weather or {})
    return out


def bumper_needs_weather(b):
    """True if a bumper only makes sense with live weather (a weather condition, or {temp}-style words)."""
    from .config import BUMPER_WEATHER_VARS, BUMPER_WEATHER_WHEN
    if b.get("when") in BUMPER_WEATHER_WHEN:
        return True
    texts = [c.get("text", "") for c in b.get("cards") or []] + [(b.get("style") or {}).get("tag", "")]
    return any(m.group(1).lower() in BUMPER_WEATHER_VARS for t in texts for m in VAR_RE.finditer(t or ""))


def bumper_time_ok(b, t):
    """Time-of-day conditions, checked against when the bumper will air."""
    when = b.get("when") or ""
    d = datetime.fromtimestamp(t or time.time())
    h = d.hour
    return {"late_night": h >= 23 or h < 5, "morning": 5 <= h < 11, "daytime": 11 <= h < 17,
            "evening": 17 <= h < 23, "weekend": d.weekday() >= 5}.get(when, True)


def bumper_weather_ok(b, values, tags):
    """Weather conditions, checked when the bumper is about to air."""
    from .config import BUMPER_WEATHER_WHEN
    if not bumper_needs_weather(b):
        return True
    if not values:
        return False
    if b.get("when") in BUMPER_WEATHER_WHEN and b["when"] not in tags:
        return False
    texts = [c.get("text", "") for c in b.get("cards") or []]
    return all(values.get(m.group(1).lower(), "x") != "" for t in texts for m in VAR_RE.finditer(t or ""))


def fill_vars(text, values):
    return VAR_RE.sub(lambda m: str(values.get(m.group(1).lower(), m.group(0))), text or "")


def _apply_case(text, mode):
    return text.lower() if mode == "lower" else text.upper() if mode == "upper" else text


def _hex(c, default):
    try:
        c = (c or "").lstrip("#")
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) if len(c) == 6 else default
    except ValueError:
        return default


def _cleanup(folder: Path, max_age=86400):
    if time.time() - _last_cleanup[0] < 3600:
        return
    _last_cleanup[0] = time.time()
    for p in folder.glob("*"):
        try:
            if time.time() - p.stat().st_mtime > max_age:
                if p.is_dir():
                    for f in p.iterdir():
                        f.unlink()
                    p.rmdir()
                else:
                    p.unlink()
        except OSError:
            pass


def render_bumper_card(fonts, W, H, bumper, text, values):
    """One card as a Pillow image."""
    st = bumper.get("style") or {}
    bg, fg = _hex(st.get("bg"), (0, 0, 0)), _hex(st.get("fg"), (255, 255, 255))
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    body = _apply_case(fill_vars(text, values), st.get("case", "lower"))
    size = H * BUMPER_SIZES.get(st.get("size"), 0.066)
    bold = st.get("font") == "bold"

    lib = font_set(st.get("font_id"), fonts) if st.get("font_id") else None

    def font(sz, txt):
        fp = st.get("font_path")
        if fp and Path(fp).is_file() and not is_cjk(txt):
            try:
                return ImageFont.truetype(fp, int(sz))
            except Exception:
                pass
        return (lib or fonts).get(sz, bold, txt)

    f = font(size, body)
    left = st.get("align") == "left"
    maxw = W * (0.76 if left else 0.8)
    lines = []
    for para in body.split("\n"):
        lines += wrap(d, para, f, maxw, 6) if para.strip() else [""]
    lh = size * 1.35
    y = (H - lh * len(lines)) / 2
    for line in lines:
        x = W * 0.12 if left else (W - text_w(d, line, f)) / 2
        d.text((x, y), line, font=f, fill=fg)
        y += lh
    tag = _apply_case(fill_vars(st.get("tag", ""), values), st.get("case", "lower")).strip()
    if tag:
        tf = font(H * 0.032, tag)
        m = H * 0.06
        tw = text_w(d, tag, tf)
        pos = st.get("tag_pos", "bottom-right")
        tx = m * 1.4 if "left" in pos else W - tw - m * 1.4
        ty = m if "top" in pos else H - m - H * 0.04
        dim = tuple(int(fg[i] * 0.8 + bg[i] * 0.2) for i in range(3))
        d.text((tx, ty), tag, font=tf, fill=dim)
    return img


def render_bumper(fonts, out_dir: Path, W, H, bumper, values, total=None):
    """Render every card and write an ffconcat playlist that ffmpeg plays as one clip. Returns the playlist path."""
    natural = sum(c["seconds"] for c in bumper["cards"]) + bumper.get("gap", 0) * (len(bumper["cards"]) + 1)
    scale = (total / natural) if total and natural else 1.0
    texts = [fill_vars(c["text"], values) for c in bumper["cards"]]
    key = hashlib.md5(repr((W, H, bumper.get("style"), bumper.get("gap"), [c["seconds"] for c in bumper["cards"]],
                            texts, fill_vars((bumper.get("style") or {}).get("tag", ""), values),
                            round(scale, 3))).encode()).hexdigest()[:16]
    folder = out_dir / f"bump-{key}"
    playlist = folder / "bumper.ffconcat"
    if playlist.exists():
        return playlist
    out_dir.mkdir(parents=True, exist_ok=True)
    _cleanup(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    bg = _hex((bumper.get("style") or {}).get("bg"), (0, 0, 0))
    Image.new("RGB", (W, H), bg).save(folder / "blank.png")
    lines = ["ffconcat version 1.0"]
    gap = bumper.get("gap", 0) * scale
    last = "blank.png"
    for n, c in enumerate(bumper["cards"]):
        if gap > 0.04:
            lines += ["file blank.png", f"duration {gap:.3f}"]
        name = f"card{n}.png"
        render_bumper_card(fonts, W, H, bumper, c["text"], values).save(folder / name)
        lines += [f"file {name}", f"duration {c['seconds'] * scale:.3f}"]
        last = name
    if gap > 0.04:
        lines += ["file blank.png", f"duration {gap:.3f}"]
        last = "blank.png"
    lines.append(f"file {last}")   # the concat demuxer needs the final entry repeated
    playlist.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return playlist

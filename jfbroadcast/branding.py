"""Station branding: the name and artwork shown everywhere (guide, weather, slates, TV page, admin page, Jellyfin,
web-app icons and the Android TV app). The Barnes look is the default; Appearance -> Branding replaces it.

Artwork:
  wordmark  the wide logo (guide header, TV page start screen, welcome screen)       default web/brand/barnes-wordmark.png
  mark      the small logo / bug (admin header, Up Next cards, weather header)      default web/brand/orbital-b.png
  icon      a square app icon (browser tab, phone home screen, TV app)               default: made from the mark
Uploads live in <data>/brand/. One-colour artwork on a transparent background can follow each theme's colours
("recolor"); full-colour logos are better left as they are.
"""
import hashlib
import io
import json
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from . import BRAND, BRAND_SHORT

WEB = Path(__file__).resolve().parent.parent / "web"
DEFAULT_FILES = {"wordmark": WEB / "brand" / "barnes-wordmark.png", "mark": WEB / "brand" / "orbital-b.png"}
KINDS = ("wordmark", "mark", "icon")
DEFAULT_COLOR = "#0b1a4a"

_store = [None]          # the app's Store (set by App)


def init(store):
    _store[0] = store


def _settings():
    s = _store[0]
    return s.settings if s is not None else {}


def _dir():
    s = _store[0]
    return (s.data_dir / "brand") if s is not None else None


def name():
    return (_settings().get("station_name") or "").strip() or BRAND


def short():
    st = _settings()
    sh = (st.get("station_short") or "").strip()
    if sh:
        return sh
    n = name()
    return BRAND_SHORT if n == BRAND else n


def color():
    c = (_settings().get("brand_color") or "").strip()
    return c if len(c) == 7 and c.startswith("#") else DEFAULT_COLOR


def recolor():
    """Tint the artwork to each theme (right for one-colour artwork like the Barnes logo)."""
    st = _settings()
    if st.get("brand_recolor") is not None:
        return bool(st["brand_recolor"])
    return not (custom("wordmark") or custom("mark"))


def is_default():
    return name() == BRAND and not any(custom(k) for k in KINDS)


def custom(kind):
    d = _dir()
    p = d / f"{kind}.png" if d else None
    return p if p is not None and p.is_file() else None


def path(kind):
    """The file to use for wordmark / mark (custom upload, else the Barnes default)."""
    p = custom(kind)
    if p:
        return p
    if kind == "wordmark" and custom("mark"):        # only a logo uploaded: use it for both
        return custom("mark")
    if kind == "mark" and custom("wordmark") and not custom("mark"):
        return custom("wordmark")
    return DEFAULT_FILES.get(kind)


def version():
    """Changes whenever the branding does (for cache-busting URLs and render caches)."""
    parts = [name(), short(), color(), str(recolor())]
    for k in KINDS:
        p = custom(k)
        parts.append(f"{k}:{p.stat().st_mtime if p else 0}")
    return hashlib.md5("|".join(parts).encode()).hexdigest()[:10]


def public():
    return {"name": name(), "short": short(), "color": color(), "recolor": recolor(), "default": is_default(),
            "custom": {k: bool(custom(k)) for k in KINDS}, "version": version()}


def save_upload(kind, data):
    """Store an uploaded image (any format) as PNG, trimmed of empty borders, at most 1600 px."""
    if kind not in KINDS:
        raise ValueError("unknown artwork")
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGBA")
    box = img.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    if box and kind != "icon":
        img = img.crop(box)
    img.thumbnail((1600, 1600), Image.LANCZOS)
    d = _dir()
    d.mkdir(parents=True, exist_ok=True)
    img.save(d / f"{kind}.png", "PNG")
    _clear_generated()
    return img.size


def remove(kind):
    p = custom(kind)
    if p:
        p.unlink()
    _clear_generated()


def _clear_generated():
    d = _dir()
    if d and (d / "gen").is_dir():
        for f in (d / "gen").iterdir():
            try:
                f.unlink()
            except OSError:
                pass


# ------------------------------------------------------------------ generated images (icons, TV app artwork)

def _hex(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _fit(img, w, h):
    img = img.copy()
    k = min(w / img.width, h / img.height)
    return img.resize((max(1, round(img.width * k)), max(1, round(img.height * k))), Image.LANCZOS)


def _art(kind):
    p = path(kind)
    return Image.open(p).convert("RGBA") if p else None


def _readable_on(bg, img):
    """White artwork stays white; dark single-colour artwork on a dark background is drawn white instead."""
    if not recolor():
        return img
    lum = sum(c * w for c, w in zip(bg, (0.299, 0.587, 0.114)))
    ink = (255, 255, 255) if lum < 150 else (20, 24, 40)
    solid = Image.new("RGBA", img.size, ink + (255,))
    solid.putalpha(img.getchannel("A"))
    return solid


def icon_image(size):
    """A square icon: the uploaded icon, else the mark centred on the brand colour."""
    c = custom("icon")
    if c:
        img = Image.open(c).convert("RGBA")
        img = ImageOps.fit(img, (size, size), Image.LANCZOS)
        bg = Image.new("RGBA", (size, size), _hex(color()) + (255,))
        bg.alpha_composite(img)
        return bg
    bg = _hex(color())
    out = Image.new("RGBA", (size, size), bg + (255,))
    mark = _art("mark")
    if mark is not None:
        m = _fit(_readable_on(bg, mark), size * 0.74, size * 0.74)
        out.alpha_composite(m, ((size - m.width) // 2, (size - m.height) // 2))
    return out


def adaptive_foreground(size=432):
    """Android adaptive-icon foreground: 108 dp canvas, artwork inside the 66 dp safe circle."""
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    c = custom("icon")
    if c:
        art = ImageOps.fit(Image.open(c).convert("RGBA"), (round(size * 0.68), round(size * 0.68)), Image.LANCZOS)
    else:
        mark = _art("mark")
        if mark is None:
            return out
        art = _fit(_readable_on(_hex(color()), mark), size * 0.52, size * 0.52)
    out.alpha_composite(art, ((size - art.width) // 2, (size - art.height) // 2))
    return out


def monochrome(img):
    """Themed-icon layer (Android 13+): the shape only, in white."""
    out = Image.new("RGBA", img.size, (255, 255, 255, 0))
    out.putalpha(img.getchannel("A"))
    return out


def tv_banner(w=320, h=180):
    """Android TV launcher banner: the wordmark on the brand colour (with a soft vertical gradient)."""
    bg = _hex(color())
    top = tuple(min(255, int(c * 1.35 + 12)) for c in bg)
    img = Image.new("RGBA", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        k = y / (h - 1)
        d.line((0, y, w, y), fill=tuple(int(top[i] * (1 - k) + bg[i] * k) for i in range(3)) + (255,))
    art = _art("wordmark")
    if art is not None:
        a = _fit(_readable_on(bg, art), w * 0.84, h * 0.62)
        img.alpha_composite(a, ((w - a.width) // 2, (h - a.height) // 2))
    return img


def generated(name_, size=None):
    """Cached PNG bytes of a generated image: icon-<n>, favicon, banner, adaptive-fg, adaptive-mono."""
    d = _dir()
    key = f"{name_}-{size}-{version()}.png"
    if d:
        p = d / "gen" / key
        if p.is_file():
            return p.read_bytes()
    if name_ == "icon":
        img = icon_image(size)
    elif name_ == "favicon":
        img = icon_image(64)
    elif name_ == "banner":
        img = tv_banner(*(size or (320, 180)))
    elif name_ == "adaptive-fg":
        img = adaptive_foreground(size or 432)
    elif name_ == "adaptive-mono":
        img = monochrome(adaptive_foreground(size or 432))
    else:
        raise ValueError(name_)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    data = buf.getvalue()
    if d:
        (d / "gen").mkdir(parents=True, exist_ok=True)
        (d / "gen" / key).write_bytes(data)
    return data


def tvapp_kit():
    """A zip for android-tv/build.py --brand: name, colour, launcher icon layers and the TV banner."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("branding.json", json.dumps({"name": short(), "full_name": name(), "color": color()}, indent=2))
        z.writestr("banner.png", generated("banner", (320, 180)))
        z.writestr("banner-xxhdpi.png", generated("banner", (640, 360)))
        z.writestr("ic_launcher_foreground.png", generated("adaptive-fg", 432))
        z.writestr("ic_launcher_monochrome.png", generated("adaptive-mono", 432))
        z.writestr("ic_launcher.png", generated("icon", 192))
        z.writestr("README.txt", "Branding for the Android TV app. Build with:\n"
                                 "    python android-tv/build.py --brand this-file.zip\n"
                                 "or unzip it into android-tv/branding/ and run get-tools-and-build.sh.\n")
    return buf.getvalue()

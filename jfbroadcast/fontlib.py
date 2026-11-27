"""The bundled font library (web/fonts) plus any fonts the user drops into <data>/fonts.

Every font has an id. Settings store ids ("theme" = use the theme's choice, "system" = the OS font).
The same files are used by Pillow (guide, slates, bumpers), ffmpeg drawtext (clock) and the web pages (@font-face).
"""
import logging
import os
import re
from pathlib import Path

log = logging.getLogger("fonts")

FONT_DIR = Path(__file__).resolve().parent.parent / "web" / "fonts"
USER_DIR = [None]           # set by App: <data>/fonts

# scale = visual size correction so every font looks about as big as the default at the same point size
CATALOG = [
    {"id": "system", "name": "System (Segoe UI / DejaVu)", "kind": "text", "css": "system-ui, 'Segoe UI', Roboto, sans-serif",
     "desc": "Your computer's standard font"},
    {"id": "inter", "name": "Inter", "regular": "Inter-Regular.ttf", "bold": "Inter-Bold.ttf", "kind": "text",
     "desc": "Clean, modern sans"},
    {"id": "maru", "name": "Maru Gothic (Japanese broadcast)", "regular": "MPLUSRounded1c-Medium.ttf",
     "bold": "MPLUSRounded1c-ExtraBold.ttf", "kind": "text", "cjk": True,
     "desc": "Rounded gothic like the corner clocks on Japanese TV. Has Japanese characters"},
    {"id": "dseg7", "name": "7-Segment LED", "regular": "DSEG7Classic-Bold.ttf", "bold": "DSEG7Classic-Bold.ttf",
     "kind": "clock", "scale": 0.86, "desc": "Digital alarm clock / VCR. Digits only - use 24-hour or no AM/PM"},
    {"id": "dseg14", "name": "14-Segment LED", "regular": "DSEG14Classic-Bold.ttf", "bold": "DSEG14Classic-Bold.ttf",
     "kind": "clock", "scale": 0.86, "desc": "Segmented display that can also spell AM / PM"},
    {"id": "bebas", "name": "Bebas Neue", "regular": "BebasNeue-Regular.ttf", "bold": "BebasNeue-Regular.ttf",
     "kind": "display", "scale": 1.18, "desc": "Tall condensed capitals, news-ticker style"},
    {"id": "orbitron", "name": "Orbitron", "regular": "Orbitron-Medium.ttf", "bold": "Orbitron-ExtraBold.ttf",
     "kind": "display", "scale": 0.88, "desc": "Geometric sci-fi"},
    {"id": "rajdhani", "name": "Rajdhani", "regular": "Rajdhani-Medium.ttf", "bold": "Rajdhani-Bold.ttf",
     "kind": "text", "scale": 1.12, "desc": "Squared techno sans"},
    {"id": "audiowide", "name": "Audiowide", "regular": "Audiowide-Regular.ttf", "bold": "Audiowide-Regular.ttf",
     "kind": "display", "scale": 0.9, "desc": "Wide racing / synthwave"},
    {"id": "monoton", "name": "Monoton", "regular": "Monoton-Regular.ttf", "bold": "Monoton-Regular.ttf",
     "kind": "display", "scale": 0.92, "desc": "Neon tubes"},
    {"id": "vt323", "name": "VT323", "regular": "VT323-Regular.ttf", "bold": "VT323-Regular.ttf", "kind": "text",
     "scale": 1.3, "desc": "Old computer terminal / teletext"},
    {"id": "sharetech", "name": "Share Tech Mono", "regular": "ShareTechMono-Regular.ttf",
     "bold": "ShareTechMono-Regular.ttf", "kind": "text", "desc": "Monospaced terminal"},
    {"id": "pressstart", "name": "Press Start 2P", "regular": "PressStart2P-Regular.ttf",
     "bold": "PressStart2P-Regular.ttf", "kind": "display", "scale": 0.66, "desc": "8-bit video game"},
    {"id": "dotgothic", "name": "DotGothic16", "regular": "DotGothic16-Regular.ttf", "bold": "DotGothic16-Regular.ttf",
     "kind": "text", "cjk": True, "desc": "Japanese pixel font (retro game / dot-matrix). Has Japanese characters"},
    {"id": "limelight", "name": "Limelight", "regular": "Limelight-Regular.ttf", "bold": "Limelight-Regular.ttf",
     "kind": "display", "scale": 0.95, "desc": "1920s marquee"},
    {"id": "poiret", "name": "Poiret One", "regular": "PoiretOne-Regular.ttf", "bold": "PoiretOne-Regular.ttf",
     "kind": "display", "scale": 1.05, "desc": "Thin art deco"},
    {"id": "josefin", "name": "Josefin Sans", "regular": "JosefinSans-Regular.ttf", "bold": "JosefinSans-Bold.ttf",
     "kind": "text", "scale": 1.05, "desc": "Elegant geometric, vintage feel"},
    {"id": "atomic", "name": "Atomic Age", "regular": "AtomicAge-Regular.ttf", "bold": "AtomicAge-Regular.ttf",
     "kind": "display", "scale": 0.95, "desc": "1950s space-age"},
    {"id": "shrikhand", "name": "Shrikhand", "regular": "Shrikhand-Regular.ttf", "bold": "Shrikhand-Regular.ttf",
     "kind": "display", "scale": 0.92, "desc": "Chunky '70s italic"},
    {"id": "righteous", "name": "Righteous", "regular": "Righteous-Regular.ttf", "bold": "Righteous-Regular.ttf",
     "kind": "display", "desc": "Rounded '70s / retro"},
    {"id": "fredoka", "name": "Fredoka", "regular": "Fredoka-Medium.ttf", "bold": "Fredoka-Bold.ttf",
     "kind": "text", "desc": "Friendly rounded"},
    {"id": "rubik", "name": "Rubik", "regular": "Rubik-Regular.ttf", "bold": "Rubik-ExtraBold.ttf", "kind": "text",
     "desc": "Soft geometric sans"},
    {"id": "nunito", "name": "Nunito", "regular": "Nunito-Regular.ttf", "bold": "Nunito-ExtraBold.ttf",
     "kind": "text", "desc": "Rounded and airy"},
]
BY_ID = {f["id"]: f for f in CATALOG}
_scan_cache = [None, None]


def _family_name(path):
    try:
        from PIL import ImageFont
        fam, style = ImageFont.truetype(str(path), 20).getname()
        return f"{fam} {style}".replace(" Regular", "").strip() or path.stem
    except Exception:
        return path.stem


def user_fonts():
    """Fonts dropped into <data>/fonts (.ttf / .otf). id = custom:<file name>."""
    folder = USER_DIR[0]
    if not folder or not Path(folder).is_dir():
        return []
    files = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in (".ttf", ".otf") and p.is_file())
    key = tuple((p.name, p.stat().st_mtime) for p in files)
    if _scan_cache[0] == key:
        return _scan_cache[1]
    out = []
    for p in files:
        out.append({"id": "custom:" + p.name, "name": _family_name(p) + " (your font)", "regular": str(p),
                    "bold": str(p), "kind": "custom", "custom": True, "desc": f"From your fonts folder: {p.name}"})
    _scan_cache[:] = [key, out]
    return out


def all_fonts():
    return CATALOG + user_fonts()


def get(font_id):
    if not font_id:
        return None
    if font_id in BY_ID:
        return BY_ID[font_id]
    return next((f for f in user_fonts() if f["id"] == font_id), None)


def file_path(font, bold=False):
    """Absolute path of a font's regular / bold file, or '' (system font / missing file)."""
    if not font or not font.get("regular"):
        return ""
    name = font["bold" if bold else "regular"]
    p = Path(name) if os.path.isabs(name) else FONT_DIR / name
    return str(p) if p.is_file() else ""


def family(font_id):
    """The font's real family name (what libass needs to find it in the fonts folder)."""
    f = get(font_id)
    path = file_path(f, True) if f else ""
    if not path:
        return ""
    try:
        from PIL import ImageFont
        return ImageFont.truetype(path, 20).getname()[0]
    except Exception:
        return ""


def css_family(font_id):
    f = get(font_id)
    if not f:
        return "system-ui, 'Segoe UI', Roboto, sans-serif"
    if f.get("css"):
        return f["css"]
    return f"'btv-{_slug(f['id'])}', system-ui, 'Segoe UI', sans-serif"


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def url_for(font, bold=False):
    name = font["bold" if bold else "regular"]
    if font.get("custom"):
        from urllib.parse import quote
        return "/fonts/custom/" + quote(Path(name).name)
    return "/fonts/" + name


def font_face_css():
    """@font-face rules for the whole library (browsers only download the fonts a page actually uses)."""
    out = []
    for f in all_fonts():
        if not f.get("regular"):
            continue
        fam = "btv-" + _slug(f["id"])
        adj = f"size-adjust: {round(f.get('scale', 1.0) * 100)}%; " if f.get("scale") else ""
        same = f["regular"] == f["bold"]
        out.append(f"@font-face {{ font-family: '{fam}'; src: url('{url_for(f)}'); font-weight: {'100 900' if same else '100 600'}; "
                   f"font-display: swap; {adj}}}")
        if not same:
            out.append(f"@font-face {{ font-family: '{fam}'; src: url('{url_for(f, True)}'); font-weight: 700 900; "
                       f"font-display: swap; {adj}}}")
    return "\n".join(out)


def public_list():
    return [{"id": f["id"], "name": f["name"], "kind": f.get("kind", "text"), "desc": f.get("desc", ""),
             "cjk": bool(f.get("cjk")), "css": css_family(f["id"]), "custom": bool(f.get("custom"))}
            for f in all_fonts()]

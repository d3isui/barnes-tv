"""Station themes: one palette + font set + decoration style applied to the guide channel, the on-air slates
(Up Next / Programming will resume), the admin page, the TV page and the phone remote."""
import hashlib
import json
import math
import random
import re

from PIL import Image, ImageDraw, ImageFilter

from . import fontlib

DEFAULT_THEME = "barnes"

# Colour keys (all "#rrggbb"):
#   bg/head1/head2 ..... guide background and header gradient       panel/panel2/line/input ... admin + TV panels
#   text/muted ......... main and secondary text                       accent/accent2/on_accent .. highlights
#   now ................ the red "now" line                            chan/chan_text/num ........ guide channel column
#   cells .............. programme cell colours (cycled)               filler ..................... station breaks
#   cell_border/cell_text/timebar/timebar_text/spot_bg/spot_border/track
THEMES = {
    "barnes": {
        "name": "Barnes Classic", "desc": "The original navy and gold Barnes look.",
        "fonts": {"ui": "system", "display": "inter", "guide": "inter", "guide_display": "inter", "clock": "system"},
        "c": {"bg": "#081238", "head1": "#18266e", "head2": "#0a1442", "panel": "#121a33", "panel2": "#18234a",
              "line": "#263465", "input": "#0a0f22", "page": "#0b1020", "text": "#ffffff", "muted": "#bfdbfe",
              "accent": "#ffd23f", "accent2": "#3b82f6", "on_accent": "#1a1400", "now": "#ef4444",
              "chan": "#10286e", "chan_text": "#ffffff", "num": "#ffd23f", "cells": ["#1d4ed8", "#2540af"],
              "filler": "#182c78", "cell_border": "#93c5fd", "cell_text": "#ffffff", "timebar": "#1e3a8a",
              "timebar_text": "#ffffff", "spot_bg": "#060c28", "spot_border": "#4664c8", "track": "#283264"},
        "cell": "flat", "radius": 0, "deco": "stripes",
    },
    "retro_cable": {
        "name": "Retro Cable", "desc": "Late-'80s cable guide: royal blue grid, bevelled boxes, yellow numbers, scanlines.",
        "fonts": {"ui": "rubik", "display": "bebas", "guide": "rubik", "guide_display": "bebas", "clock": "bebas"},
        "c": {"bg": "#00004a", "head1": "#1d1da8", "head2": "#000058", "panel": "#0b0b6a", "panel2": "#15158a",
              "line": "#3b3bc4", "input": "#00003a", "page": "#00003a", "text": "#ffffff", "muted": "#cfd2ff",
              "accent": "#ffff55", "accent2": "#ff5555", "on_accent": "#00004a", "now": "#ff3030",
              "chan": "#14148c", "chan_text": "#ffffff", "num": "#ffff55", "cells": ["#2a2ad0", "#2222b4"],
              "filler": "#46209a", "cell_border": "#9a9aff", "cell_text": "#ffffff", "timebar": "#b31717",
              "timebar_text": "#ffffff", "spot_bg": "#000038", "spot_border": "#ffff55", "track": "#22228a"},
        "cell": "bevel", "radius": 0, "deco": "vhs", "body": "scanlines", "upper": True,
    },
    "groovy70s": {
        "name": "Groovy '70s", "desc": "Burnt orange, mustard and chocolate with rainbow stripes and soft round corners.",
        "fonts": {"ui": "fredoka", "display": "shrikhand", "guide": "righteous", "guide_display": "shrikhand",
                  "clock": "righteous"},
        "c": {"bg": "#2b1a10", "head1": "#5c3419", "head2": "#2b1a10", "panel": "#3a2416", "panel2": "#4a2e1a",
              "line": "#7a4a26", "input": "#24150c", "page": "#22140b", "text": "#fff3dc", "muted": "#f3cfa0",
              "accent": "#f2b134", "accent2": "#e0622a", "on_accent": "#2b1a10", "now": "#ff5a2a",
              "chan": "#4a2a16", "chan_text": "#fff3dc", "num": "#f2b134", "cells": ["#c45a22", "#8a5a1c", "#a8461e"],
              "filler": "#6b3b1e", "cell_border": "#f2b134", "cell_text": "#fff3dc", "timebar": "#d99a2b",
              "timebar_text": "#2b1a10", "spot_bg": "#3a2214", "spot_border": "#f2b134", "track": "#5a361c"},
        "cell": "round", "radius": 18, "gap": 5, "deco": "rainbow70s",
    },
    "futuristic": {
        "name": "Sleek Futuristic", "desc": "Black glass, cyan hairlines, cut corners and a soft neon glow.",
        "fonts": {"ui": "rajdhani", "display": "orbitron", "guide": "rajdhani", "guide_display": "orbitron",
                  "clock": "orbitron"},
        "c": {"bg": "#04070d", "head1": "#0a1828", "head2": "#04070d", "panel": "#0a111c", "panel2": "#0f1a2a",
              "line": "#13405a", "input": "#050a12", "page": "#03060b", "text": "#e8fbff", "muted": "#86c2d2",
              "accent": "#00e5ff", "accent2": "#ff2bd6", "on_accent": "#001318", "now": "#ff2bd6",
              "chan": "#07121d", "chan_text": "#e8fbff", "num": "#00e5ff", "cells": ["#0b1d2b", "#091723"],
              "filler": "#0d1420", "cell_border": "#00e5ff", "cell_text": "#e8fbff", "timebar": "#061019",
              "timebar_text": "#9ee9f5", "spot_bg": "#05101a", "spot_border": "#00e5ff", "track": "#0e2a38"},
        "cell": "cut", "radius": 0, "gap": 4, "deco": "circuit", "glow": True,
    },
    "artdeco": {
        "name": "Art Deco", "desc": "Gatsby black and gold: sunbursts, double gold frames, marquee lettering.",
        "fonts": {"ui": "josefin", "display": "limelight", "guide": "josefin", "guide_display": "limelight",
                  "clock": "limelight"},
        "c": {"bg": "#0c0b09", "head1": "#221d14", "head2": "#0c0b09", "panel": "#15130f", "panel2": "#1f1b14",
              "line": "#5a4a26", "input": "#0c0b09", "page": "#0a0907", "text": "#f6ecd2", "muted": "#cdbd92",
              "accent": "#d4af37", "accent2": "#3a8c7a", "on_accent": "#1a1405", "now": "#c0392b",
              "chan": "#16130e", "chan_text": "#f6ecd2", "num": "#d4af37", "cells": ["#1d1a15", "#25211a"],
              "filler": "#14120e", "cell_border": "#d4af37", "cell_text": "#f6ecd2", "timebar": "#d4af37",
              "timebar_text": "#0c0b09", "spot_bg": "#0f0d0a", "spot_border": "#d4af37", "track": "#3a3020"},
        "cell": "deco", "radius": 0, "gap": 4, "deco": "sunburst", "upper": True,
    },
    "memphis": {
        "name": "Corporate Memphis", "desc": "Flat pastels, chunky outlines, squiggles and confetti. Light theme.",
        "fonts": {"ui": "rubik", "display": "fredoka", "guide": "rubik", "guide_display": "fredoka", "clock": "fredoka"},
        "c": {"bg": "#fbf6ee", "head1": "#fff1dc", "head2": "#fbf6ee", "panel": "#ffffff", "panel2": "#f3eeff",
              "line": "#d9d2f5", "input": "#ffffff", "page": "#fbf6ee", "text": "#1e1b4b", "muted": "#5b5689",
              "accent": "#ff6b6b", "accent2": "#6c5ce7", "on_accent": "#ffffff", "now": "#ff3d6e",
              "chan": "#6c5ce7", "chan_text": "#ffffff", "num": "#ffd93d",
              "cells": ["#c4b5fd", "#ffc6a8", "#a7f3d0", "#fde68a"], "filler": "#ece7f7", "cell_border": "#1e1b4b",
              "cell_text": "#1e1b4b", "timebar": "#1e1b4b", "timebar_text": "#ffffff", "spot_bg": "#ffffff",
              "spot_border": "#1e1b4b", "track": "#ece7ff", "brand": "#1e1b4b"},
        "cell": "chunky", "radius": 14, "gap": 6, "deco": "memphis", "light": True,
    },
    "synthwave": {
        "name": "Synthwave", "desc": "Outrun sunset, chrome grid, hot pink and cyan neon.",
        "fonts": {"ui": "rajdhani", "display": "monoton", "guide": "audiowide", "guide_display": "audiowide",
                  "clock": "monoton"},
        "c": {"bg": "#12041f", "head1": "#3b0a5c", "head2": "#12041f", "panel": "#1a0830", "panel2": "#24103f",
              "line": "#5a2588", "input": "#10031c", "page": "#0e0218", "text": "#ffffff", "muted": "#e3b0ff",
              "accent": "#05d9e8", "accent2": "#ff2a6d", "on_accent": "#12041f", "now": "#ffd319",
              "chan": "#1d0733", "chan_text": "#ffffff", "num": "#ffd319", "cells": ["#3a0f5e", "#2d0b4a"],
              "filler": "#1f0838", "cell_border": "#ff2a6d", "cell_text": "#ffffff", "timebar": "#2a0845",
              "timebar_text": "#05d9e8", "spot_bg": "#1a0630", "spot_border": "#ff2a6d", "track": "#3a1060"},
        "cell": "glow", "radius": 6, "gap": 4, "deco": "outrun", "glow": True,
    },
    "teletext": {
        "name": "Teletext", "desc": "Page 100: black screen, eight blocky colours and mosaic graphics.",
        "fonts": {"ui": "vt323", "display": "vt323", "guide": "vt323", "guide_display": "vt323", "clock": "vt323"},
        "c": {"bg": "#000000", "head1": "#000000", "head2": "#000000", "panel": "#000000", "panel2": "#00007a",
              "line": "#0000ff", "input": "#000000", "page": "#000000", "text": "#ffffff", "muted": "#00ffff",
              "accent": "#ffff00", "accent2": "#00ff00", "on_accent": "#000000", "now": "#ff0000",
              "chan": "#0000ff", "chan_text": "#ffff00", "num": "#ffffff", "cells": ["#0000c0", "#00008a"],
              "filler": "#800080", "cell_border": "#000000", "cell_text": "#ffffff", "timebar": "#000000",
              "timebar_text": "#00ff00", "spot_bg": "#000000", "spot_border": "#ff00ff", "track": "#00007a",
              "brand": "text"},
        "cell": "flat", "radius": 0, "gap": 4, "deco": "teletext", "upper": True,
    },
    "tokyo": {
        "name": "Tokyo Broadcast", "desc": "Japanese TV listings: crisp white grid, red bars, genre-coloured cells, "
                                           "rounded gothic type. Light theme.",
        "fonts": {"ui": "maru", "display": "maru", "guide": "maru", "guide_display": "maru", "clock": "maru"},
        "c": {"bg": "#e9ecf1", "head1": "#ffffff", "head2": "#eef0f4", "panel": "#ffffff", "panel2": "#f1f3f6",
              "line": "#cfd5de", "input": "#ffffff", "page": "#eef0f4", "text": "#1c1f26", "muted": "#5d6675",
              "accent": "#e60033", "accent2": "#0068b7", "on_accent": "#ffffff", "now": "#e60033",
              "chan": "#1d2a44", "chan_text": "#ffffff", "num": "#ffd400", "cells": ["#ffffff", "#f7f8fa"],
              "filler": "#e2e5ea", "cell_border": "#c3cad5", "cell_text": "#1c1f26", "timebar": "#e60033",
              "timebar_text": "#ffffff", "spot_bg": "#ffffff", "spot_border": "#e60033", "track": "#e5e7eb",
              "brand": "#1d2a44"},
        "cell": "epg", "radius": 3, "gap": 3, "deco": "tokyo", "light": True, "genre_colors": True,
    },
    "aero": {
        "name": "Frutiger Aero", "desc": "Y2K glossy sky blue, bubbles, glass buttons and fresh green. Light theme.",
        "fonts": {"ui": "nunito", "display": "nunito", "guide": "nunito", "guide_display": "nunito", "clock": "nunito"},
        "c": {"bg": "#cfeeff", "head1": "#5fb8f5", "head2": "#d4f0ff", "panel": "#ffffff", "panel2": "#e6f5ff",
              "line": "#a9d6f5", "input": "#ffffff", "page": "#dff3ff", "text": "#08324f", "muted": "#3f6f8f",
              "accent": "#35b335", "accent2": "#1e90ff", "on_accent": "#ffffff", "now": "#ff5a36",
              "chan": "#1e78c8", "chan_text": "#ffffff", "num": "#ffffff", "cells": ["#ffffff", "#eef8ff"],
              "filler": "#d3ecfb", "cell_border": "#7cc4f2", "cell_text": "#08324f", "timebar": "#2a8fe0",
              "timebar_text": "#ffffff", "spot_bg": "#f4fbff", "spot_border": "#7cc4f2", "track": "#cfe9fb",
              "brand": "#0a3d66"},
        "cell": "gloss", "radius": 12, "gap": 5, "deco": "bubbles", "light": True,
    },
    "phosphor": {
        "name": "Green Phosphor", "desc": "Monochrome CRT terminal with scanlines and glowing green text.",
        "fonts": {"ui": "sharetech", "display": "vt323", "guide": "sharetech", "guide_display": "vt323",
                  "clock": "vt323"},
        "c": {"bg": "#020a03", "head1": "#05200b", "head2": "#020a03", "panel": "#031006", "panel2": "#062010",
              "line": "#0f4d1f", "input": "#010702", "page": "#010702", "text": "#7dff9a", "muted": "#3fbf5f",
              "accent": "#b8ffc9", "accent2": "#33ff66", "on_accent": "#021006", "now": "#ffb000",
              "chan": "#031406", "chan_text": "#7dff9a", "num": "#b8ffc9", "cells": ["#052611", "#041d0d"],
              "filler": "#031508", "cell_border": "#33ff66", "cell_text": "#7dff9a", "timebar": "#062010",
              "timebar_text": "#7dff9a", "spot_bg": "#020a03", "spot_border": "#33ff66", "track": "#0a3016",
              "brand": "#33ff66"},
        "cell": "outline", "radius": 0, "gap": 4, "deco": "crt", "body": "scanlines", "glow": True, "upper": True,
    },
    "atomic": {
        "name": "Atomic Age", "desc": "1950s space-age: teal, mustard and coral with starbursts and boomerangs.",
        "fonts": {"ui": "josefin", "display": "atomic", "guide": "josefin", "guide_display": "atomic",
                  "clock": "atomic"},
        "c": {"bg": "#10302f", "head1": "#1f5450", "head2": "#10302f", "panel": "#133836", "panel2": "#1a4542",
              "line": "#2e6b66", "input": "#0d2725", "page": "#0d2826", "text": "#fbf1dc", "muted": "#cfe3d8",
              "accent": "#f2c14e", "accent2": "#e76f51", "on_accent": "#10302f", "now": "#e76f51",
              "chan": "#0d2725", "chan_text": "#fbf1dc", "num": "#f2c14e", "cells": ["#2a7f75", "#3a6f8f", "#b0563c"],
              "filler": "#1a4542", "cell_border": "#f2c14e", "cell_text": "#fbf1dc", "timebar": "#f2c14e",
              "timebar_text": "#10302f", "spot_bg": "#0d2725", "spot_border": "#f2c14e", "track": "#24524e"},
        "cell": "round", "radius": 24, "gap": 5, "deco": "starburst",
    },
    "arcade": {
        "name": "8-Bit Arcade", "desc": "Pixel borders, chunky console colours and a starfield.",
        "fonts": {"ui": "vt323", "display": "pressstart", "guide": "vt323", "guide_display": "pressstart",
                  "clock": "pressstart"},
        "c": {"bg": "#0d0d1a", "head1": "#1b1b3a", "head2": "#0d0d1a", "panel": "#14142b", "panel2": "#1d1d3d",
              "line": "#3a3a7a", "input": "#0a0a16", "page": "#0a0a16", "text": "#ffffff", "muted": "#9bbcff",
              "accent": "#f8b800", "accent2": "#3cbcfc", "on_accent": "#000000", "now": "#f83800",
              "chan": "#24188c", "chan_text": "#ffffff", "num": "#f8b800", "cells": ["#0058f8", "#6844fc"],
              "filler": "#503000", "cell_border": "#000000", "cell_text": "#ffffff", "timebar": "#f83800",
              "timebar_text": "#ffffff", "spot_bg": "#000000", "spot_border": "#fcfcfc", "track": "#24188c"},
        "cell": "pixel", "radius": 0, "gap": 4, "deco": "pixel", "upper": True,
    },
}

GENRE_COLORS = [  # Japanese-EPG style genre tints (tokyo theme)
    (("anim", "anime", "kids", "children", "family"), "#ffe3ee"),
    (("news", "documentary", "history", "biography"), "#e1f5e1"),
    (("drama", "romance", "crime", "mystery"), "#e2efff"),
    (("comedy", "sitcom", "variety", "reality", "game"), "#fff0dc"),
    (("action", "adventure", "science fiction", "sci-fi", "fantasy", "thriller", "horror", "western", "war"), "#fff5c7"),
    (("music", "musical"), "#f1e6ff"),
    (("sport",), "#dff6f6"),
]


def rgb(h, default=(0, 0, 0)):
    try:
        h = h.lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return default


def mix(a, b, t):
    return tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3))


# ------------------------------------------------------------------ custom themes (theme builder)

CUSTOM = {}          # id -> normalized spec, loaded from config.json by the Store
COLOR_KEYS = ["bg", "head1", "head2", "page", "panel", "panel2", "line", "input", "text", "muted", "accent", "accent2",
              "on_accent", "now", "chan", "chan_text", "num", "filler", "cell_border", "cell_text", "timebar",
              "timebar_text", "spot_bg", "spot_border", "track"]
CELL_STYLES = ["flat", "bevel", "round", "cut", "deco", "chunky", "glow", "epg", "gloss", "outline", "pixel"]
PAGE_STYLES = ["soft", "square", "chunky", "glow", "glass"]
PAGE_PATTERNS = ["none", "grid", "dots", "scanlines", "stripes"]
FONT_ROLES = ["ui", "display", "guide", "guide_display", "clock"]
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _color(v, default):
    v = str(v or "").strip()
    if re.fullmatch(r"#?[0-9a-fA-F]{6}", v):
        return ("#" + v.lstrip("#")).lower()
    return default


def normalize(data, tid=None):
    """Clean up a theme sent by the theme builder. Anything missing comes from its 'base' theme."""
    data = data or {}
    base_id = data.get("base") if data.get("base") in THEMES else DEFAULT_THEME
    base = THEMES[base_id]
    bc = base["c"]
    c_in = data.get("c") or {}
    c = {k: _color(c_in.get(k), bc.get(k, bc["bg"]) if isinstance(bc.get(k, ""), str) and str(bc.get(k, "")).startswith("#")
                   else bc["text"]) for k in COLOR_KEYS}
    cells = [_color(x, "") for x in (c_in.get("cells") or bc["cells"])][:4]
    c["cells"] = [x for x in cells if x] or list(bc["cells"])
    brand = c_in.get("brand", bc.get("brand", ""))
    if brand not in ("", "text"):
        brand = _color(brand, "")
    if brand:
        c["brand"] = brand
    f_in = data.get("fonts") or {}
    fonts = {r: (f_in.get(r) if fontlib.get(f_in.get(r) or "") else base["fonts"].get(r, "system")) for r in FONT_ROLES}

    def num(k, lo, hi, d):
        try:
            return int(max(lo, min(hi, float(data.get(k, d)))))
        except (TypeError, ValueError):
            return d
    return {
        "id": tid or data.get("id") or "", "base": base_id, "custom": True,
        "name": (str(data.get("name") or "My theme").strip()[:40]) or "My theme",
        "desc": str(data.get("desc") or "").strip()[:160],
        "fonts": fonts, "c": c,
        "cell": data.get("cell") if data.get("cell") in CELL_STYLES else base.get("cell", "flat"),
        "radius": num("radius", 0, 30, base.get("radius", 0)), "gap": num("gap", 0, 12, base.get("gap", 3)),
        "deco": data.get("deco") if data.get("deco") in DECOS or data.get("deco") == "none" else base.get("deco", "none"),
        "body": "scanlines" if data.get("body") == "scanlines" else "",
        "glow": bool(data.get("glow")), "upper": bool(data.get("upper")), "light": bool(data.get("light")),
        "genre_colors": bool(data.get("genre_colors")),
        "page_style": data.get("page_style") if data.get("page_style") in PAGE_STYLES else "soft",
        "page_pattern": data.get("page_pattern") if data.get("page_pattern") in PAGE_PATTERNS else "none",
    }


def builtin_spec(tid):
    """A built-in theme in the builder's format (to start a new theme from)."""
    b = THEMES.get(tid) or THEMES[DEFAULT_THEME]
    d = {k: b.get(k) for k in ("cell", "radius", "gap", "deco", "body", "glow", "upper", "light", "genre_colors")}
    d.update(base=tid if tid in THEMES else DEFAULT_THEME, name=b["name"] + " (copy)", desc=b["desc"],
             fonts=dict(b["fonts"]), c=dict(b["c"], page=b["c"].get("page", b["c"]["bg"])))
    return normalize(d)


def set_custom(specs):
    CUSTOM.clear()
    for sp in specs or []:
        if sp.get("id"):
            CUSTOM[sp["id"]] = sp


class Theme:
    """A resolved theme: colours as RGB tuples plus font ids."""

    def __init__(self, tid=None, spec=None):
        if spec is not None:
            self.id = spec.get("id") or "preview"
            self.spec = spec
        elif tid in THEMES:
            self.id, self.spec = tid, THEMES[tid]
        elif tid in CUSTOM:
            self.id, self.spec = tid, CUSTOM[tid]
        else:
            self.id, self.spec = DEFAULT_THEME, THEMES[DEFAULT_THEME]
        c = self.spec["c"]
        self.key = self.id + "-" + hashlib.md5(json.dumps(self.spec, sort_keys=True).encode()).hexdigest()[:10]
        self.hex = c
        self.c = {k: (rgb(v) if isinstance(v, str) and v.startswith("#") else v) for k, v in c.items() if k != "cells"}
        self.cells = [rgb(x) for x in c["cells"]]
        self.fonts = self.spec["fonts"]
        self.cell = self.spec.get("cell", "flat")
        self.radius = self.spec.get("radius", 0)
        self.gap = self.spec.get("gap", 3)
        self.deco = self.spec.get("deco", "none")
        self.body = self.spec.get("body", "")
        self.glow = self.spec.get("glow", False)
        self.upper = self.spec.get("upper", False)
        self.light = self.spec.get("light", False)
        self.genre_colors = self.spec.get("genre_colors", False)
        self.name = self.spec["name"]

    def font(self, role):
        return self.fonts.get(role) or "system"

    def cell_fill(self, i, item=None):
        if self.genre_colors and item:
            genres = " ".join(item.get("genres") or []).lower()
            for keys, col in GENRE_COLORS:
                if any(k in genres for k in keys):
                    return rgb(col)
        return self.cells[i % len(self.cells)]


def get(tid):
    return Theme(tid)


def public_list():
    return [{"id": k, "name": v["name"], "desc": v["desc"], "light": v.get("light", False), "custom": bool(v.get("custom")),
             "swatch": [v["c"]["bg"], v["c"]["head1"], v["c"]["cells"][0], v["c"]["accent"], v["c"]["accent2"]],
             "fonts": v["fonts"]} for k, v in list(THEMES.items()) + list(CUSTOM.items())]


# ------------------------------------------------------------------ drawing helpers

def gradient(W, H, top, bottom):
    base = Image.new("RGB", (1, 256))
    for y in range(256):
        a = y / 255
        base.putpixel((0, y), tuple(int(top[i] * (1 - a) + bottom[i] * a) for i in range(3)))
    return base.resize((max(1, int(W)), max(1, int(H))))


def _layer(img):
    return Image.new("RGBA", img.size, (0, 0, 0, 0))


def _comp(img, layer):
    img.alpha_composite(layer)


def background(T, W, H, s, kind="header"):
    """Header / slate background with the theme's decoration (RGBA)."""
    img = gradient(W, H, T.c["head1"], T.c["head2"]).convert("RGBA")
    fn = DECOS.get(T.deco)
    if fn:
        fn(img, T, s, kind)
    return img


def scanlines(img, s, alpha=40, step=3):
    L = _layer(img)
    d = ImageDraw.Draw(L)
    st = max(2, int(step * s))
    for y in range(0, img.size[1], st):
        d.line((0, y, img.size[0], y), fill=(0, 0, 0, alpha))
    _comp(img, L)


def _stripes(img, T, s, kind):
    W, H = img.size
    L = _layer(img)
    d = ImageDraw.Draw(L)
    for x in range(-H, W, int(60 * s)):
        d.line((x, H, x + H, 0), fill=(255, 255, 255, 12), width=max(1, int(18 * s)))
    _comp(img, L)


def _vhs(img, T, s, kind):
    W, H = img.size
    L = _layer(img)
    d = ImageDraw.Draw(L)
    cols = [(255, 64, 64), (255, 160, 32), (255, 255, 85), (64, 220, 96), (64, 160, 255)]
    bh = max(2, int(7 * s))
    y0 = H - bh * len(cols) - int(10 * s)
    for i, c in enumerate(cols):
        d.rectangle((0, y0 + i * bh, W * (0.42 if kind == "header" else 1), y0 + (i + 1) * bh - 1), fill=c + (200,))
    _comp(img, L)
    scanlines(img, s, 34)


def _rainbow70s(img, T, s, kind):
    W, H = img.size
    L = _layer(img)
    d = ImageDraw.Draw(L)
    cols = [(242, 177, 52), (224, 98, 42), (176, 64, 30), (110, 52, 24)]
    band = 26 * s
    cx, cy = (W * 0.47, H * 1.05) if kind == "header" else (W * 0.98, H * 1.02)
    r0 = (H * 0.55) if kind == "header" else H * 0.45
    for i, c in enumerate(cols):
        r = r0 + (len(cols) - i) * band
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=c + (235,))
    r = r0
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=T.c["head2"] + (255,))
    _comp(img, L)


def _circuit(img, T, s, kind):
    W, H = img.size
    acc = T.c["accent"]
    L = _layer(img)
    d = ImageDraw.Draw(L)
    step = int(32 * s)
    for x in range(0, W, step):
        d.line((x, 0, x, H), fill=acc + (14,))
    for y in range(0, H, step):
        d.line((0, y, W, y), fill=acc + (14,))
    rnd = random.Random(7)
    for _ in range(9):
        x, y = rnd.randrange(0, W // step) * step, rnd.randrange(0, H // step + 1) * step
        pts = [(x, y)]
        for _ in range(4):
            if rnd.random() < .5:
                x += rnd.choice((-1, 1)) * step * rnd.randint(1, 4)
            else:
                y += rnd.choice((-1, 1)) * step * rnd.randint(1, 2)
            pts.append((x, y))
        d.line(pts, fill=acc + (60,), width=max(1, int(2 * s)))
        ex, ey = pts[-1]
        r = 4 * s
        d.ellipse((ex - r, ey - r, ex + r, ey + r), outline=acc + (150,), width=max(1, int(2 * s)))
    # corner brackets
    m, k = 10 * s, 36 * s
    w = max(2, int(3 * s))
    for (x, y, dx, dy) in ((m, m, 1, 1), (W - m, m, -1, 1), (m, H - m, 1, -1), (W - m, H - m, -1, -1)):
        d.line((x, y, x + dx * k, y), fill=acc + (220,), width=w)
        d.line((x, y, x, y + dy * k), fill=acc + (220,), width=w)
    _comp(img, L)


def _sunburst(img, T, s, kind):
    W, H = img.size
    gold = T.c["accent"]
    L = _layer(img)
    d = ImageDraw.Draw(L)
    cx, cy = (W * 0.22, H * 1.0) if kind == "header" else (W * 0.5, H * 1.05)
    R = max(W, H) * 1.2
    n = 44
    for i in range(n):
        if i % 2:
            continue
        a0, a1 = math.pi + i * math.pi / n, math.pi + (i + 1) * math.pi / n
        d.polygon([(cx, cy), (cx + R * math.cos(a0), cy + R * math.sin(a0)), (cx + R * math.cos(a1), cy + R * math.sin(a1))],
                  fill=gold + (16,))
    # stepped double frame
    m = 10 * s
    for k, a in ((0, 200), (7 * s, 110)):
        d.rectangle((m + k, m + k, W - m - k, H - m - k), outline=gold + (a,), width=max(1, int(2 * s)))
    step = 18 * s
    for i in range(3):   # stepped corners
        o = m + 14 * s + i * step / 2
        for (x, y, dx, dy) in ((o, o, 1, 1), (W - o, o, -1, 1)):
            d.line((x, y + dy * (step - i * 4 * s), x, y, x + dx * (step - i * 4 * s), y), fill=gold + (150,),
                   width=max(1, int(2 * s)))
    _comp(img, L)


def _squiggle(d, x, y, w, amp, color, width):
    pts = [(x + t, y + amp * math.sin(t / max(1, w) * math.pi * 4)) for t in range(0, int(w), 3)]
    d.line(pts, fill=color, width=width, joint="curve")


def _memphis(img, T, s, kind):
    W, H = img.size
    ink = T.c["cell_border"] + (255,)
    rnd = random.Random(42 if kind == "header" else 43)
    pal = list(T.cells) + [T.c["accent"], T.c["accent2"]]
    L = _layer(img)
    d = ImageDraw.Draw(L)
    lw = max(2, int(3 * s))
    # big blob
    bx, by = (W * 0.29, H * 0.3) if kind == "header" else (W * 0.78, H * 0.2)
    d.ellipse((bx, by, bx + 170 * s, by + 170 * s), fill=pal[0] + (255,))
    zones = [(0.28, 0.43)] if kind == "header" else [(0.0, 1.0)]
    for _ in range(16 if kind == "header" else 26):
        z = zones[0]
        x = rnd.uniform(z[0], z[1]) * W
        y = rnd.uniform(0.05, 0.95) * H
        c = rnd.choice(pal) + (255,)
        kind_ = rnd.choice(("circle", "tri", "squiggle", "dots", "ring", "half"))
        r = rnd.uniform(10, 26) * s
        if kind_ == "circle":
            d.ellipse((x - r, y - r, x + r, y + r), fill=c, outline=ink, width=lw)
        elif kind_ == "ring":
            d.ellipse((x - r, y - r, x + r, y + r), outline=c, width=max(3, int(6 * s)))
        elif kind_ == "tri":
            d.polygon([(x, y - r), (x + r, y + r), (x - r, y + r)], fill=c, outline=ink, width=lw)
        elif kind_ == "squiggle":
            _squiggle(d, x, y, 70 * s, 8 * s, ink, lw)
        elif kind_ == "half":
            d.pieslice((x - r, y - r, x + r, y + r), 180, 360, fill=c, outline=ink, width=lw)
        else:
            for i in range(3):
                for j in range(3):
                    rr = 2.5 * s
                    d.ellipse((x + i * 10 * s - rr, y + j * 10 * s - rr, x + i * 10 * s + rr, y + j * 10 * s + rr), fill=ink)
    _comp(img, L)


def _outrun(img, T, s, kind):
    W, H = img.size
    L = _layer(img)
    d = ImageDraw.Draw(L)
    horizon = H * (0.84 if kind == "header" else 0.62)
    cx = W * (0.4 if kind == "header" else 0.82)
    r = (H * 0.42) if kind == "header" else H * 0.3
    # sun: vertical gradient yellow -> pink, cut by horizontal gaps
    sun = gradient(int(2 * r), int(2 * r), (255, 211, 25), (255, 42, 109)).convert("RGBA")
    mask = Image.new("L", sun.size, 0)
    md = ImageDraw.Draw(mask)
    md.ellipse((0, 0, sun.size[0] - 1, sun.size[1] - 1), fill=255)
    for i in range(7):
        y = sun.size[1] * (0.52 + i * 0.07)
        md.rectangle((0, y, sun.size[0], y + (2 + i * 1.6) * s), fill=0)
    sun.putalpha(mask)
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((cx - r * 1.25, horizon - r * 1.25, cx + r * 1.25, horizon + r * 0.6), fill=(255, 42, 109, 70))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(30 * s)))
    img.alpha_composite(sun, (int(cx - r), int(horizon - r * 1.05)))
    # ground + perspective grid
    d.rectangle((0, horizon, W, H), fill=(18, 4, 31, 235))
    pink = (255, 42, 109)
    for i in range(1, 9):
        y = horizon + (H - horizon) * (i / 8) ** 1.8
        d.line((0, y, W, y), fill=pink + (200,), width=max(1, int(2 * s)))
    for i in range(-14, 15):
        d.line((cx + i * 18 * s, horizon, cx + i * 160 * s, H), fill=pink + (170,), width=max(1, int(2 * s)))
    d.line((0, horizon, W, horizon), fill=(5, 217, 232, 255), width=max(2, int(3 * s)))
    _comp(img, L)


def _teletext(img, T, s, kind):
    W, H = img.size
    L = _layer(img)
    d = ImageDraw.Draw(L)
    cols = [(255, 0, 0), (0, 255, 0), (255, 255, 0), (0, 0, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255)]
    rnd = random.Random(100)
    cw, chh = 12 * s, 9 * s
    y0 = H - 4 * chh - 10 * s
    width = W * (0.42 if kind == "header" else 1)
    x = 0
    while x < width:          # mosaic "sixel" band
        c = rnd.choice(cols)
        for j in range(4):
            if rnd.random() < 0.55:
                d.rectangle((x, y0 + j * chh, x + cw - 1, y0 + (j + 1) * chh - 1), fill=c + (255,))
        x += cw
    _comp(img, L)


def _tokyo(img, T, s, kind):
    W, H = img.size
    red = T.c["accent"]
    L = _layer(img)
    d = ImageDraw.Draw(L)
    for x in range(0, W, max(4, int(8 * s))):      # fine pinstripes
        d.line((x, 0, x, H), fill=(0, 0, 0, 7))
    cx, cy, r = (W * 0.37, H * 0.45, 70 * s) if kind == "header" else (W * 0.82, H * 0.3, 150 * s)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=red + (40,))
    d.rectangle((0, H - 8 * s, W, H), fill=red + (255,))
    d.rectangle((0, H - 12 * s, W, H - 10 * s), fill=T.c["accent2"] + (255,))
    _comp(img, L)


def _bubbles(img, T, s, kind):
    W, H = img.size
    rnd = random.Random(5)
    L = _layer(img)
    d = ImageDraw.Draw(L)
    # green grass swoosh
    pts = [(0, H)] + [(x, H - (22 + 16 * math.sin(x / W * math.pi * 1.5)) * s) for x in range(0, W + 1, 16)] + [(W, H)]
    d.polygon(pts, fill=(80, 190, 60, 230))
    pts2 = [(0, H)] + [(x, H - (10 + 12 * math.sin(x / W * math.pi * 2.3 + 1)) * s) for x in range(0, W + 1, 16)] + [(W, H)]
    d.polygon(pts2, fill=(130, 220, 90, 255))
    for _ in range(16 if kind == "header" else 26):
        r = rnd.uniform(6, 30) * s
        x, y = rnd.uniform(0, W * (0.5 if kind == "header" else 1)), rnd.uniform(0, H * 0.85)
        d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, 40), outline=(255, 255, 255, 170), width=max(1, int(2 * s)))
        d.ellipse((x - r * .55, y - r * .7, x - r * .05, y - r * .3), fill=(255, 255, 255, 190))
    # lens glare
    g = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(g)
    gd.ellipse((W * 0.02, -H * 0.4, W * 0.5, H * 0.5), fill=(255, 255, 255, 70))
    img.alpha_composite(g.filter(ImageFilter.GaussianBlur(40 * s)))
    _comp(img, L)


def _crt(img, T, s, kind):
    W, H = img.size
    scanlines(img, s, 70, 3)
    v = Image.new("L", (64, 36), 0)
    vd = ImageDraw.Draw(v)
    vd.ellipse((-14, -10, 78, 46), fill=255)
    v = v.filter(ImageFilter.GaussianBlur(8)).resize((W, H))
    dark = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    dark.putalpha(v.point(lambda a: int((255 - a) * 0.55)))
    img.alpha_composite(dark)


def _star(d, x, y, r, color, points=4, inner=0.25, rot=0):
    pts = []
    for i in range(points * 2):
        a = rot + i * math.pi / points
        rr = r if i % 2 == 0 else r * inner
        pts.append((x + rr * math.cos(a), y + rr * math.sin(a)))
    d.polygon(pts, fill=color)


def _starburst(img, T, s, kind):
    W, H = img.size
    rnd = random.Random(1957)
    L = _layer(img)
    d = ImageDraw.Draw(L)
    mus, cor, cream = T.c["accent"], T.c["accent2"], T.c["text"]
    zone = 0.5 if kind == "header" else 1.0
    # orbit ellipses
    cx, cy = W * zone * 0.82, H * 0.5
    for k in range(3):
        box = (cx - 120 * s, cy - 36 * s, cx + 120 * s, cy + 36 * s)
        el = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(el).ellipse(box, outline=cream + (60,), width=max(1, int(2 * s)))
        L.alpha_composite(el.rotate(k * 60, center=(cx, cy)))
    d.ellipse((cx - 10 * s, cy - 10 * s, cx + 10 * s, cy + 10 * s), fill=cor + (220,))
    for _ in range(12 if kind == "header" else 22):
        x, y = rnd.uniform(0, W * zone), rnd.uniform(0, H)
        r = rnd.uniform(6, 20) * s
        c = rnd.choice((mus, cream, cor))
        _star(d, x, y, r, c + (rnd.randint(90, 200),), points=rnd.choice((4, 4, 8)), inner=0.22, rot=rnd.random())
    # boomerangs
    for _ in range(3):
        x, y = rnd.uniform(0.05, zone * 0.9) * W, rnd.uniform(0.15, 0.85) * H
        c = rnd.choice((mus, cor)) + (120,)
        d.polygon([(x, y), (x + 40 * s, y - 14 * s), (x + 80 * s, y + 10 * s), (x + 40 * s, y - 2 * s)], fill=c)
    _comp(img, L)


def _pixel(img, T, s, kind):
    W, H = img.size
    rnd = random.Random(8)
    L = _layer(img)
    d = ImageDraw.Draw(L)
    p = max(2, int(4 * s))
    for _ in range(70 if kind == "header" else 140):
        x = rnd.randrange(0, int(W * (0.5 if kind == "header" else 1)) // p) * p
        y = rnd.randrange(0, int(H * 0.8) // p) * p
        c = rnd.choice(((255, 255, 255), (60, 188, 252), (248, 184, 0)))
        d.rectangle((x, y, x + p - 1, y + p - 1), fill=c + (rnd.randint(120, 255),))
    # blocky mountains
    base = H
    x = 0
    rnd2 = random.Random(3)
    h = 0
    while x < W:
        h = max(1, min(int(H * 0.16 / p), h + rnd2.choice((-1, 0, 1, 1)))) if h else rnd2.randint(2, 5)
        d.rectangle((x, base - h * p, x + p * 2 - 1, base), fill=(36, 24, 140, 255))
        d.rectangle((x, base - h * p, x + p * 2 - 1, base - h * p + p - 1), fill=(104, 68, 252, 255))
        x += p * 2
    _comp(img, L)


DECOS = {"stripes": _stripes, "vhs": _vhs, "rainbow70s": _rainbow70s, "circuit": _circuit, "sunburst": _sunburst,
         "memphis": _memphis, "outrun": _outrun, "teletext": _teletext, "tokyo": _tokyo, "bubbles": _bubbles,
         "crt": _crt, "starburst": _starburst, "pixel": _pixel}


# ------------------------------------------------------------------ programme cells

def draw_cell(img, d, box, fill, T, s, current=False):
    """Draws one guide cell in the theme's style. Text is drawn separately. Boxes too small for the style's
    borders and insets (a short break can be only a few pixels wide) are drawn as plain blocks."""
    x0, y0, x1, y1 = box
    inset = {"pixel": 3 * max(2, int(4 * s)), "chunky": 2 * max(2, int(4 * s)), "deco": 3 * max(3, int(4 * s)),
             "gloss": 2 * int(T.radius * s) + 8, "round": 4, "glow": 4, "cut": 6, "bevel": 2 * max(2, int(3 * s)) + 2}
    if x1 - x0 < inset.get(T.cell, 2) or y1 - y0 < inset.get(T.cell, 2):
        d.rectangle((x0, y0, max(x0, x1), max(y0, y1)), fill=fill)
        return
    try:
        _draw_cell(img, d, box, fill, T, s, current)
    except ValueError:      # never let one odd box take the guide channel down
        d.rectangle((x0, y0, max(x0, x1), max(y0, y1)), fill=fill)


def _draw_cell(img, d, box, fill, T, s, current=False):
    x0, y0, x1, y1 = box
    border = T.c["cell_border"]
    st, r = T.cell, int(T.radius * s)
    w1 = max(1, int(1 * s))
    if st == "flat":
        d.rectangle(box, fill=fill)
        d.line((x0, y0, x1, y0), fill=border, width=1)
    elif st == "bevel":
        d.rectangle(box, fill=fill)
        hi, lo = mix(fill, (255, 255, 255), 0.45), mix(fill, (0, 0, 0), 0.5)
        b = max(2, int(3 * s))
        d.polygon([(x0, y0), (x1, y0), (x1 - b, y0 + b), (x0 + b, y0 + b), (x0 + b, y1 - b), (x0, y1)], fill=hi)
        d.polygon([(x1, y1), (x0, y1), (x0 + b, y1 - b), (x1 - b, y1 - b), (x1 - b, y0 + b), (x1, y0)], fill=lo)
    elif st == "round":
        d.rounded_rectangle(box, radius=min(r, int((y1 - y0) / 2)), fill=fill)
    elif st == "cut":
        c = min(14 * s, (x1 - x0) / 3)
        d.polygon([(x0 + c, y0), (x1, y0), (x1, y1 - c), (x1 - c, y1), (x0, y1), (x0, y0 + c)], fill=fill,
                  outline=mix(border, fill, 0.55))
        d.line((x0 + c, y0, x0 + min(x1 - x0, 60 * s), y0), fill=border, width=max(2, int(2 * s)))
    elif st == "deco":
        d.rectangle(box, fill=fill)
        d.rectangle(box, outline=mix(border, fill, 0.35), width=w1)
        k = max(3, int(4 * s))
        if x1 - x0 > 3 * k:
            d.rectangle((x0 + k, y0 + k, x1 - k, y1 - k), outline=mix(border, fill, 0.7), width=1)
    elif st == "chunky":
        off = max(2, int(4 * s))
        d.rounded_rectangle((x0 + off, y0 + off, x1, y1), radius=r, fill=border)
        d.rounded_rectangle((x0, y0, x1 - off, y1 - off), radius=r, fill=fill, outline=border, width=max(2, int(2.5 * s)))
    elif st == "glow":
        d.rounded_rectangle(box, radius=r, fill=fill, outline=border, width=max(1, int(2 * s)))
    elif st == "epg":
        d.rectangle(box, fill=fill, outline=border, width=1)
        if current:
            d.rectangle((x0, y0, x0 + max(3, int(5 * s)), y1), fill=T.c["accent"])
    elif st == "gloss":
        d.rounded_rectangle(box, radius=r, fill=fill, outline=border, width=max(1, int(1.5 * s)))
        hl = mix(fill, (255, 255, 255), 0.7 if sum(fill) > 540 else 0.2)
        mid = y0 + (y1 - y0) * 0.45
        if x1 - x0 > 2 * r + 4:
            d.rounded_rectangle((x0 + 3 * s, y0 + 3 * s, x1 - 3 * s, mid), radius=max(1, r - 3), fill=hl)
    elif st == "outline":
        d.rectangle(box, fill=fill, outline=border, width=w1)
    elif st == "pixel":
        p = max(2, int(4 * s))
        d.rectangle((x0 + p, y0, x1 - p, y1), fill=(0, 0, 0))
        d.rectangle((x0, y0 + p, x1, y1 - p), fill=(0, 0, 0))
        d.rectangle((x0 + p, y0 + p, x1 - p, y1 - p), fill=fill)
        d.rectangle((x0 + p, y0 + p, x1 - p, y0 + 2 * p - 1), fill=mix(fill, (255, 255, 255), 0.35))
    else:
        d.rectangle(box, fill=fill)
    if current and st not in ("epg",):
        d.line((x0, y1 - max(2, int(3 * s)), x1, y1 - max(2, int(3 * s))), fill=T.c["accent"], width=max(2, int(3 * s)))


def text_glow(layer, s, color=None, radius=3.0, strength=2):
    """Returns layer composited over its own blurred copy (neon glow)."""
    g = layer.filter(ImageFilter.GaussianBlur(radius * s))
    out = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    for _ in range(strength):
        out.alpha_composite(g)
    out.alpha_composite(layer)
    return out


# ------------------------------------------------------------------ web (admin / TV / remote)

EXTRA_CSS = {
    "retro_cable": """
body { background-image: repeating-linear-gradient(0deg, #0000 0 2px, #00000033 2px 3px); }
header.top { background: linear-gradient(180deg, #2a2ad0, #000058) !important; border-bottom: 3px solid #ff5555; }
.card, .btn, .eguide .prog { box-shadow: inset 2px 2px 0 #ffffff40, inset -2px -2px 0 #00000080; border-radius: 0 !important; }
h1, h2, .brand { text-transform: uppercase; letter-spacing: .06em; }
#banner, #controls, #guide, .np, .rbtn, .rocker, .keys button, #castpick .box { border-radius: 0 !important; box-shadow: inset 3px 3px 0 #ffffff33, inset -3px -3px 0 #0008; }
""",
    "groovy70s": """
header.top { background: linear-gradient(180deg, #f2b134 0 6px, #e0622a 6px 12px, #b0401e 12px 18px, #5c3419 18px) !important; padding-top: 26px !important; }
.card { border-radius: 22px; } .btn { border-radius: 99px; }
h1 { font-style: italic; }
#banner, #controls, #guide, .np { border-radius: 26px !important; }
""",
    "futuristic": """
body { background-image: linear-gradient(#00e5ff0a 1px, transparent 1px), linear-gradient(90deg, #00e5ff0a 1px, transparent 1px); background-size: 32px 32px; }
.card { clip-path: polygon(14px 0, 100% 0, 100% calc(100% - 14px), calc(100% - 14px) 100%, 0 100%, 0 14px); border-color: #00e5ff55; box-shadow: inset 0 0 30px #00e5ff10; }
.btn { border-color: #00e5ff66; box-shadow: 0 0 10px #00e5ff22; }
.btn.primary { box-shadow: 0 0 16px #00e5ff88; }
h1, h2, .brand, #banner .num, .gi .n { text-shadow: 0 0 12px #00e5ff99; letter-spacing: .08em; }
#banner, #controls, #guide, .np, .volrow, .rocker { border-color: #00e5ff88 !important; box-shadow: 0 0 24px #00e5ff33, inset 0 0 24px #00e5ff14 !important; }
""",
    "artdeco": """
header.top { border-bottom: 2px solid #d4af37; box-shadow: 0 4px 0 #0c0b09, 0 5px 0 #d4af3788; }
.card { border: 1px solid #d4af37; outline: 1px solid #d4af3755; outline-offset: -6px; border-radius: 0; }
.btn { border-radius: 0; border-color: #d4af37; letter-spacing: .08em; text-transform: uppercase; font-size: 13px; }
h1, h2, h3, .brand { text-transform: uppercase; letter-spacing: .14em; }
nav a { text-transform: uppercase; letter-spacing: .06em; font-size: 13px; }
h1 { text-align: left; border-bottom: 1px solid #d4af37; padding-bottom: 6px; }
#banner, #guide, .np, #castpick .box { border-radius: 0 !important; border: 1px solid #d4af37 !important; outline: 1px solid #d4af3766; outline-offset: -6px; }
""",
    "memphis": """
body { background-image: radial-gradient(#1e1b4b22 1.5px, transparent 1.5px); background-size: 22px 22px; }
header.top { background: #fff !important; border-bottom: 3px solid #1e1b4b; }
.card { border: 2.5px solid #1e1b4b; box-shadow: 6px 6px 0 #1e1b4b; border-radius: 18px; }
.btn { border: 2px solid #1e1b4b; box-shadow: 3px 3px 0 #1e1b4b; border-radius: 99px; }
.btn:active { transform: translate(2px, 2px); box-shadow: 1px 1px 0 #1e1b4b; }
.btn.primary { background: #ff6b6b; color: #fff; }
input[type=text], input[type=number], input[type=password], input[type=url], select, textarea { border: 2px solid #1e1b4b; }
#banner, #controls, #guide, .np, .volrow, #castpick .box { border: 2.5px solid #1e1b4b !important; box-shadow: 6px 6px 0 #1e1b4b !important; }
""",
    "synthwave": """
body { background: linear-gradient(180deg, #12041f 0%, #2a0845 55%, #12041f 100%) fixed; }
header.top { background: linear-gradient(90deg, #ff2a6d33, #12041f 40%, #05d9e822) !important; border-bottom: 2px solid #ff2a6d; box-shadow: 0 0 22px #ff2a6d66; }
h1, .brand { text-shadow: 0 0 14px #ff2a6d, 0 0 2px #fff; }
.card { border-color: #ff2a6d66; box-shadow: 0 0 22px #ff2a6d22; }
.btn.primary { background: linear-gradient(90deg, #ff2a6d, #05d9e8); color: #12041f; border: 0; }
#banner, #controls, #guide, .np, .volrow { border-color: #ff2a6d !important; box-shadow: 0 0 26px #ff2a6d55 !important; }
#banner .num, .gi .n { text-shadow: 0 0 12px #ffd319; }
""",
    "teletext": """
body { font-size: 20px !important; }
* { border-radius: 0 !important; }
header.top { background: #000 !important; border-bottom: 4px solid #0000ff; }
.card { border: 0; border-top: 6px solid #0000ff; }
h1 { background: #0000ff; color: #ffff00; padding: 4px 10px; display: inline-block; }
h2 { color: #00ffff; } h3 { color: #00ff00 !important; }
.btn { background: #00007a; border-color: #00ffff; color: #fff; }
.btn.primary { background: #ffff00; color: #000; }
""",
    "tokyo": """
header.top { background: #fff !important; border-bottom: 4px solid #e60033; box-shadow: 0 2px 0 #0068b7 inset; }
.card { box-shadow: 0 1px 3px #0001, 0 4px 14px #0000000d; border-radius: 6px; }
h1 { border-left: 6px solid #e60033; padding-left: 10px; }
#banner { background: #ffffffee !important; border-left: 8px solid #e60033 !important; }
#banner .num { color: #e60033 !important; }
""",
    "aero": """
body { background: linear-gradient(180deg, #8fd3ff 0%, #dff3ff 45%, #f4fff0 100%) fixed; }
header.top { background: linear-gradient(180deg, #ffffffcc, #bfe6ffcc) !important; backdrop-filter: blur(10px); border-bottom: 1px solid #ffffff; box-shadow: 0 2px 12px #1e90ff33; }
.card { background: linear-gradient(180deg, #ffffffee, #f0f9ffcc); border: 1px solid #ffffff; box-shadow: 0 6px 22px #1e90ff26, inset 0 1px 0 #fff; border-radius: 16px; backdrop-filter: blur(8px); }
.btn { background: linear-gradient(180deg, #ffffff, #d6efff 50%, #bfe4ff 51%, #e6f6ff); border-color: #8cc8f0; border-radius: 99px; color: #08324f; }
.btn.primary { background: linear-gradient(180deg, #a6f08a, #4cc33a 50%, #36a826 51%, #7ad85e); border-color: #2e8f22; color: #fff; text-shadow: 0 1px 1px #0005; }
#banner, #controls, .np, .volrow, #guide { background: linear-gradient(180deg, #ffffffee, #d9f0ffdd) !important; border: 1px solid #fff !important; box-shadow: 0 8px 30px #1e90ff44 !important; }
""",
    "phosphor": """
body { text-shadow: 0 0 6px #33ff6688; background-image: repeating-linear-gradient(0deg, #0000 0 2px, #00000066 2px 3px); }
* { border-radius: 0 !important; }
header.top { background: #020a03 !important; border-bottom: 1px dashed #33ff66; }
.card { border: 1px dashed #1f7a35; }
.btn { background: transparent; border: 1px solid #33ff66; color: #7dff9a; }
.btn.primary { background: #33ff66; color: #021006; text-shadow: none; }
img { filter: grayscale(1) sepia(1) hue-rotate(70deg) saturate(3) brightness(.9); }
""",
    "atomic": """
body { background-image: radial-gradient(circle at 20% 10%, #f2c14e18 0 2px, transparent 3px), radial-gradient(circle at 70% 60%, #e76f5118 0 2px, transparent 3px); background-size: 140px 140px, 90px 90px; }
header.top { background: linear-gradient(90deg, #1f5450, #10302f) !important; border-bottom: 4px solid #f2c14e; }
.card { border-radius: 28px 6px 28px 6px; border-color: #2e6b66; }
.btn { border-radius: 99px; }
.btn.primary { background: #e76f51; border-color: #e76f51; color: #fbf1dc; }
#banner, .np { border-radius: 40px 8px 40px 8px !important; }
""",
    "arcade": """
body { font-size: 19px !important; }
* { border-radius: 0 !important; }
.card, .btn, input, select, textarea { border-width: 3px !important; border-style: solid; box-shadow: 4px 4px 0 #000; }
.btn.primary { background: #f8b800; color: #000; border-color: #000; }
h1, h2, .brand, nav a { font-family: var(--font-display) !important; font-size: 13px !important; line-height: 1.8; }
h1 { font-size: 18px !important; color: #f8b800; }
#banner, #controls, #guide, .np { border: 4px solid #fcfcfc !important; box-shadow: 6px 6px 0 #000 !important; }
""",
}


def css(T, ui_font=None):
    """Theme stylesheet for the admin page, the TV page and the remote."""
    h = T.hex
    ui = ui_font if ui_font and ui_font != "theme" else T.font("ui")
    light = T.light

    def a(hexc, alpha):  # hex + alpha suffix
        return hexc + alpha

    tv_panel = h["panel2"] if not light else "#ffffff"
    v = {
        "--bg": h.get("page", h["bg"]), "--panel": h["panel"], "--panel2": h["panel2"], "--line": h["line"],
        "--text": h["text"], "--muted": h["muted"], "--accent": h["accent"], "--blue": h["accent2"],
        "--on-accent": h["on_accent"], "--red": h["now"], "--input": h["input"],
        "--head-bg": f"linear-gradient(90deg, {h['head1']}, {h.get('page', h['bg'])})",
        "--cell": h["cells"][0], "--cell2": h["cells"][1 % len(h["cells"])], "--cell-text": h["cell_text"],
        "--chan": h["chan"], "--chan-text": h["chan_text"], "--timebar": h["timebar"], "--timebar-text": h["timebar_text"],
        "--font": fontlib.css_family(ui), "--font-display": fontlib.css_family(T.font("display")),
        # TV page / remote
        "--yellow": h["accent"], "--sub": h["muted"], "--tvtext": h["text"],
        "--tvp": tv_panel, "--tvp-a": a(tv_panel, "e6"), "--tvh": h["head1"] if not light else h["panel2"],
        "--tvhi": a(h["accent2"], "4d" if light else "cc"), "--tvbg": a(h["bg"], "f2"),
        "--tvgrad": f"radial-gradient(circle at 50% 0%, {h['head1']}, {h['bg']} 70%)",
        "--tvbanner": f"linear-gradient(180deg, {a(h['head1'], 'ee')}, {a(h['bg'], 'ee')})",
    }
    root = ":root { " + " ".join(f"{k}: {val};" for k, val in v.items()) + f" color-scheme: {'light' if light else 'dark'}; }}"
    brand = h.get("brand")
    art = ""
    if light:      # the station artwork is white: darken it on light themes
        art = ".brandart { filter: brightness(0) saturate(100%) opacity(.85) !important; }"
    elif isinstance(brand, str) and brand.startswith("#"):
        art = f".brandart {{ filter: drop-shadow(0 0 6px {brand}88) !important; }}"
    base = art + """
body { font-family: var(--font) !important; }
h1, h2, .brand #station, #banner .num, .gi .n, #guide header > b, .np .ch, #power h1 { font-family: var(--font-display); }
"""
    extra = EXTRA_CSS.get(T.id, "") if not T.spec.get("custom") else (
        PAGE_STYLE_CSS.get(T.spec.get("page_style"), "") + PAGE_PATTERN_CSS.get(T.spec.get("page_pattern"), ""))
    return "\n".join([fontlib.font_face_css(), root, base, extra])


# page looks for custom themes, written only with the theme's own colours (CSS variables)
PAGE_STYLE_CSS = {
    "soft": "",
    "square": "* { border-radius: 0 !important; }\n",
    "chunky": """
.card { border: 2.5px solid var(--text); box-shadow: 6px 6px 0 var(--text); }
.btn { border: 2px solid var(--text); box-shadow: 3px 3px 0 var(--text); border-radius: 99px; }
#banner, #controls, #guide, .np, .volrow, #castpick .box { border: 2.5px solid var(--tvtext) !important; box-shadow: 6px 6px 0 var(--tvtext) !important; }
""",
    "glow": """
.card { border-color: color-mix(in srgb, var(--accent) 45%, transparent); box-shadow: 0 0 22px color-mix(in srgb, var(--accent) 18%, transparent); }
.btn.primary { box-shadow: 0 0 16px color-mix(in srgb, var(--accent) 60%, transparent); }
h1, h2, .brand { text-shadow: 0 0 12px color-mix(in srgb, var(--accent) 60%, transparent); }
#banner, #controls, #guide, .np, .volrow { border-color: var(--accent) !important; box-shadow: 0 0 26px color-mix(in srgb, var(--accent) 35%, transparent) !important; }
""",
    "glass": """
.card { background: color-mix(in srgb, var(--panel) 70%, transparent); backdrop-filter: blur(10px); border-color: color-mix(in srgb, var(--text) 18%, transparent); box-shadow: 0 8px 30px #0003; }
header.top { backdrop-filter: blur(10px); }
#banner, #controls, .np, .volrow { backdrop-filter: blur(12px); }
""",
}
PAGE_PATTERN_CSS = {
    "none": "",
    "grid": "body { background-image: linear-gradient(color-mix(in srgb, var(--accent) 6%, transparent) 1px, transparent 1px), linear-gradient(90deg, color-mix(in srgb, var(--accent) 6%, transparent) 1px, transparent 1px); background-size: 32px 32px; }\n",
    "dots": "body { background-image: radial-gradient(color-mix(in srgb, var(--text) 14%, transparent) 1.5px, transparent 1.5px); background-size: 22px 22px; }\n",
    "scanlines": "body { background-image: repeating-linear-gradient(0deg, #0000 0 2px, #00000040 2px 3px); }\n",
    "stripes": "body { background-image: repeating-linear-gradient(135deg, color-mix(in srgb, var(--accent) 5%, transparent) 0 14px, transparent 14px 28px); }\n",
}

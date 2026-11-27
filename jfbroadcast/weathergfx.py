"""Draws the Weather channel: themed screens (current conditions, next hours, 7 days, radar, sun & moon,
alerts), weather icons, charts and the frame around them. One frame a second, like the guide channel."""
import math
from datetime import datetime, timezone

from PIL import Image, ImageDraw, ImageFilter

from . import BRAND, branding, themes, weather
from .graphics import _Text, corner_logo, ellipsize, fmt_time, panel, readable, text_w, wrap

SLIDE_TITLES = {"current": "Current Conditions", "hourly": "Next 12 Hours", "daily": "7-Day Forecast",
                "radar_local": "Local Radar", "radar_regional": "Regional Radar", "radar_future": "Future Radar", "almanac": "Sun & Moon",
                "alerts": "Weather Alerts"}
SUN, MOON = (255, 201, 60), (250, 240, 200)
RAIN, SNOW, BOLT = (90, 170, 255), (235, 245, 255), (255, 220, 60)

# ------------------------------------------------------------------ icons

_icon_cache = {}


def _cloud(d, x, y, w, color, shade):
    """A cartoon cloud whose box starts at (x, y), w wide."""
    h = w * 0.5
    d.ellipse((x + w * 0.05, y + h * 0.35, x + w * 0.45, y + h * 1.0), fill=shade)
    d.ellipse((x + w * 0.22, y, x + w * 0.72, y + h * 0.95), fill=shade)
    d.ellipse((x + w * 0.5, y + h * 0.25, x + w * 0.95, y + h * 1.0), fill=shade)
    d.rounded_rectangle((x + w * 0.2, y + h * 0.55, x + w * 0.8, y + h * 1.0), radius=int(h * 0.2), fill=shade)
    o = w * 0.035                                                         # lighter top layer
    d.ellipse((x + w * 0.05 + o, y + h * 0.35 + o, x + w * 0.45 - o, y + h * 1.0 - o * 2), fill=color)
    d.ellipse((x + w * 0.22 + o, y + o, x + w * 0.72 - o, y + h * 0.95 - o * 2), fill=color)
    d.ellipse((x + w * 0.5 + o, y + h * 0.25 + o, x + w * 0.95 - o, y + h * 1.0 - o * 2), fill=color)


def _sun(d, cx, cy, r):
    for i in range(12):
        a = i * math.pi / 6
        d.line((cx + math.cos(a) * r * 1.3, cy + math.sin(a) * r * 1.3, cx + math.cos(a) * r * 1.75,
                cy + math.sin(a) * r * 1.75), fill=SUN, width=max(2, int(r * 0.16)))
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=SUN)
    d.ellipse((cx - r * 0.75, cy - r * 0.8, cx + r * 0.55, cy + r * 0.3), fill=(255, 224, 120))


def _moon(d, cx, cy, r, bg=(0, 0, 0, 0)):
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=MOON)
    d.ellipse((cx - r * 0.35, cy - r * 1.15, cx + r * 1.45, cy + r * 0.65), fill=bg)


def icon(code, is_day, size):
    """A weather icon (RGBA, size x size), drawn at 4x and scaled down so the edges are smooth."""
    key = (int(code or 0), bool(is_day), int(size))
    if key in _icon_cache:
        return _icon_cache[key]
    kind = weather.describe(code)[1]
    S = int(size) * 4
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    light, mid, dark = (245, 248, 255), (200, 208, 222), (120, 128, 145)
    sky = _sun if is_day else _moon
    if kind == "clear":
        sky(d, S / 2, S / 2, S * 0.26)
    elif kind in ("mostly_clear", "partly"):
        sky(d, S * 0.36, S * 0.34, S * (0.2 if kind == "partly" else 0.22))
        w = S * (0.7 if kind == "partly" else 0.55)
        _cloud(d, S - w - S * 0.06, S * 0.42, w, light, mid)
    else:
        storm_like = kind in ("storm", "heavy_rain")
        top, shade = ((150, 156, 172), (95, 100, 118)) if storm_like else (light, mid) if kind != "cloudy" else ((220, 225, 235), dark)
        if kind == "showers":
            sky(d, S * 0.32, S * 0.28, S * 0.17)
        _cloud(d, S * 0.08, S * 0.14, S * 0.84, top, shade)
        cy = S * 0.62
        if kind in ("rain", "heavy_rain", "drizzle", "showers", "storm", "sleet"):
            n = {"drizzle": 4, "rain": 4, "showers": 3, "heavy_rain": 6, "storm": 3, "sleet": 4}[kind]
            for i in range(n):
                x = S * 0.24 + i * S * 0.52 / max(1, n - 1)
                ln = S * (0.1 if kind == "drizzle" else 0.18)
                if kind == "sleet" and i % 2:
                    _flake(d, x, cy + S * 0.15, S * 0.06)
                else:
                    d.line((x, cy + S * 0.05, x - ln * 0.4, cy + S * 0.05 + ln), fill=RAIN, width=max(3, int(S * 0.035)))
        if kind in ("snow", "heavy_snow"):
            for i, (fx, fy) in enumerate(((0.3, 0.75), (0.5, 0.86), (0.7, 0.75), (0.4, 0.95), (0.6, 0.95))[:5 if kind == "heavy_snow" else 3]):
                _flake(d, S * fx, S * fy - S * 0.05, S * 0.065)
        if kind == "storm":
            bx, by = S * 0.5, cy + S * 0.02
            d.polygon([(bx, by), (bx - S * 0.12, by + S * 0.2), (bx - S * 0.02, by + S * 0.2), (bx - S * 0.08, by + S * 0.36),
                       (bx + S * 0.12, by + S * 0.12), (bx + S * 0.02, by + S * 0.12), (bx + S * 0.08, by)], fill=BOLT)
        if kind == "fog":
            for i in range(3):
                y = S * (0.68 + i * 0.1)
                d.rounded_rectangle((S * (0.12 + 0.06 * (i % 2)), y, S * (0.88 - 0.06 * (i % 2)), y + S * 0.045),
                                    radius=int(S * 0.02), fill=mid)
    # a soft shadow keeps white clouds visible on light themes too
    shadow = Image.new("RGBA", (S, S), (10, 20, 40, 0))
    shadow.putalpha(img.getchannel("A").point(lambda a: int(a * 0.45)).filter(ImageFilter.GaussianBlur(S * 0.025)))
    full = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    full.alpha_composite(shadow, (int(S * 0.012), int(S * 0.02)))
    full.alpha_composite(img)
    out = full.resize((int(size), int(size)), Image.LANCZOS)
    if len(_icon_cache) > 300:
        _icon_cache.clear()
    _icon_cache[key] = out
    return out


def _flake(d, x, y, r):
    for i in range(3):
        a = i * math.pi / 3
        d.line((x - math.cos(a) * r, y - math.sin(a) * r, x + math.cos(a) * r, y + math.sin(a) * r), fill=SNOW,
               width=max(2, int(r * 0.35)))


def drop(d, x, y, r, color=RAIN):
    d.polygon([(x, y - r * 1.6), (x - r * 0.9, y), (x + r * 0.9, y)], fill=color)
    d.ellipse((x - r, y - r, x + r, y + r), fill=color)


def moon_image(phase, size):
    """The moon at a given phase (0 new .. 0.5 full .. 1 new), lit side drawn properly."""
    S = int(size) * 2
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = S * 0.46
    c = S / 2
    d.ellipse((c - r, c - r, c + r, c + r), fill=(60, 62, 72, 255))
    lit = Image.new("L", (S, S), 0)
    ld = ImageDraw.Draw(lit)
    k = math.cos(2 * math.pi * phase)          # 1 at new, -1 at full
    for yy in range(int(c - r), int(c + r) + 1):
        dy = yy - c
        half = math.sqrt(max(0.0, r * r - dy * dy))
        term = half * k
        if phase < 0.5:     # waxing: lit on the right
            ld.line((c + term, yy, c + half, yy), fill=255)
        else:
            ld.line((c - half, yy, c - term, yy), fill=255)
    glow = Image.new("RGBA", (S, S), MOON + (255,))
    img.paste(glow, (0, 0), lit)
    craters = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    cd = ImageDraw.Draw(craters)
    for (fx, fy, fr) in ((0.42, 0.38, 0.08), (0.6, 0.56, 0.06), (0.48, 0.66, 0.05), (0.33, 0.58, 0.04)):   # a few craters
        cd.ellipse((S * fx - S * fr, S * fy - S * fr, S * fx + S * fr, S * fy + S * fr), fill=(120, 110, 80, 40))
    lit_craters = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    lit_craters.paste(craters, (0, 0), lit)
    img.alpha_composite(lit_craters)
    return img.resize((int(size), int(size)), Image.LANCZOS)


# ------------------------------------------------------------------ the renderer

class WeatherRenderer:
    def __init__(self, T, Ft, Fd, W, H, clock_fmt="12h", station=BRAND, header=None):
        self.T, self.F, self.D = T, Ft, Fd
        self.header = header or {"mode": "station"}
        self.W, self.H = W, H
        self.s = H / 720
        self.clock_fmt = clock_fmt
        self.station = station
        self._bg = None
        self._base = (None, None)
        s = self.s
        self.panel_box = (int(40 * s), int(104 * s), int(W - 40 * s), int(616 * s))
        self.crawl_y = int(669 * s)               # centre line of the crawl (drawn by ffmpeg)
        self.crawl_band = (int(640 * s) + max(2, int(3 * s)), int(698 * s))
        self.map_size = (int(self.panel_box[2] - self.panel_box[0] - 24 * s), int(self.panel_box[3] - self.panel_box[1] - 72 * s))

    # ---- helpers
    def _t(self, t, fc, fmt=None):
        """A time in the forecast location's own time zone."""
        off = (fc or {}).get("tz_offset")
        if off is None:
            return fmt_time(t, fmt or self.clock_fmt)
        d = datetime.fromtimestamp(t + off, tz=timezone.utc)
        if (fmt or self.clock_fmt).startswith("24"):
            return d.strftime("%H:%M")
        return d.strftime("%I:%M %p").lstrip("0")

    def _hour(self, t, fc):
        off = (fc or {}).get("tz_offset") or 0
        d = datetime.fromtimestamp(t + off, tz=timezone.utc)
        return d.strftime("%H:00") if self.clock_fmt.startswith("24") else d.strftime("%I %p").lstrip("0")

    def _day(self, t, fc, short=True):
        off = (fc or {}).get("tz_offset") or 0
        return datetime.fromtimestamp(t + off, tz=timezone.utc).strftime("%a" if short else "%A")

    def _case(self, s):
        return s.upper() if self.T.upper else s

    def _units(self, fc):
        imp = (fc or {}).get("imperial", True)
        return {"wind": "mph" if imp else "km/h", "press": "in" if imp else "hPa", "vis": "mi" if imp else "km"}

    def background(self):
        if self._bg is None:
            self._bg = themes.background(self.T, self.W, self.H, self.s, "slate")
        return self._bg

    # ---- frame
    def frame(self, snap, slide, sub_index, now, slide_list):
        """slide = which screen, sub_index = radar frame number; returns an RGB image."""
        key = (slide, sub_index, id(snap.get("forecast")), id((snap.get("radar") or {}).get(slide[6:] if slide.startswith("radar") else "")),
               len(snap.get("alerts") or []), int(now // 60), snap.get("error"), tuple(slide_list))
        if self._base[0] != key:
            self._base = (key, self._compose(snap, slide, sub_index, now, slide_list))
        img = self._base[1].copy()
        self._clock(img, now)
        return img.convert("RGB")

    def _compose(self, snap, slide, sub_index, now, slide_list):
        T, s, W = self.T, self.s, self.W
        c = T.c
        img = self.background().copy()
        d = ImageDraw.Draw(img)
        # top band
        band = int(84 * s)
        d.rectangle((0, 0, W, band), fill=c["chan"])
        d.rectangle((0, band, W, band + max(3, int(4 * s))), fill=c["accent"])
        tx = _Text(img.size, T, s)
        td = tx.d
        x = int(30 * s)
        brand = c.get("brand")
        hmode = self.header.get("mode", "station")
        if hmode in ("channel", "custom") or (hmode == "station" and brand != "text"):
            tint = readable(c["chan"], brand, c["chan_text"]) if isinstance(brand, tuple) else None
            mark = corner_logo(self.header, "orbital-b.png", (96 * s, 52 * s), (220 * s, 56 * s), tint,
                               tint or readable(c["chan"], c["accent"], c["chan_text"]))
            if mark is not None:
                if mark.height > band - 10 * s or mark.width > 360 * s:     # never taller than the top band
                    mark = mark.copy()
                    mark.thumbnail((int(360 * s), int(band - 10 * s)), Image.LANCZOS)
                img.alpha_composite(mark, (x, int((band - mark.height) / 2)))
                x += mark.width + int(16 * s)
        elif hmode == "name":
            nm = self._case(branding.short())
            k = (self.header.get("size") or 100) / 100
            nf = self.D.get(34 * s * min(k, 1.4), True, nm)
            td.text((x, band / 2), nm, font=nf, fill=readable(c["chan"], c["accent"], c["chan_text"]), anchor="lm")
            x += int(td.textlength(nm, font=nf)) + int(14 * s)
            d.line((x, band * 0.25, x, band * 0.75), fill=themes.mix(c["chan_text"], c["chan"], 0.5), width=max(1, int(2 * s)))
            x += int(14 * s)
        title_ink = readable(c["chan"], c["accent"], c["chan_text"])
        lw = self._case("Local Weather")
        td.text((x, band / 2 - 15 * s), lw, font=self.D.get(30 * s, True, lw), fill=title_ink, anchor="lm")
        sl = self._case(SLIDE_TITLES.get(slide, ""))
        td.text((x, band / 2 + 18 * s), sl, font=self.F.get(20 * s, True, sl), fill=c["chan_text"], anchor="lm")
        # slide dots
        if len(slide_list) > 1:
            dx = W / 2 - (len(slide_list) - 1) * 9 * s
            for i, name in enumerate(slide_list):
                r = 4 * s if name != slide else 6 * s
                cx = dx + i * 18 * s
                d.ellipse((cx - r, band / 2 - r, cx + r, band / 2 + r), fill=c["accent"] if name == slide else
                          themes.mix(c["chan_text"], c["chan"], 0.6))
        # content panel
        veil = Image.new("RGBA", img.size, (0, 0, 0, 0))
        panel(ImageDraw.Draw(veil), self.panel_box, T, s, fill=c["spot_bg"] + (248,), outline=c["spot_border"] + (255,))
        img.alpha_composite(veil)
        # crawl band (the moving text and its label are drawn by ffmpeg on top)
        cb0, cb1 = int(640 * s), int(698 * s)
        d.rectangle((0, cb0, W, cb1), fill=c["timebar"])
        d.rectangle((0, cb0, W, cb0 + max(2, int(3 * s))), fill=c["accent"])
        fc, loc = snap.get("forecast"), snap.get("location")
        if not fc or not loc:
            self._nodata(img, td, snap)
        else:
            getattr(self, "_" + slide, self._current)(img, d, td, snap, fc, loc, now, sub_index)
        tx.onto(img)
        return img

    def _clock(self, img, now):
        s, c = self.s, self.T.c
        d = ImageDraw.Draw(img)
        band = int(84 * s)
        t = fmt_time(now, self.clock_fmt)
        dt = datetime.fromtimestamp(now)
        x = self.W - 30 * s
        f = self.D.get(34 * s, True, t)
        d.text((x, band / 2 - 12 * s), t, font=f, fill=c["chan_text"], anchor="rm")
        ds = self._case(dt.strftime("%a %b ") + str(dt.day))
        d.text((x, band / 2 + 20 * s), ds, font=self.F.get(18 * s, False, ds), fill=themes.mix(c["chan_text"], c["chan"], 0.25),
               anchor="rm")

    def _header(self, td, loc, fc, right=None):
        s, c = self.s, self.T.c
        x0, y0, x1, _ = self.panel_box
        name = loc["name"] + (f", {loc['region']}" if loc.get("region") and loc["region"] != loc["name"] else "")
        name = self.F.text(name, True)
        td.text((x0 + 26 * s, y0 + 30 * s), self._case(name), font=self.D.get(28 * s, True, name), fill=c["accent"], anchor="lm")
        if right is None and fc:
            right = "Updated " + fmt_time(fc["fetched"], self.clock_fmt) + "  ·  Weather data by Open-Meteo.com"
        if right:
            td.text((x1 - 26 * s, y0 + 30 * s), right, font=self.F.get(17 * s, False, right), fill=c["muted"], anchor="rm")

    def _nodata(self, img, td, snap):
        s, c = self.s, self.T.c
        x0, y0, x1, y1 = self.panel_box
        loc = snap.get("location")
        msg = "Fetching the weather…" if not snap.get("error") and loc else "Weather unavailable"
        td.text(((x0 + x1) / 2, (y0 + y1) / 2 - 30 * s), self._case(msg), font=self.D.get(44 * s, True, msg), fill=c["text"], anchor="mm")
        err = snap.get("error") or (snap.get("errors") or {}).get("forecast") or (f"Location: {loc['name']}" if loc else "")
        if err:
            f = self.F.get(20 * s)
            for i, line in enumerate(wrap(td, err, f, x1 - x0 - 120 * s, 3)):
                td.text(((x0 + x1) / 2, (y0 + y1) / 2 + 30 * s + i * 28 * s), line, font=f, fill=c["muted"], anchor="mm")

    # ---- screens
    def _current(self, img, d, td, snap, fc, loc, now, _):
        s, c, F, D = self.s, self.T.c, self.F, self.D
        x0, y0, x1, y1 = self.panel_box
        cur = fc["current"]
        u = self._units(fc)
        self._header(td, loc, fc)
        text, _k = weather.describe(cur["code"])
        ic = icon(cur["code"], cur["is_day"], 210 * s)
        img.alpha_composite(ic, (int(x0 + 30 * s), int(y0 + 70 * s)))
        temp = f"{round(cur['temp'])}°" if cur.get("temp") is not None else "--°"
        tf = D.get(150 * s, True, temp)
        td.text((x0 + 260 * s, y0 + 170 * s), temp, font=tf, fill=c["text"], anchor="lm")
        cond = self._case(text)
        td.text((x0 + 40 * s, y0 + 320 * s), cond, font=F.get(40 * s, True, cond), fill=c["text"], anchor="lm")
        today = (fc.get("daily") or [{}])[0]
        lines = []
        if today.get("hi") is not None:
            lines.append(f"Today: High {round(today['hi'])}°  ·  Low {round(today['lo'])}°")
        if today.get("pop") is not None:
            lines.append(f"Chance of rain or snow: {round(today['pop'])}%")
        if today.get("sunrise"):
            lines.append(f"Sunrise {self._t(today['sunrise'], fc)}  ·  Sunset {self._t(today['sunset'], fc)}")
        for i, ln in enumerate(lines):
            td.text((x0 + 40 * s, y0 + 375 * s + i * 34 * s), ln, font=F.get(22 * s, False, ln), fill=c["muted"], anchor="lm")
        # details table
        rows = [("Feels like", f"{round(cur['feels'])}°" if cur.get("feels") is not None else "—"),
                ("Humidity", f"{round(cur['humidity'])}%" if cur.get("humidity") is not None else "—"),
                ("Dew point", f"{round(cur['dew'])}°" if cur.get("dew") is not None else "—"),
                ("Wind", f"{weather.compass(cur.get('wind_dir'))} {round(cur['wind'])} {u['wind']}" if cur.get("wind") else "Calm"),
                ("Gusts", f"{round(cur['gust'])} {u['wind']}" if cur.get("gust") else "—"),
                ("Pressure", (f"{cur['pressure']:.2f} {u['press']}" if fc.get("imperial", True) else f"{round(cur['pressure'])} {u['press']}")
                 if cur.get("pressure") else "—"),
                ("Visibility", f"{cur['visibility']:.0f} {u['vis']}" if cur.get("visibility") is not None else "—"),
                ("UV index", f"{round(cur['uv'])} {uv_word(cur['uv'])}" if cur.get("uv") is not None else "—"),
                ("Cloud cover", f"{round(cur['cloud'])}%" if cur.get("cloud") is not None else "—")]
        tx0, tx1 = x0 + (x1 - x0) * 0.56, x1 - 40 * s
        rh = 44 * s
        for i, (k, v) in enumerate(rows):
            y = y0 + 85 * s + i * rh
            if i % 2 == 0:
                d.rectangle((tx0 - 12 * s, y - rh / 2 + 2 * s, tx1 + 12 * s, y + rh / 2 - 2 * s),
                            fill=themes.mix(c["spot_bg"], c["text"], 0.06))
            k = self._case(k)
            td.text((tx0, y), k, font=F.get(21 * s, False, k), fill=c["muted"], anchor="lm")
            td.text((tx1, y), v, font=F.get(23 * s, True, v), fill=c["text"], anchor="rm")

    def _hourly(self, img, d, td, snap, fc, loc, now, _):
        s, c, F, D = self.s, self.T.c, self.F, self.D
        x0, y0, x1, y1 = self.panel_box
        self._header(td, loc, fc)
        hrs = [h for h in fc.get("hourly") or [] if h["t"] >= now - 1800][:12]
        if not hrs:
            return self._nodata(img, td, {"location": loc, "error": "No hourly forecast"})
        n = len(hrs)
        cw = (x1 - x0 - 60 * s) / n
        temps = [h["temp"] for h in hrs if h.get("temp") is not None] or [0]
        lo, hi = min(temps), max(temps)
        span = max(1.0, hi - lo)
        cy0, cy1 = y0 + 250 * s, y0 + 360 * s
        pts = []
        for i, h in enumerate(hrs):
            cx = x0 + 30 * s + cw * (i + 0.5)
            lab = "Now" if i == 0 else self._hour(h["t"], fc)
            td.text((cx, y0 + 78 * s), self._case(lab), font=F.get(19 * s, True, lab), fill=c["muted"], anchor="mm")
            ic = icon(h["code"], h["is_day"], 62 * s)
            img.alpha_composite(ic, (int(cx - ic.width / 2), int(y0 + 98 * s)))
            if h.get("temp") is not None:
                py = cy1 - (h["temp"] - lo) / span * (cy1 - cy0)
                pts.append((cx, py, h["temp"]))
            pop = h.get("pop") or 0
            bh = 70 * s * pop / 100
            by1 = y1 - 52 * s
            d.rectangle((cx - cw * 0.28, by1 - bh, cx + cw * 0.28, by1), fill=themes.mix(RAIN, c["spot_bg"], 0.25))
            d.line((cx - cw * 0.3, by1, cx + cw * 0.3, by1), fill=themes.mix(c["muted"], c["spot_bg"], 0.5), width=1)
            pl = f"{round(pop)}%"
            td.text((cx, by1 + 20 * s), pl, font=F.get(17 * s, False, pl), fill=themes.mix(RAIN, c["text"], 0.3), anchor="mm")
        if len(pts) > 1:
            d.line([(x, y) for x, y, _ in pts], fill=c["accent"], width=max(3, int(4 * s)), joint="curve")
        for x, y, t in pts:
            r = 6 * s
            d.ellipse((x - r, y - r, x + r, y + r), fill=c["accent"], outline=c["spot_bg"], width=max(1, int(2 * s)))
            lab = f"{round(t)}°"
            td.text((x, y - 24 * s), lab, font=D.get(24 * s, True, lab), fill=c["text"], anchor="mm")
        td.text((x0 + 30 * s, y1 - 128 * s), self._case("Chance of precipitation"), font=F.get(16 * s, False), fill=c["muted"],
                anchor="lm")

    def _daily(self, img, d, td, snap, fc, loc, now, _):
        s, c, F, D, T = self.s, self.T.c, self.F, self.D, self.T
        x0, y0, x1, y1 = self.panel_box
        self._header(td, loc, fc)
        days = (fc.get("daily") or [])[:7]
        if not days:
            return self._nodata(img, td, {"location": loc, "error": "No daily forecast"})
        n = len(days)
        gap = 12 * s
        cw = (x1 - x0 - 40 * s - gap * (n - 1)) / n
        cy0, cy1 = y0 + 62 * s, y1 - 22 * s
        for i, day in enumerate(days):
            cx0 = x0 + 20 * s + i * (cw + gap)
            fill = T.cell_fill(i)
            themes.draw_cell(img, d, (cx0, cy0, cx0 + cw, cy1), fill, T, s, current=(i == 0))
            ink = readable(fill, c["cell_text"], (255, 255, 255), (20, 20, 30))
            sub = themes.mix(ink, fill, 0.35)
            mid = cx0 + cw / 2
            name = "Today" if i == 0 else self._day(day["t"], fc)
            name = self._case(name)
            td.text((mid, cy0 + 34 * s), name, font=D.get(26 * s, True, name), fill=ink, anchor="mm")
            off = fc.get("tz_offset") or 0
            dl = datetime.fromtimestamp(day["t"] + off, tz=timezone.utc).strftime("%b ") + str(
                datetime.fromtimestamp(day["t"] + off, tz=timezone.utc).day)
            td.text((mid, cy0 + 62 * s), dl, font=F.get(16 * s, False, dl), fill=sub, anchor="mm")
            ic = icon(day["code"], True, min(cw - 16 * s, 104 * s))
            img.alpha_composite(ic, (int(mid - ic.width / 2), int(cy0 + 84 * s)))
            text = self._case(weather.describe(day["code"])[0])
            tf = F.get(17 * s, True, text)
            for j, line in enumerate(wrap(td, text, tf, cw - 16 * s, 2)):
                td.text((mid, cy0 + 208 * s + j * 22 * s), line, font=tf, fill=ink, anchor="mm")
            hi = f"{round(day['hi'])}°" if day.get("hi") is not None else "--"
            lo = f"{round(day['lo'])}°" if day.get("lo") is not None else "--"
            td.text((mid, cy0 + 290 * s), hi, font=D.get(40 * s, True, hi), fill=ink, anchor="mm")
            td.text((mid, cy0 + 334 * s), lo, font=D.get(26 * s, True, lo), fill=sub, anchor="mm")
            pop = round(day.get("pop") or 0)
            pt = f"{pop}%"
            pf = F.get(18 * s, True, pt)
            pw = text_w(td, pt, pf)
            drop(d, mid - pw / 2 - 8 * s, cy1 - 30 * s, 6 * s)
            td.text((mid + 6 * s, cy1 - 32 * s), pt, font=pf, fill=ink, anchor="mm")

    def _radar(self, img, d, td, snap, fc, loc, now, sub_index, which):
        s, c, F = self.s, self.T.c, self.F
        x0, y0, x1, y1 = self.panel_box
        rd = (snap.get("radar") or {}).get(which)
        # never pass old pictures off as current radar
        frames = [f for f in ((rd or {}).get("frames") or []) if f[0] > now - weather.RADAR_DROP or f[2] == "future"]
        if which == "future":
            frames = [f for f in frames if f[0] > now - 15 * 60]
        right, late = None, None
        err_key = "future" if which == "future" else "radar"
        if frames:
            fr = frames[min(sub_index, len(frames) - 1)]
            if fr[2] == "future":
                right = f"Forecast  {self._t(fr[0], fc)}"
            else:
                right = f"Radar  {self._t(fr[0], fc)}"
                if now - frames[-1][0] > weather.RADAR_STALE:
                    late = f"Radar delayed: newest image is from {self._t(frames[-1][0], fc)}"
        self._header(td, loc, fc, right=right or ("Loading radar…" if not (snap.get('errors') or {}).get(err_key) else "Radar unavailable"))
        mx, my = int(x0 + 12 * s), int(y0 + 60 * s)
        mw, mh = int(x1 - x0 - 24 * s), int(y1 - y0 - 72 * s)
        if rd and rd.get("base") is not None:
            m = rd["base"].convert("RGBA")
            source = ""
            if frames:
                lay = frames[min(sub_index, len(frames) - 1)][1]
                source = frames[-1][4] if len(frames[-1]) > 4 else "rainviewer"
                if lay.size != m.size:
                    lay = lay.resize(m.size)
                faded = lay.copy()
                faded.putalpha(lay.getchannel("A").point(lambda a: int(a * 0.85)))
                m.alpha_composite(faded)
            if m.size != (mw, mh):
                m = m.resize((mw, mh), Image.LANCZOS)
            weather.marker(m, mw / 2, mh / 2, s, loc["name"], self.F.get(18 * s, True, loc["name"]), color=c["now"])
            img.alpha_composite(m, (mx, my))
            # legend + credits
            lx1, ly1 = mx + mw - 14 * s, my + mh - 14 * s
            lw, lh = 200 * s, 14 * s
            if source in ("nexrad", "hrrr"):        # the NWS reflectivity colours
                grad = [(4, 233, 231), (1, 160, 246), (2, 253, 2), (1, 197, 1), (253, 248, 2), (253, 149, 0), (253, 0, 0), (248, 0, 253)]
            else:                                   # RainViewer "Universal Blue"
                grad = [(120, 190, 255), (40, 110, 255), (0, 200, 120), (255, 230, 0), (255, 120, 0), (230, 0, 40)]
            seg = lw / (len(grad) - 1)
            bg = (0, 0, 0)
            d.rectangle((lx1 - lw - 70 * s, ly1 - lh - 30 * s, lx1 + 6 * s, ly1 + 6 * s), fill=bg)
            for i in range(len(grad) - 1):
                for k in range(int(seg)):
                    col = themes.mix(grad[i], grad[i + 1], k / seg)
                    xx = lx1 - lw + i * seg + k
                    d.line((xx, ly1 - lh, xx, ly1), fill=col)
            d.text((lx1 - lw - 64 * s, ly1 - lh / 2), "Light", font=F.get(14 * s), fill=(230, 230, 230), anchor="lm")
            d.text((lx1, ly1 - lh - 16 * s), "Heavy", font=F.get(14 * s), fill=(230, 230, 230), anchor="rm")
            cr = {"nexrad": "Radar: NOAA NEXRAD via Iowa Environmental Mesonet",
                  "hrrr": "Forecast: NOAA HRRR model via Iowa Environmental Mesonet"}.get(source, "Radar: RainViewer") \
                + "  ·  Map © OpenStreetMap contributors © CARTO"
            cf = F.get(13 * s)
            cw = text_w(d, cr, cf)
            d.rectangle((mx + 8 * s, my + mh - 30 * s, mx + 22 * s + cw, my + mh - 8 * s), fill=(0, 0, 0))
            d.text((mx + 15 * s, my + mh - 19 * s), cr, font=cf, fill=(220, 220, 220), anchor="lm")
            if frames and frames[min(sub_index, len(frames) - 1)][2] == "future":
                tag = "FORECAST" if not self.T.upper else "FORECAST"
                tf = F.get(20 * s, True, tag)
                tw = text_w(d, tag, tf)
                d.rounded_rectangle((mx + 12 * s, my + 12 * s, mx + 32 * s + tw, my + 46 * s), radius=6 * s, fill=c["accent"])
                d.text((mx + 22 * s, my + 29 * s), tag, font=tf, fill=readable(c["accent"], (255, 255, 255), (0, 0, 0)), anchor="lm")
            if late:
                lf = F.get(18 * s, True, late)
                lw2 = text_w(d, late, lf)
                d.rectangle((mx + mw / 2 - lw2 / 2 - 12 * s, my + 12 * s, mx + mw / 2 + lw2 / 2 + 12 * s, my + 44 * s), fill=(0, 0, 0))
                d.text((mx + mw / 2, my + 28 * s), late, font=lf, fill=(255, 200, 80), anchor="mm")
            if not frames:
                errs = snap.get("errors") or {}
                if which == "future" and (rd or {}).get("unsupported"):
                    msg = "Forecast radar is only available in the US"
                else:
                    msg = "Loading radar…" if not errs.get(err_key) else "Radar isn't available right now"
                td.text((mx + mw / 2, my + 40 * s), msg, font=F.get(24 * s, True, msg), fill=c["text"], anchor="mm")
        else:
            d.rectangle((mx, my, mx + mw, my + mh), fill=themes.mix(c["spot_bg"], c["text"], 0.05))
            err = (snap.get("errors") or {}).get("radar")
            msg = "Loading the map…" if not err else "The radar map isn't available right now"
            td.text((mx + mw / 2, my + mh / 2), msg, font=F.get(28 * s, True, msg), fill=c["text"], anchor="mm")
            if err:
                td.text((mx + mw / 2, my + mh / 2 + 40 * s), ellipsize(td, err, F.get(18 * s), mw - 60 * s), font=F.get(18 * s),
                        fill=c["muted"], anchor="mm")

    def _radar_local(self, *a):
        self._radar(*a, which="local")

    def _radar_regional(self, *a):
        self._radar(*a, which="regional")

    def _radar_future(self, *a):
        self._radar(*a, which="future")

    def _almanac(self, img, d, td, snap, fc, loc, now, _):
        s, c, F, D = self.s, self.T.c, self.F, self.D
        x0, y0, x1, y1 = self.panel_box
        self._header(td, loc, fc)
        days = fc.get("daily") or []
        colx = [x0 + 60 * s, x0 + 330 * s]
        y = y0 + 90 * s
        for j, (label, day) in enumerate((("Today", days[0] if days else None), ("Tomorrow", days[1] if len(days) > 1 else None))):
            if not day or not day.get("sunrise"):
                continue
            lab = self._case(label)
            td.text((colx[j], y), lab, font=D.get(28 * s, True, lab), fill=c["accent"], anchor="lm")
            _sun_small = icon(0, True, 54 * s)
            img.alpha_composite(_sun_small, (int(colx[j]), int(y + 26 * s)))
            for k, (word, t) in enumerate((("Sunrise", day["sunrise"]), ("Sunset", day["sunset"]))):
                yy = y + 110 * s + k * 70 * s
                w = self._case(word)
                td.text((colx[j], yy), w, font=F.get(19 * s, False, w), fill=c["muted"], anchor="lm")
                tt = self._t(t, fc)
                td.text((colx[j], yy + 30 * s), tt, font=D.get(32 * s, True, tt), fill=c["text"], anchor="lm")
            if day.get("sunset") and day.get("sunrise"):
                L = day["sunset"] - day["sunrise"]
                dl = f"{int(L // 3600)}h {int(L % 3600 // 60)}m of daylight"
                td.text((colx[j], y + 270 * s), dl, font=F.get(19 * s, False, dl), fill=c["muted"], anchor="lm")
        if days and days[0].get("uv") is not None:
            uv = days[0]["uv"]
            ut = f"Peak UV today: {round(uv)} ({uv_word(uv)})"
            td.text((colx[0], y1 - 50 * s), ut, font=F.get(22 * s, True, ut), fill=c["text"], anchor="lm")
        # moon
        phase, illum, name = weather.moon(now)
        mx = x0 + (x1 - x0) * 0.74
        mi = moon_image(phase, 230 * s)
        img.alpha_composite(mi, (int(mx - mi.width / 2), int(y0 + 70 * s)))
        nm = self._case(name)
        td.text((mx, y0 + 330 * s), nm, font=D.get(32 * s, True, nm), fill=c["text"], anchor="mm")
        il = f"{round(illum * 100)}% illuminated"
        td.text((mx, y0 + 372 * s), il, font=F.get(20 * s, False, il), fill=c["muted"], anchor="mm")
        # next full / new moon
        age = phase * 29.530588853
        to_full = ((14.765 - age) % 29.530588853) * 86400
        to_new = ((29.530588853 - age) % 29.530588853) * 86400
        nf = "Next full moon: " + datetime.fromtimestamp(now + to_full).strftime("%a %b ") + str(datetime.fromtimestamp(now + to_full).day)
        nn = "Next new moon: " + datetime.fromtimestamp(now + to_new).strftime("%a %b ") + str(datetime.fromtimestamp(now + to_new).day)
        td.text((mx, y0 + 420 * s), nf, font=F.get(18 * s, False, nf), fill=c["muted"], anchor="mm")
        td.text((mx, y0 + 450 * s), nn, font=F.get(18 * s, False, nn), fill=c["muted"], anchor="mm")

    def _alerts(self, img, d, td, snap, fc, loc, now, _):
        s, c, F, D = self.s, self.T.c, self.F, self.D
        x0, y0, x1, y1 = self.panel_box
        alerts = snap.get("alerts") or []
        self._header(td, loc, fc, right=f"{len(alerts)} active" if alerts else "")
        if not alerts:
            msg = self._case("No weather alerts")
            td.text(((x0 + x1) / 2, (y0 + y1) / 2), msg, font=D.get(40 * s, True, msg), fill=c["text"], anchor="mm")
            return
        y = y0 + 64 * s
        colors = {"Extreme": (200, 20, 40), "Severe": (220, 60, 30), "Moderate": (230, 140, 0), "Minor": (200, 170, 0)}
        for a in alerts[:3]:
            box = (x0 + 24 * s, y, x1 - 24 * s, y + 160 * s)
            col = colors.get(a["severity"], (200, 120, 0))
            d.rectangle(box, fill=themes.mix(col, c["spot_bg"], 0.78), outline=col, width=max(2, int(3 * s)))
            d.rectangle((box[0], box[1], box[0] + 12 * s, box[3]), fill=col)
            ev = self._case(a["event"])
            td.text((box[0] + 30 * s, y + 30 * s), ev, font=D.get(30 * s, True, ev), fill=c["text"], anchor="lm")
            if a.get("ends"):
                un = "until " + fmt_time(a["ends"], self.clock_fmt) + datetime.fromtimestamp(a["ends"]).strftime(" %a")
                td.text((box[2] - 20 * s, y + 30 * s), un, font=F.get(19 * s, True, un), fill=c["text"], anchor="rm")
            body = a.get("headline") or a.get("desc") or ""
            bf = F.get(19 * s, False, body)
            for k, line in enumerate(wrap(td, body, bf, box[2] - box[0] - 60 * s, 3)):
                td.text((box[0] + 30 * s, y + 68 * s + k * 26 * s), line, font=bf, fill=c["muted"], anchor="lm")
            y += 172 * s
        if len(alerts) > 3:
            more = f"+ {len(alerts) - 3} more"
            td.text((x1 - 30 * s, y1 - 18 * s), more, font=F.get(18 * s, True, more), fill=c["muted"], anchor="rm")


def uv_word(uv):
    uv = float(uv or 0)
    return "Low" if uv < 3 else "Moderate" if uv < 6 else "High" if uv < 8 else "Very High" if uv < 11 else "Extreme"


def crawl_text(snap, clock_fmt="12h"):
    """The scrolling line along the bottom."""
    fc, loc = snap.get("forecast"), snap.get("location")
    if not fc or not loc:
        return snap.get("error") or "Fetching the latest weather…"
    parts = []
    for a in (snap.get("alerts") or [])[:3]:
        until = (" until " + fmt_time(a["ends"], clock_fmt)) if a.get("ends") else ""
        parts.append(f"ALERT: {a['event'].upper()}{until}")
    cur = fc["current"]
    u = "mph" if fc.get("imperial", True) else "km/h"
    parts.append(f"Now in {loc['name']}: {round(cur['temp'])}° and {weather.describe(cur['code'])[0].lower()}"
                 + (f", wind {weather.compass(cur.get('wind_dir'))} {round(cur['wind'])} {u}" if cur.get("wind") else ""))
    days = fc.get("daily") or []
    off = fc.get("tz_offset") or 0
    for i, day in enumerate(days[:4]):
        name = "Today" if i == 0 else datetime.fromtimestamp(day["t"] + off, tz=timezone.utc).strftime("%A")
        parts.append(f"{name}: {weather.describe(day['code'])[0]}, high {round(day['hi'])}°, low {round(day['lo'])}°"
                     + (f", {round(day['pop'])}% chance of precipitation" if day.get("pop") else ""))
    return "      •      ".join(parts) + "      •      "

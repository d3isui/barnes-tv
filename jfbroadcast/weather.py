"""Weather data for the Weather channel.

  location  - your internet connection's location (ipwho.is, ip-api.com), a ZIP / postal code (zippopotam.us),
              a city name (Open-Meteo geocoding) or exact coordinates
  forecast  - Open-Meteo (free, no key): current conditions, 48 hours, 7 days
  alerts    - US National Weather Service active alerts (US locations only)
  radar     - RainViewer radar frames (free for personal use, max zoom 7) over CARTO / OpenStreetMap base maps

Everything is cached in memory and on disk: if the internet drops, the channel keeps showing the last good data.
"""
import hashlib
import io
import json
import logging
import math
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from . import net

log = logging.getLogger("weather")

UA = "BarnesTV/1.14 (personal weather channel; https://github.com/d3isui/barnes-tv)"
URLS = {
    "ipwho": "https://ipwho.is/",
    "ipapi": "http://ip-api.com/json/",
    "zip": "https://api.zippopotam.us/{country}/{zip}",
    "geocode": "https://geocoding-api.open-meteo.com/v1/search?name={q}&count=1&language=en&format=json",
    "forecast": "https://api.open-meteo.com/v1/forecast",
    "alerts": "https://api.weather.gov/alerts/active?point={lat:.4f},{lon:.4f}",
    "radar": "https://api.rainviewer.com/public/weather-maps.json",
    "basemap": "https://basemaps.cartocdn.com/rastertiles/{style}/{z}/{x}/{y}{scale}.png?key={key}",
    # US: NOAA NEXRAD mosaic and NOAA HRRR forecast reflectivity, served as map tiles by the Iowa Environmental Mesonet
    "iem_tile": "https://mesonet.agron.iastate.edu/c/tile.py/1.0.0/{layer}/{z}/{x}/{y}.png",
    # the HRRR layers are only served from IEM's short-cache endpoint (/cache/...), not the long-cache one (/c/...)
    "iem_tile_hrrr": "https://mesonet.agron.iastate.edu/cache/tile.py/1.0.0/{layer}/{z}/{x}/{y}.png",
    "hrrr_meta": "https://mesonet.agron.iastate.edu/data/gis/images/4326/hrrr/refd_1080.json",
}
if os.environ.get("BTV_WEATHER_MOCK"):          # testing only: send every request to a local mock server
    _m = os.environ["BTV_WEATHER_MOCK"].rstrip("/")
    URLS = {"ipwho": _m + "/ipwho", "ipapi": _m + "/ipapi", "zip": _m + "/zip/{country}/{zip}",
            "geocode": _m + "/geocode?name={q}", "forecast": _m + "/forecast", "alerts": _m + "/alerts?point={lat:.4f},{lon:.4f}",
            "radar": _m + "/radar", "basemap": _m + "/basemap/{style}/{z}/{x}/{y}{scale}.png?key={key}",
            "iem_tile": _m + "/iem/{layer}/{z}/{x}/{y}.png", "iem_tile_hrrr": _m + "/iem/{layer}/{z}/{x}/{y}.png",
            "hrrr_meta": _m + "/hrrr_meta"}
FORECAST_EVERY = 600          # seconds between forecast refreshes
RADAR_EVERY = 300             # the US mosaic updates every 5 minutes; tiles already fetched are reused
RADAR_RETRY = 90              # after a failed refresh
RADAR_STALE = 40 * 60         # an older "latest" frame is labelled as delayed
RADAR_DROP = 3 * 3600         # frames older than this are never shown
ALERTS_EVERY = 300
AUTO_LOCATION_EVERY = 12 * 3600
TILE = 512                    # map tile size in pixels (CARTO @2x and RainViewer 512 tiles)
RADAR_GAP = float(os.environ.get("BTV_RADAR_GAP", 0.7))   # seconds between radar tile requests (100 / minute allowed)
RADAR_COLOR = 2               # Universal Blue: the only colour scheme RainViewer still serves for free
IMPERIAL = {"US", "PR", "GU", "VI", "AS", "MP", "LR", "MM"}

WMO = {  # weather code -> (text, icon kind)
    0: ("Clear", "clear"), 1: ("Mostly Clear", "mostly_clear"), 2: ("Partly Cloudy", "partly"),
    3: ("Cloudy", "cloudy"), 45: ("Fog", "fog"), 48: ("Freezing Fog", "fog"),
    51: ("Light Drizzle", "drizzle"), 53: ("Drizzle", "drizzle"), 55: ("Heavy Drizzle", "drizzle"),
    56: ("Freezing Drizzle", "sleet"), 57: ("Freezing Drizzle", "sleet"),
    61: ("Light Rain", "rain"), 63: ("Rain", "rain"), 65: ("Heavy Rain", "heavy_rain"),
    66: ("Freezing Rain", "sleet"), 67: ("Freezing Rain", "sleet"),
    71: ("Light Snow", "snow"), 73: ("Snow", "snow"), 75: ("Heavy Snow", "heavy_snow"), 77: ("Snow Grains", "snow"),
    80: ("Rain Showers", "showers"), 81: ("Rain Showers", "showers"), 82: ("Heavy Showers", "heavy_rain"),
    85: ("Snow Showers", "snow"), 86: ("Heavy Snow Showers", "heavy_snow"),
    95: ("Thunderstorms", "storm"), 96: ("T-Storms & Hail", "storm"), 99: ("T-Storms & Hail", "storm"),
}
COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def describe(code):
    return WMO.get(int(code or 0), ("—", "cloudy"))


def compass(deg):
    try:
        return COMPASS[int((float(deg) % 360) / 22.5 + 0.5) % 16]
    except (TypeError, ValueError):
        return ""


def moon(t=None):
    """(phase 0..1 where 0 = new and 0.5 = full, illuminated fraction, name)."""
    t = t or time.time()
    age = ((t - 947182440) / 86400.0) % 29.530588853          # days since a known new moon (6 Jan 2000)
    phase = age / 29.530588853
    illum = (1 - math.cos(2 * math.pi * phase)) / 2
    names = [(1.84, "New Moon"), (5.53, "Waxing Crescent"), (9.22, "First Quarter"), (12.91, "Waxing Gibbous"),
             (16.61, "Full Moon"), (20.30, "Waning Gibbous"), (23.99, "Last Quarter"), (27.68, "Waning Crescent"),
             (30.0, "New Moon")]
    return phase, illum, next(n for limit, n in names if age < limit)


def http_json(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json, application/geo+json"})
    with net.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def http_bytes(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with net.urlopen(req, timeout=timeout) as r:
        return r.read()


# ------------------------------------------------------------------ location

def resolve_location(cfg):
    """Turns the channel's location settings into {name, region, country, lat, lon, source}."""
    mode = (cfg or {}).get("mode", "auto")
    name = ((cfg or {}).get("name") or "").strip()
    if mode == "coords":
        lat, lon = float(cfg.get("lat")), float(cfg.get("lon"))
        loc = {"name": name or f"{lat:.2f}, {lon:.2f}", "region": "", "country": (cfg.get("country") or "").upper(),
               "lat": lat, "lon": lon, "source": "coordinates"}
    elif mode == "zip":
        country = (cfg.get("country") or "US").strip().lower()
        z = urllib.parse.quote((cfg.get("zip") or "").strip())
        d = http_json(URLS["zip"].format(country=country, zip=z))
        p = (d.get("places") or [{}])[0]
        loc = {"name": p.get("place name") or d.get("post code"), "region": p.get("state abbreviation") or p.get("state") or "",
               "country": (d.get("country abbreviation") or country).upper(), "lat": float(p["latitude"]),
               "lon": float(p["longitude"]), "source": f"ZIP {d.get('post code') or cfg.get('zip')}"}
    elif mode == "city":
        d = http_json(URLS["geocode"].format(q=urllib.parse.quote((cfg.get("query") or "").strip())))
        r = (d.get("results") or [None])[0]
        if not r:
            raise ValueError(f"Couldn't find “{cfg.get('query')}”")
        loc = {"name": r.get("name"), "region": r.get("admin1") or "", "country": (r.get("country_code") or "").upper(),
               "lat": float(r["latitude"]), "lon": float(r["longitude"]), "source": "city search"}
    else:
        loc = None
        try:
            d = http_json(URLS["ipwho"])
            if d.get("success", True) and d.get("latitude") is not None:
                loc = {"name": d.get("city") or "", "region": d.get("region_code") or d.get("region") or "",
                       "country": (d.get("country_code") or "").upper(), "lat": float(d["latitude"]),
                       "lon": float(d["longitude"]), "source": "your internet connection"}
        except Exception as e:
            log.info("ipwho.is lookup failed: %s", e)
        if loc is None:
            d = http_json(URLS["ipapi"])
            if d.get("status") != "success":
                raise ValueError("Couldn't work out your location from your internet connection")
            loc = {"name": d.get("city") or "", "region": d.get("region") or d.get("regionName") or "",
                   "country": (d.get("countryCode") or "").upper(), "lat": float(d["lat"]), "lon": float(d["lon"]),
                   "source": "your internet connection"}
    if name:                         # the name you typed is shown exactly as typed (no ", IL" added to "Chicago, IL")
        loc["name"], loc["region"] = name, ""
    return loc


def use_imperial(units, country):
    return units == "imperial" or (units in (None, "", "auto") and (country or "US").upper() in IMPERIAL)


# ------------------------------------------------------------------ forecast

def _epoch(local_iso, offset):
    """Open-Meteo's local 'YYYY-MM-DDTHH:MM' (timezone=auto) -> UNIX time."""
    d = datetime.strptime(local_iso[:16], "%Y-%m-%dT%H:%M") if "T" in local_iso else datetime.strptime(local_iso, "%Y-%m-%d")
    return d.replace(tzinfo=timezone.utc).timestamp() - offset


def fetch_forecast(lat, lon, imperial):
    cur = ("temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,weather_code,cloud_cover,"
           "pressure_msl,wind_speed_10m,wind_direction_10m,wind_gusts_10m,visibility,dew_point_2m,uv_index")
    q = {"latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}", "current": cur,
         "hourly": "temperature_2m,precipitation_probability,weather_code,is_day",
         "daily": ("weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset,"
                   "uv_index_max,wind_speed_10m_max"),
         "timezone": "auto", "forecast_days": "8", "wind_speed_unit": "mph" if imperial else "kmh"}
    if imperial:
        q.update(temperature_unit="fahrenheit", precipitation_unit="inch")
    d = http_json(URLS["forecast"] + "?" + urllib.parse.urlencode(q))
    return parse_forecast(d, imperial)


def parse_forecast(d, imperial):
    off = int(d.get("utc_offset_seconds") or 0)
    c = d.get("current") or {}
    vis = c.get("visibility")
    out = {
        "fetched": time.time(), "imperial": imperial, "tz_offset": off, "tz": d.get("timezone_abbreviation") or "",
        "current": {
            "t": _epoch(c["time"], off) if c.get("time") else time.time(),
            "temp": c.get("temperature_2m"), "feels": c.get("apparent_temperature"),
            "humidity": c.get("relative_humidity_2m"), "dew": c.get("dew_point_2m"),
            "wind": c.get("wind_speed_10m"), "wind_dir": c.get("wind_direction_10m"), "gust": c.get("wind_gusts_10m"),
            # Open-Meteo gives hPa and metres whatever the units: convert for US screens
            "pressure": (c["pressure_msl"] * 0.0295300 if imperial else c["pressure_msl"]) if c.get("pressure_msl") else None,
            "visibility": (vis / 1609.344 if imperial else vis / 1000) if vis is not None else None,
            "uv": c.get("uv_index"), "cloud": c.get("cloud_cover"), "code": c.get("weather_code", 3),
            "is_day": bool(c.get("is_day", 1)), "precip": c.get("precipitation"),
        },
        "hourly": [], "daily": [],
    }
    h = d.get("hourly") or {}
    now = time.time()
    for i, ts in enumerate(h.get("time") or []):
        t = _epoch(ts, off)
        if t < now - 3600:
            continue
        out["hourly"].append({"t": t, "temp": _at(h, "temperature_2m", i), "pop": _at(h, "precipitation_probability", i),
                              "code": _at(h, "weather_code", i), "is_day": bool(_at(h, "is_day", i, 1))})
        if len(out["hourly"]) >= 36:
            break
    dd = d.get("daily") or {}
    for i, ds in enumerate(dd.get("time") or []):
        out["daily"].append({"date": ds, "t": _epoch(ds, off), "hi": _at(dd, "temperature_2m_max", i),
                             "lo": _at(dd, "temperature_2m_min", i), "pop": _at(dd, "precipitation_probability_max", i),
                             "code": _at(dd, "weather_code", i), "uv": _at(dd, "uv_index_max", i),
                             "wind": _at(dd, "wind_speed_10m_max", i),
                             "sunrise": _epoch(dd["sunrise"][i], off) if _at(dd, "sunrise", i) else None,
                             "sunset": _epoch(dd["sunset"][i], off) if _at(dd, "sunset", i) else None})
    return out


def _at(d, key, i, default=None):
    v = d.get(key) or []
    return v[i] if i < len(v) and v[i] is not None else default


# ------------------------------------------------------------------ alerts (US)

SEVERITY = {"Extreme": 0, "Severe": 1, "Moderate": 2, "Minor": 3}


def fetch_alerts(lat, lon):
    d = http_json(URLS["alerts"].format(lat=lat, lon=lon))
    out = []
    for f in d.get("features") or []:
        p = f.get("properties") or {}
        end = p.get("ends") or p.get("expires")
        try:
            end_t = datetime.fromisoformat(end.replace("Z", "+00:00")).timestamp() if end else None
        except ValueError:
            end_t = None
        if end_t and end_t < time.time():
            continue
        out.append({"event": p.get("event") or "Weather Alert", "headline": p.get("headline") or "",
                    "severity": p.get("severity") or "", "ends": end_t,
                    "desc": " ".join((p.get("description") or "").split())[:600],
                    "instruction": " ".join((p.get("instruction") or "").split())[:300]})
    out.sort(key=lambda a: (SEVERITY.get(a["severity"], 4), a["ends"] or 9e12))
    return out


# ------------------------------------------------------------------ maps & radar

def world_px(lat, lon, z):
    """Web-Mercator pixel position at zoom z (TILE-pixel tiles)."""
    n = TILE * (2 ** z)
    lat = max(-85.0, min(85.0, lat))
    x = (lon + 180.0) / 360.0 * n
    y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    return x, y


# ---- cleaning up NEXRAD / HRRR radar images
# The IEM mosaic (N0Q) and HRRR tiles share one 256-colour palette, where colour number i means (i - 1) / 2 - 32 dBZ.
# It reaches all the way down to -32 dBZ: in "clear-air mode" (most nights, and calm days) the radars pick up bugs,
# birds, dust and temperature layers, which show up as grey-blue static and beige rings around every radar site. TV
# stations hide those weak echoes. So each tile is decoded back to dBZ, echoes below the channel's threshold are
# dropped, lone specks are cleaned away, and what's left is drawn in the classic NWS colours shown in the legend.
# Palette from the Iowa Environmental Mesonet (github.com/akrherz/iem, data/gis/images/n0q-ramp.png, MIT licence).
IEM_PALETTE = bytes.fromhex(
    "00000085718f85718f86738d87758b87758b8877898979878979878a7b858b7d848b7d848c7f828d81808d81808e837e8f857c8f857c9087"
    "7b918979918979928b77938d759691539894579b975b9d9a60a09d64a3a068a5a36da8a671aaa976adac7ab0af7eb2b283b7b88cbabb90bd"
    "be94bfc199c2c49dc4c7a2c7caa6cacdaaccd0afd2d4b4cfd2b4c9ccb4c6c9b4c3c7b4c0c4b4bdc1b4b9beb4b6bbb4b3b9b4b0b6b4adb3b4"
    "aab0b4a4abb4a0a8b49da5b49aa2b497a0b4949db4919ab4949bb59098b48c95b38892b2808cb07c89af7886ae7483ac7080ab6c7daa6779"
    "a96376a85f73a75b70a6576da44f67a24b64a14761a0435e9f415b9e4361a24568a6486faa4a76ae4d7db24f84b6518bbb5699c3599fc75b"
    "a6cb5eadcf60b4d462bbd865c2dc67c9e06ad0e46fd6e868d6d759d6b352d6a24bd69043d67e3cd66d35d65b11d51811d11710cd1710c816"
    "10c4160fbc150fb7140eb3140eaf130eab130da6120da2120d9e110c99110c95100c91100b880f0b840e0a800e0a7c0d0a770d09730c096f"
    "0c096b0b08660b08620a095e09327308467d085b88076f9207849d0698a806adb205c1bd05d6c704ead204ffe200ffd800ffd300ffce00ff"
    "c900ffc400ffc000ffbb00ffb600ffb100ffac00ffa700ffa200ff9900ff9400ff8f00ff8a00ff8500ff8000ff0000f80000f10000ea0000"
    "e30000d50000cd0000c60000bf0000b80000b10000aa0000a300009b00009400008d00007f0000780000710000fffffffff5ffffeaffffdf"
    "ffffd4ffffc9ffffbeffffb3ffff9dffff92ffff75fffc6bfdf960faf656f7f34bf4f040f1ed36efea2bece720e9e10be3b200ffac00fca4"
    "00f79b00f49300ef8800ea8300e87900e27200dd6900db05ecf005ecf005ecf005dde005dde005dde005cdd005cdd004bdc004bdc004bdc0"
    "04aeb004aeb0049ea0049ea0049ea0038e90038e90038e90037e80037e80036f70036f70036f70025f60025f60024f50024f50024f50023f"
    "40023f40023f400130300130300120200120200120203a67b53a67b53a67b53a67b5fefefeffffff")
NWS_STEPS = ((5, (4, 233, 231)), (10, (1, 159, 244)), (15, (3, 0, 244)), (20, (2, 253, 2)), (25, (1, 197, 1)),
             (30, (0, 142, 0)), (35, (253, 248, 2)), (40, (229, 188, 0)), (45, (253, 149, 0)), (50, (253, 0, 0)),
             (55, (212, 0, 0)), (60, (188, 0, 0)), (65, (248, 0, 253)), (70, (152, 84, 198)), (75, (253, 253, 253)))
RADAR_MIN_DBZ = 10           # default: hides clear-air static, keeps drizzle and light snow
RADAR_DATA_ZOOM = 7          # radar pictures are fetched at most at this zoom (finer data doesn't exist / isn't free)
ZOOM_RANGE = {"local": (4, 10), "regional": (3, 8), "future": (4, 9)}
_pal_img = Image.new("P", (1, 1))
_pal_img.putpalette(IEM_PALETTE)


def iem_dbz(i):
    return None if i in (0, 255) else (i - 1) / 2 - 32


def nws_color(dbz):
    col = NWS_STEPS[0][1]
    for t, c in NWS_STEPS:
        if dbz >= t:
            col = c
    return col


_NWS_PAL = bytes(v for i in range(256) for v in (nws_color(iem_dbz(i)) if iem_dbz(i) is not None else (0, 0, 0)))


def clean_iem_tile(tile, min_dbz):
    """An IEM radar tile (RGBA) with weak echoes and specks removed, recoloured to the NWS colours."""
    rgb = tile.convert("RGB")
    q = rgb.quantize(palette=_pal_img, dither=Image.Dither.NONE)
    # safety: if most of the tile's colours aren't from this palette (IEM changed it?), leave the tile as it is
    seen = tile.getchannel("A").point(lambda a: 255 if a > 0 else 0)
    dr, dg, db = ImageChops.difference(q.convert("RGB"), rgb).split()
    off = ImageChops.multiply(ImageChops.lighter(ImageChops.lighter(dr, dg), db).point(lambda v: 255 if v > 6 else 0), seen)
    n_seen, n_off = seen.histogram()[255], off.histogram()[255]
    if n_seen and n_off > n_seen * 0.3:
        return tile
    idx = Image.frombytes("L", q.size, q.tobytes())
    keep = [0 if iem_dbz(i) is None or iem_dbz(i) < min_dbz else 255 for i in range(256)]
    alpha = ImageChops.multiply(idx.point(keep), tile.getchannel("A"))
    alpha = alpha.filter(ImageFilter.MedianFilter(3))      # lone pixels of noise go; real rain areas stay
    q.putpalette(_NWS_PAL)
    out = q.convert("RGB")
    out.putalpha(alpha)
    return out


class Radar:
    """A map centred on the location with the latest radar frames on top. Base-map tiles are cached on disk for
    good; radar tiles are fetched gently (RainViewer allows 100 requests a minute)."""

    def __init__(self, cache_dir: Path):
        self.cache = cache_dir
        self.lock = threading.Lock()
        self.key = ""
        self.map_error = ""

    def _tiles(self, cx, cy, w, h):
        x0, y0 = cx - w / 2, cy - h / 2
        tx0, ty0 = int(x0 // TILE), int(y0 // TILE)
        tx1, ty1 = int((x0 + w - 1) // TILE), int((y0 + h - 1) // TILE)
        return x0, y0, [(tx, ty) for ty in range(ty0, ty1 + 1) for tx in range(tx0, tx1 + 1)]

    def _fetch_tile(self, style, z, x, y):
        """A CARTO map tile (high-resolution if available). CARTO needs an API key since 2026; without one the
        tiles come back watermarked, so those are never cached."""
        key = urllib.parse.quote(self.key or "")
        last = None
        for scale in ("@2x", ""):
            try:
                return http_bytes(URLS["basemap"].format(style=style, z=z, x=x, y=y, scale=scale, key=key))
            except urllib.error.HTTPError as e:
                last = e
                if e.code in (401, 403):
                    self.map_error = ("CARTO refused the map key (HTTP %d). Check it under Settings → Weather maps; "
                                      "if the key is limited to certain websites, remove that limit." % e.code
                                      if self.key else "CARTO maps need a free API key: add one under Settings → Weather maps.")
                    raise
        raise last

    def basemap(self, lat, lon, z, w, h, style):
        cx, cy = world_px(lat, lon, z)
        x0, y0, tiles = self._tiles(cx, cy, w, h)
        img = Image.new("RGB", (w, h), (20, 24, 32) if "dark" in style else (232, 232, 228))
        n = 2 ** z
        self.map_error = ""
        for i, (tx, ty) in enumerate(tiles):
            if not 0 <= ty < n:
                continue
            txw = tx % n
            # "tiles2": the first version cached tiles fetched without a key (watermarked); never reuse those
            p = self.cache / "tiles2" / style / str(z) / f"{txw}_{ty}.png"
            if not p.exists():
                try:
                    data = self._fetch_tile(style, z, txw, ty)
                    p.parent.mkdir(parents=True, exist_ok=True)
                    if self.key:            # keyless tiles may carry CARTO's "API key required" watermark
                        p.write_bytes(data)
                    t = Image.open(io.BytesIO(data)).convert("RGB")
                    img.paste(t.resize((TILE, TILE)) if t.size != (TILE, TILE) else t, (int(tx * TILE - x0), int(ty * TILE - y0)))
                except Exception as e:
                    log.info("base map tile %s/%s/%s failed: %s", z, txw, ty, e)
                continue
            try:
                t = Image.open(p).convert("RGB")
                if t.size != (TILE, TILE):
                    t = t.resize((TILE, TILE))
                img.paste(t, (int(tx * TILE - x0), int(ty * TILE - y0)))
            except Exception:
                pass
        return img

    def layer(self, frame, lat, lon, z, w, h, stop=None, min_dbz=RADAR_MIN_DBZ):
        """One radar frame drawn for this map: an RGBA layer, or None if no tile came back.
        frame = {"time", "kind": past|future, "key", "url": template with {z} {x} {y}, "gap": seconds between tiles}
        Zoomed in past RADAR_DATA_ZOOM, the radar is fetched at that zoom for the smaller area and enlarged (the map
        underneath still gets sharper)."""
        if z > RADAR_DATA_ZOOM:
            k = 2 ** (z - RADAR_DATA_ZOOM)
            sw, sh = math.ceil(w / k) + 2, math.ceil(h / k) + 2
            small = self.layer(frame, lat, lon, RADAR_DATA_ZOOM, sw, sh, stop, min_dbz)
            if small is None:
                return None
            big = small.resize((sw * k, sh * k), Image.BILINEAR)
            ox, oy = (sw * k - w) // 2, (sh * k - h) // 2
            return big.crop((ox, oy, ox + w, oy + h))
        cx, cy = world_px(lat, lon, z)
        x0, y0, tiles = self._tiles(cx, cy, w, h)
        n = 2 ** z
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        got = 0
        for tx, ty in tiles:
            if stop and stop():
                return None
            if not 0 <= ty < n:
                continue
            try:
                t = Image.open(io.BytesIO(http_bytes(frame["url"].format(z=z, x=tx % n, y=ty)))).convert("RGBA")
                if frame.get("source") in ("nexrad", "hrrr") and min_dbz is not None:
                    t = clean_iem_tile(t, min_dbz)
                if t.size != (TILE, TILE):        # 256-pixel tiles cover the same area: just scale them up
                    t = t.resize((TILE, TILE), Image.BILINEAR)
                layer.alpha_composite(t, (int(tx * TILE - x0), int(ty * TILE - y0)))
                got += 1
            except Exception as e:
                log.debug("radar tile failed: %s", e)
            time.sleep(frame.get("gap", 0))
        return layer if got else None


def in_us_radar(loc):
    """Inside the NEXRAD / HRRR coverage (the lower 48 states and nearby)."""
    try:
        return 21 <= float(loc["lat"]) <= 53 and -131 <= float(loc["lon"]) <= -60
    except (KeyError, TypeError, ValueError):
        return False


def _utc(t, fmt="%Y%m%d%H%M"):
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime(fmt)


def past_frames(loc, n, now=None):
    """The newest n radar frames (oldest first), 10 minutes apart. US: NOAA's NEXRAD mosaic (IEM); elsewhere:
    RainViewer (which only keeps the past two hours)."""
    now = now or time.time()
    if in_us_radar(loc):
        latest = (int(now) - 8 * 60) // 300 * 300            # the mosaic for minute :05, :10 ... is ready ~5 min later
        out = []
        for i in range(n - 1, -1, -1):
            t = latest - i * 600
            layer = f"ridge::USCOMP-N0Q-{_utc(t)}"
            out.append({"time": t, "kind": "past", "key": layer, "source": "nexrad", "gap": 0.05,
                        "url": URLS["iem_tile"].replace("{layer}", layer)})
        return out
    maps = http_json(URLS["radar"])
    host = maps.get("host") or "https://tilecache.rainviewer.com"
    past = (maps.get("radar") or {}).get("past") or []
    return [{"time": fr.get("time") or 0, "kind": "past", "key": "rv" + fr["path"], "source": "rainviewer",
             "gap": RADAR_GAP, "url": f"{host}{fr['path']}/{TILE}/{{z}}/{{x}}/{{y}}/{RADAR_COLOR}/1_1.png"}
            for fr in past[-n:]]


def future_frames(loc, n, step_min=30, now=None):
    """Forecast radar for the next few hours: NOAA's HRRR model simulated reflectivity (US only). RainViewer's
    short "nowcast" ended in January 2026, so there is no forecast radar outside the US."""
    if not in_us_radar(loc):
        return None
    now = now or time.time()
    meta = http_json(URLS["hrrr_meta"])
    init_s = str(meta.get("model_init_utc") or "")
    init = datetime.fromisoformat(init_s.replace("Z", "+00:00")).timestamp()
    out = []
    t = (int(now) // (step_min * 60) + 1) * step_min * 60        # the next half hour, then every step after it
    while len(out) < n:
        f = int(round((t - init) / 60 / 15)) * 15
        if f > 1080:
            break
        if f >= 0:
            layer = f"hrrr::REFD-F{f:04d}-{_utc(init)}"
            out.append({"time": init + f * 60, "kind": "future", "key": layer, "source": "hrrr", "gap": 0.05,
                        "url": URLS["iem_tile_hrrr"].replace("{layer}", layer)})
        t += step_min * 60
    return out


def marker(img, x, y, s, label=None, font=None, color=(255, 80, 80)):
    d = ImageDraw.Draw(img)
    r = 9 * s
    d.ellipse((x - r * 2, y - r * 2, x + r * 2, y + r * 2), outline=color + (200,) if img.mode == "RGBA" else color,
              width=max(2, int(2 * s)))
    d.ellipse((x - r, y - r, x + r, y + r), fill=color, outline=(255, 255, 255), width=max(2, int(2 * s)))
    if label and font:
        tw = d.textlength(label, font=font)
        bx = x + r * 2 + 6 * s
        d.rectangle((bx - 6 * s, y - 16 * s, bx + tw + 6 * s, y + 16 * s), fill=(0, 0, 0))
        d.text((bx, y), label, font=font, fill=(255, 255, 255), anchor="lm")


# ------------------------------------------------------------------ the service

class WeatherService:
    """One per app. Channels share data for the same location. Fetching happens in background threads; callers
    always get the latest snapshot immediately."""

    def __init__(self, app):
        self.app = app
        self.cache = app.store.data_dir / "cache" / "weather"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.radar = Radar(self.cache)
        self.lock = threading.Lock()
        self.locs = {}          # location-settings key -> (time, location or None, error)
        self.data = {}          # location key -> state
        self.busy = set()

    @staticmethod
    def _cfg(ch):
        return ch.get("weather") or {}

    def _loc_key(self, cfg):
        lc = cfg.get("location") or {}
        return json.dumps(dict({k: lc.get(k) for k in ("mode", "zip", "country", "query", "lat", "lon", "name")}, v=2), sort_keys=True)

    def location(self, ch, wait=False):
        """(location dict or None, error text)."""
        cfg = self._cfg(ch)
        key = self._loc_key(cfg)
        lc = cfg.get("location") or {}
        with self.lock:
            hit = self.locs.get(key)
        fresh = hit and (hit[1] is not None) and (lc.get("mode", "auto") != "auto" or time.time() - hit[0] < AUTO_LOCATION_EVERY)
        if hit and (fresh or time.time() - hit[0] < 120):
            return hit[1], hit[2]
        disk = self.cache / ("loc-" + hashlib.md5(key.encode()).hexdigest()[:12] + ".json")

        def work():
            try:
                loc, err = resolve_location(lc), ""
                disk.write_text(json.dumps(loc))
            except Exception as e:
                err = f"Couldn't find the location: {e}"
                try:
                    loc = json.loads(disk.read_text())         # last good answer
                except Exception:
                    loc = None
                log.warning("weather: %s", err)
            with self.lock:
                self.locs[key] = (time.time(), loc, err)
        if wait:
            work()
        else:
            self._background("loc" + key, work)
            if hit is None:
                try:
                    return json.loads(disk.read_text()), ""
                except Exception:
                    return None, ""
        with self.lock:
            hit = self.locs.get(key)
        return (hit[1], hit[2]) if hit else (None, "")

    def _background(self, name, fn):
        with self.lock:
            if name in self.busy:
                return
            self.busy.add(name)

        def run():
            try:
                fn()
            except Exception:
                log.exception("weather task %s failed", name)
            finally:
                with self.lock:
                    self.busy.discard(name)
        threading.Thread(target=run, daemon=True, name="weather-" + name[:20]).start()

    def snapshot(self, ch, map_size=(1200, 520), light=False, wait=False, radar=True, refresh=False):
        """Everything the weather channel needs right now (fetching what's stale in the background)."""
        cfg = self._cfg(ch)
        loc, loc_err = self.location(ch, wait=wait)
        if not loc:
            return {"location": None, "error": loc_err or "Finding your location…"}
        imperial = use_imperial(cfg.get("units", "auto"), loc.get("country"))
        k = f"{loc['lat']:.3f},{loc['lon']:.3f},{'i' if imperial else 'm'}"
        with self.lock:
            st = self.data.setdefault(k, {"forecast": None, "alerts": [], "radar": {}, "errors": {}, "at": {}})
            if st.get("forecast") is None:
                p = self.cache / f"fc-{k.replace(',', '_')}.json"
                if p.exists():
                    try:
                        st["forecast"] = json.loads(p.read_text())
                    except Exception:
                        pass
        now = time.time()
        lat, lon = loc["lat"], loc["lon"]
        # radar settings changed (zoom, filtering, loop length, screens): fetch new maps now, not at the next refresh
        sig = json.dumps([cfg.get(x) for x in ("radar_zoom_local", "radar_zoom_regional", "radar_zoom_future",
                                               "radar_min_dbz", "radar_frames", "slides")], default=str)
        if st.get("radar_sig") != sig:
            if st.get("radar_sig") is not None:
                st["at"]["radar"] = 0
            st["radar_sig"] = sig

        def get_forecast():
            try:
                fc = fetch_forecast(lat, lon, imperial)
                (self.cache / f"fc-{k.replace(',', '_')}.json").write_text(json.dumps(fc))
                st["forecast"], st["errors"]["forecast"] = fc, ""
            except Exception as e:
                st["errors"]["forecast"] = f"{type(e).__name__}: {e}"
                log.warning("weather forecast failed (%s): %s: %s", URLS["forecast"], type(e).__name__, e)
            st["at"]["forecast"] = time.time()

        def get_alerts():
            try:
                st["alerts"], st["errors"]["alerts"] = fetch_alerts(lat, lon), ""
            except Exception as e:
                st["errors"]["alerts"] = str(e)
            st["at"]["alerts"] = time.time()

        def get_radar():
            w, h = map_size
            style = "light_all" if light else "dark_all"
            self.radar.key = (self.app.store.settings.get("map_api_key") or "").strip()
            stop = lambda: self.app.stop_evt.is_set()
            slides = cfg.get("slides") or DEFAULT_SLIDES
            frames_wanted = max(1, min(12, int(cfg.get("radar_frames") or 6)))
            mz = cfg.get("radar_min_dbz", RADAR_MIN_DBZ)
            min_dbz = None if mz in (None, "", "all") else float(mz)
            jobs, ok = [], True
            try:
                past = past_frames(loc, frames_wanted)
                jobs += [("local", int(cfg.get("radar_zoom_local") or 7), past),
                         ("regional", int(cfg.get("radar_zoom_regional") or 5), past)]
            except Exception as e:
                st["errors"]["radar"] = f"radar list: {e}"
                log.warning("weather radar list failed: %s", e)
                ok = False
            if "radar_future" in slides:
                try:
                    fut = future_frames(loc, frames_wanted)
                    if fut is None:
                        st["radar"]["future"] = {"unsupported": True, "frames": [], "fetched": time.time()}
                    else:
                        jobs.append(("future", int(cfg.get("radar_zoom_future") or 6), fut))
                    st["errors"]["future"] = ""
                except Exception as e:
                    st["errors"]["future"] = f"forecast radar: {e}"
                    log.warning("weather forecast radar failed: %s", e)
            for name, z, wanted in jobs:
                if name != "future" and ("radar_" + name) not in slides:
                    continue
                lo, hi = ZOOM_RANGE.get(name, (3, 7))
                z = max(lo, min(hi, z))
                old = st["radar"].get(name) or {}
                base = old.get("base") if old.get("zoom") == z and old.get("base") is not None and \
                    old.get("base_size") == (w, h, style) and not self.radar.map_error else None
                if base is None:
                    base = self.radar.basemap(lat, lon, z, w, h, style)
                # frames already drawn for this map are reused: each refresh normally fetches just the newest one
                have = {f[3]: f for f in (old.get("frames") or [])} \
                    if old.get("zoom") == z and old.get("size") == (w, h) and old.get("min_dbz", RADAR_MIN_DBZ) == min_dbz else {}
                got = {}
                for fr in reversed(wanted):                         # newest first, so the screen catches up quickly
                    if stop():
                        return
                    if fr["key"] in have:
                        got[fr["key"]] = have[fr["key"]]
                        continue
                    lay = self.radar.layer(fr, lat, lon, z, w, h, stop, min_dbz)
                    if lay is not None:
                        got[fr["key"]] = (fr["time"], lay, fr["kind"], fr["key"], fr["source"])
                    frames = sorted(got.values(), key=lambda f: f[0])
                    st["radar"][name] = {"base": base, "frames": frames, "zoom": z, "size": (w, h), "min_dbz": min_dbz,
                                         "base_size": (w, h, style), "fetched": time.time()}
                frames = sorted(got.values(), key=lambda f: f[0])
                if name == "future":
                    st["errors"]["future"] = "" if frames or not wanted else \
                        "the forecast radar service didn't send any images, so the Future radar screen is skipped for now"
                if not frames and wanted:
                    ok = False
                    # nothing new came back: keep older frames only while they're still recent
                    keep = [f for f in (old.get("frames") or []) if f[0] > time.time() - RADAR_DROP]
                    frames = keep
                st["radar"][name] = {"base": base, "frames": frames, "zoom": z, "size": (w, h), "min_dbz": min_dbz,
                                     "base_size": (w, h, style), "fetched": time.time()}
            if ok:
                st["errors"]["radar"] = ""
            elif not st["errors"].get("radar"):
                st["errors"]["radar"] = "the radar service didn't send any images"
            st["errors"]["map"] = self.radar.map_error
            # a failed refresh tries again soon instead of waiting the full interval
            st["at"]["radar"] = time.time() if ok else time.time() - RADAR_EVERY + RADAR_RETRY

        if (wait and st.get("forecast") is None) or refresh:     # refresh: fetch right now (admin "Check")
            get_forecast()
        if now - st["at"].get("forecast", 0) > (FORECAST_EVERY if st.get("forecast") else 90):
            st["at"]["forecast"] = now
            self._background("fc" + k, get_forecast)
        if loc.get("country") == "US" and cfg.get("alerts", True) and now - st["at"].get("alerts", 0) > ALERTS_EVERY:
            st["at"]["alerts"] = now
            self._background("al" + k, get_alerts)
        if radar and any(x in (cfg.get("slides") or DEFAULT_SLIDES) for x in ("radar_local", "radar_regional", "radar_future")) and \
                now - st["at"].get("radar", 0) > RADAR_EVERY:
            st["at"]["radar"] = now
            self._background(f"rd{k}{light}{map_size}", get_radar)
        return {"location": loc, "imperial": imperial, "forecast": st.get("forecast"), "alerts": st.get("alerts") or [],
                "radar": st.get("radar") or {}, "errors": dict(st["errors"]), "error": ""}

    def reset_radar(self):
        """Refetch maps and radar soon (e.g. after the map key changed)."""
        with self.lock:
            for st in self.data.values():
                st["at"]["radar"] = 0

    def summary(self, ch):
        """One line for the TV page banner and the guide: '72° Sunny · Springfield'."""
        snap = self.snapshot(ch, radar=False)
        fc, loc = snap.get("forecast"), snap.get("location")
        if not fc or not loc:
            return snap.get("error") or "Local weather"
        c = fc["current"]
        return f"{round(c['temp'])}° {describe(c['code'])[0]} · {loc['name']}"


    # ---- for bumpers ("it's {temp} and {conditions} out there")
    def bumper_channel(self):
        chans = [c for c in self.app.store.channels() if c.get("type") == "weather"]
        return next((c for c in chans if c.get("enabled", True)), chans[0] if chans else None)

    def bumper_info(self, clock_fmt="12h"):
        """(values for {weather} etc., set of condition tags like {"rain", "cold"}); ({}, set()) when unknown."""
        ch = self.bumper_channel()
        if not ch:
            return {}, set()
        try:
            snap = self.snapshot(ch, radar=False)
        except Exception as e:
            log.info("weather for bumpers unavailable: %s", e)
            return {}, set()
        fc, loc = snap.get("forecast"), snap.get("location")
        if not fc or not loc or (fc.get("current") or {}).get("temp") is None:
            return {}, set()
        return bumper_values(fc, loc, ch, clock_fmt)


def bumper_values(fc, loc, ch, clock_fmt="12h"):
    imp = fc.get("imperial", True)
    c = fc["current"]
    deg = lambda v: f"{round(v)}°" if v is not None else ""
    cond = describe(c.get("code"))[0].lower()
    off = fc.get("tz_offset")
    today_key = datetime.fromtimestamp(time.time() + (off or 0), tz=timezone.utc).strftime("%Y-%m-%d") if off is not None else None
    days = fc.get("daily") or []
    ti = next((i for i, d in enumerate(days) if d.get("date") == today_key), 0)
    today = days[ti] if days else {}
    tom = days[ti + 1] if len(days) > ti + 1 else {}

    def clock(t):
        from .graphics import fmt_time
        return fmt_time(t, clock_fmt) if t else ""
    temp, wind = c.get("temp"), c.get("wind") or 0
    vals = {
        "temp": deg(temp), "feels_like": deg(c.get("feels")), "conditions": cond,
        "weather": f"{deg(temp)} and {cond}" if cond not in ("—",) else deg(temp),
        "high": deg(today.get("hi")), "low": deg(today.get("lo")),
        "rain_chance": f"{round(today.get('pop') or 0)}%",
        "wind": f"{round(wind)} {'mph' if imp else 'km/h'}",
        "humidity": f"{round(c.get('humidity') or 0)}%",
        "tomorrow": describe(tom.get("code"))[0].lower() if tom else "",
        "tomorrow_high": deg(tom.get("hi")) if tom else "",
        "sunset": clock(today.get("sunset")), "sunrise": clock(today.get("sunrise")),
        "city": loc.get("name") or "", "weather_channel": ch.get("name") or "", "weather_number": str(ch.get("number") or ""),
    }
    code = int(c.get("code") or 0)
    f = temp if imp else (temp * 9 / 5 + 32 if temp is not None else None)
    mph = wind if imp else wind / 1.609
    tags = set()
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        tags.add("rain")
    if code in (71, 73, 75, 77, 85, 86):
        tags.add("snow")
    if code >= 95:
        tags.update(("storm", "rain"))
    if code in (0, 1):
        tags.add("clear")
    if code in (2, 3, 45, 48):
        tags.add("cloudy")
    if code in (45, 48):
        tags.add("fog")
    if f is not None:
        if f >= 85:
            tags.add("hot")
        if f <= 40:
            tags.add("cold")
        if f <= 32:
            tags.add("freezing")
        if 62 <= f <= 80 and code <= 2:
            tags.add("nice")
    if mph >= 20:
        tags.add("windy")
    return vals, tags


DEFAULT_SLIDES = ["current", "hourly", "daily", "radar_local", "radar_regional", "radar_future", "almanac", "alerts"]

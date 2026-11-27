"""M3U playlist, XMLTV guide data and HDHomeRun emulation, so Jellyfin (or Plex/Emby/any IPTV app) can tune in."""
import time
from datetime import datetime, timezone
from xml.sax.saxutils import escape, quoteattr

from .graphics import program_label
from . import branding


def _xmltime(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y%m%d%H%M%S +0000")


def tvg_id(ch):
    return f"jfb-{ch['id']}"


def content_channels(app):
    """Channels handed to Jellyfin / IPTV apps. With the lock on (and 'hide' chosen), only kids channels."""
    chans = [c for c in app.store.channels() if c.get("enabled", True)]
    if app.lock.enabled and app.store.settings.get("lock_hide_in_jellyfin"):
        chans = [c for c in chans if not app.lock.is_locked(c)]
    return chans


def stream_url(app, base, ch):
    # the private tuner key lets Jellyfin play locked channels without a code (it can't show a code prompt)
    return f"{base}/stream/{ch['id']}.ts?k={app.lock.tuner_key}"


def m3u(app, base):
    lines = [f'#EXTM3U url-tvg="{base}/iptv/xmltv.xml" x-tvg-url="{base}/iptv/xmltv.xml"']
    for ch in content_channels(app):
        group = ch.get("group") or {"guide": "Guide", "weather": "Weather"}.get(ch.get("type"), "Broadcast")
        name = ch["name"].replace(",", " ")
        lines.append(f'#EXTINF:-1 tvg-id="{tvg_id(ch)}" tvg-chno="{ch["number"]}" tvg-name="{name}" '
                     f'tvg-logo="{base}/logos/{ch["id"]}.png" group-title="{group}",{name}')
        lines.append(stream_url(app, base, ch))
    return "\n".join(lines) + "\n"


SPECIAL = ("guide", "weather")      # channel types with no schedule of their own


def weather_entries(app, ch, t0, t1):
    """The weather channel's listings: hour-long 'Local Weather' blocks showing the current conditions."""
    try:
        summary = app.weather.summary(ch)
    except Exception:
        summary = "Local Weather"
    start = t0 - (t0 % 3600)
    out = []
    while start < t1:
        out.append({"s": start, "d": 3600, "k": "program",
                    "i": {"id": "weather", "title": "Local Weather", "type": "Weather", "summary": summary,
                          "overview": "Current conditions, the next 12 hours, the 7-day forecast, radar and alerts.",
                          "genres": ["Weather"]}})
        start += 3600
    return out


def channel_entries(app, ch, t0, t1):
    """What a channel shows between t0 and t1, as guide entries (shows folded together with their breaks)."""
    if ch.get("type") == "guide":
        return []
    if ch.get("type") == "weather":
        return weather_entries(app, ch, t0, t1)
    return merged_programs(app.sched.entries_between(ch, t0, t1))


def merged_programs(entries):
    """Fold commercials, bumpers, filler and the later parts of a show (after a break) into the program they
    belong to - exactly how a real TV guide lists it."""
    out = []
    for e in entries:
        if (e["k"] == "program" and not e.get("p")) or not out:
            out.append(dict(e))
        else:
            out[-1]["d"] = e["s"] + e["d"] - out[-1]["s"]
    return out


def xmltv(app, base):
    st = app.store.settings
    now = time.time()
    t0, t1 = now - 2 * 3600, now + float(st.get("epg_hours") or 48) * 3600
    chans = content_channels(app)
    x = ['<?xml version="1.0" encoding="UTF-8"?>',
         f'<tv generator-info-name={quoteattr(branding.name())} source-info-name={quoteattr(branding.name())}>']
    for ch in chans:
        x.append(f'  <channel id="{tvg_id(ch)}">')
        x.append(f"    <display-name>{escape(ch['name'])}</display-name>")
        x.append(f"    <display-name>{escape(str(ch['number']))}</display-name>")
        x.append(f'    <icon src="{base}/logos/{ch["id"]}.png"/>')
        x.append("  </channel>")
    for ch in chans:
        cid = tvg_id(ch)
        if ch.get("type") == "guide":
            start = t0 - (t0 % 3600)
            while start < t1:
                x.append(f'  <programme start="{_xmltime(start)}" stop="{_xmltime(start + 3600)}" channel="{cid}">')
                x.append(f"    <title>{escape(ch['name'])}</title>")
                x.append("    <desc>What's on right now, across every channel.</desc>")
                x.append("  </programme>")
                start += 3600
            continue
        try:
            entries = channel_entries(app, ch, t0, t1)
        except Exception:
            entries = []
        for e in entries:
            it = e.get("i") or {}
            title, sub = program_label(it) if e["k"] == "program" else ("Station Break", "")
            x.append(f'  <programme start="{_xmltime(e["s"])}" stop="{_xmltime(e["s"] + e["d"])}" channel="{cid}">')
            x.append(f"    <title>{escape(title)}</title>")
            if it.get("type") == "Episode" and it.get("episode_title"):
                x.append(f"    <sub-title>{escape(it['episode_title'])}</sub-title>")
            if it.get("type") == "Weather":
                x.append(f"    <desc>{escape(it.get('summary') or '')}. {escape(it['overview'])}</desc>")
                x.append("    <category>Weather</category>")
            elif it.get("overview"):
                x.append(f"    <desc>{escape(it['overview'])}</desc>")
            if it.get("year"):
                x.append(f"    <date>{it['year']}</date>")
            if it.get("type") == "Movie":
                x.append("    <category>Movie</category>")
            elif it.get("type") == "Episode":
                x.append("    <category>Series</category>")
            for g in it.get("genres", []):
                x.append(f"    <category>{escape(g)}</category>")
            if it.get("image_id"):
                x.append(f'    <icon src="{base}/img/{it["image_id"]}.jpg"/>')
            if it.get("type") == "Episode" and it.get("season") is not None and it.get("episode") is not None:
                x.append(f'    <episode-num system="xmltv_ns">{max(0, it["season"] - 1)}.{max(0, it["episode"] - 1)}.</episode-num>')
                x.append(f'    <episode-num system="onscreen">S{it["season"]:02d}E{it["episode"]:02d}</episode-num>')
            if it.get("rating"):
                x.append(f"    <rating><value>{escape(it['rating'])}</value></rating>")
            x.append("    <previously-shown/>")
            x.append("  </programme>")
    x.append("</tv>")
    return "\n".join(x) + "\n"


# ---------------- HDHomeRun emulation (optional; Jellyfin's M3U tuner is the simplest route)

def hdhr_discover(app, base):
    n = max(2, len(content_channels(app)))
    return {"FriendlyName": branding.name(),
            "Manufacturer": "Silicondust", "ModelNumber": "HDTC-2US", "FirmwareName": "hdhomeruntc_atsc",
            "FirmwareVersion": "20200101", "DeviceID": "1F0B0ADC", "DeviceAuth": "jellyfinbroadcast",
            "TunerCount": n, "BaseURL": base, "LineupURL": f"{base}/lineup.json"}


def hdhr_lineup(app, base):
    return [{"GuideNumber": str(c["number"]), "GuideName": c["name"], "URL": stream_url(app, base, c)}
            for c in content_channels(app)]


def hdhr_device_xml(app, base):
    d = hdhr_discover(app, base)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
  <specVersion><major>1</major><minor>0</minor></specVersion>
  <URLBase>{base}</URLBase>
  <device>
    <deviceType>urn:schemas-upnp-org:device:MediaServer:1</deviceType>
    <friendlyName>{escape(d['FriendlyName'])}</friendlyName>
    <manufacturer>Silicondust</manufacturer>
    <modelName>HDTC-2US</modelName>
    <modelNumber>HDTC-2US</modelNumber>
    <serialNumber>{d['DeviceID']}</serialNumber>
    <UDN>uuid:{d['DeviceID']}</UDN>
  </device>
</root>"""

"""HTTP server: admin API + UI, the TV web player, live streams, M3U/XMLTV and HDHomeRun endpoints."""
import base64
import json
import logging
import mimetypes
import queue
import re
import subprocess
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__, branding, epg, fontlib, themes
from .config import NO_WINDOW, SCHEDULE_KEYS
from .graphics import default_logo, normalize_logo, program_label
from .jellyfin import Jellyfin, JellyfinError

log = logging.getLogger("http")
WEB = Path(__file__).resolve().parent.parent / "web"
MASK = "••••••••"
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/manifest+json", ".webmanifest")


def entry_json(e):
    if not e:
        return None
    title, sub = program_label(e.get("i")) if e["k"] == "program" or e["k"] == "filler" else (
        "No programming" if e.get("msg") == "nocontent" else "Station Break", "")
    it = e.get("i") or {}
    return {"start": e["s"], "end": e["s"] + e["d"], "kind": e["k"], "title": title, "subtitle": sub,
            "overview": it.get("overview", ""), "image": f"/img/{it['image_id']}.jpg" if it.get("image_id") else None,
            "type": it.get("type"), "rating": it.get("rating", ""), "year": it.get("year"), "slot": e.get("slot")}


class Handler(BaseHTTPRequestHandler):
    server_version = f"BarnesTV/{__version__}"
    protocol_version = "HTTP/1.1"
    app = None  # set by serve()

    def log_message(self, fmt, *args):
        log.debug("%s %s", self.address_string(), fmt % args)

    # ------------------------------------------------------------------ helpers
    @property
    def base(self):
        pub = (self.app.store.settings.get("public_url") or "").rstrip("/")
        if pub:
            return pub
        host = self.headers.get("Host")
        return f"http://{host}" if host else self.app.default_base()

    def send(self, code, body=b"", ctype="application/json", headers=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def json(self, obj, code=200):
        self.send(code, json.dumps(obj, default=str))

    def error(self, code, msg):
        self.json({"error": msg}, code)

    def body(self):
        # cached, and always read before any reply: an unread body would corrupt the next request on a kept-alive
        # connection (e.g. a refused save followed by the unlock request)
        if not hasattr(self, "_body"):
            n = int(self.headers.get("Content-Length") or 0)
            self._body = self.rfile.read(n) if n else b""
        return self._body

    def body_json(self):
        raw = self.body()
        return json.loads(raw) if raw else {}

    def authorized(self):
        pw = self.app.store.settings.get("admin_password") or ""
        if not pw:
            return True
        h = self.headers.get("Authorization", "")
        if h.startswith("Basic "):
            try:
                _, _, given = base64.b64decode(h[6:]).decode().partition(":")
                if given == pw:
                    return True
            except Exception:
                pass
        self.send(401, "Login required", "text/plain",
                  {"WWW-Authenticate": f'Basic realm="{branding.short().replace(chr(34), "")}"'})
        return False

    def static(self, rel):
        p = (WEB / rel).resolve()
        if WEB not in p.parents and p != WEB or not p.is_file():
            return self.error(404, "not found")
        ctype = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
        self.send(200, p.read_bytes(), ctype + ("; charset=utf-8" if ctype.startswith("text") else ""),
                  {"Cache-Control": "no-cache"})

    # ------------------------------------------------------------------ routing
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        self.__dict__.pop("_body", None)
        try:
            self.route("GET")
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as e:
            log.exception("GET %s failed", self.path)
            try:
                self.error(500, str(e))
            except Exception:
                pass

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        self._mut("POST")

    def do_PUT(self):
        self._mut("PUT")

    def do_DELETE(self):
        self._mut("DELETE")

    def unlock_token(self, qs=None):
        return self.headers.get("X-Unlock") or (qs or {}).get("unlock") or ""

    def locked_response(self, msg="This channel is locked"):
        self.json({"error": msg, "locked": True}, 403)

    def _mut(self, method):
        try:
            self.__dict__.pop("_body", None)    # one handler serves every request on a kept-alive connection
            self.body()
            if self.path.startswith("/lineup.post"):
                return self.json({})
            if self.path.startswith("/api/client-log"):
                return self.client_log()
            open_paths = ("/api/cast/", "/api/lock/")
            if not self.path.startswith(open_paths):
                if not self.authorized():
                    return
                # with the channel lock on and no admin password, changing anything needs the lock code
                lk = self.app.lock
                if (lk.enabled and not self.app.store.settings.get("admin_password") and not lk.valid(self.unlock_token())
                        and not self.path.startswith(("/api/themes/preview", "/api/bumpers/render"))):    # previews change nothing
                    return self.locked_response("Enter the channel lock code to change settings")
            self.route(method)
        except JellyfinError as e:
            self.error(502, str(e))
        except Exception as e:
            log.exception("%s %s failed", method, self.path)
            self.error(500, str(e))

    def route(self, method):
        url = urllib.parse.urlparse(self.path)
        path, qs = url.path, {k: v[-1] for k, v in urllib.parse.parse_qs(url.query).items()}
        app = self.app
        if method == "GET":
            if path in ("/", "/index.html"):
                return self.authorized() and self.page("index.html")
            if path in ("/tv", "/tv/", "/watch", "/remote", "/remote/"):
                mode = "remote" if path.startswith("/remote") else "tv"
                return self.page("tv.html", mode)
            # branding: the artwork and icons follow Appearance -> Branding (the Barnes files are the default)
            if path in ("/favicon.ico", "/favicon.png", "/favicon.svg"):
                return self.brand_file("favicon")
            m = re.fullmatch(r"/(?:static/)?brand/(barnes-wordmark|orbital-b|wordmark|mark)\.png", path)
            if m:
                return self.brand_file({"barnes-wordmark": "wordmark", "orbital-b": "mark"}.get(m.group(1), m.group(1)))
            m = re.fullmatch(r"/static/icon-(192|512)\.png", path)
            if m:
                return self.brand_file("icon", int(m.group(1)))
            m = re.fullmatch(r"/static/(tv|remote)\.webmanifest", path)
            if m:
                return self.manifest(m.group(1))
            if path == "/api/brand/tvapp-kit.zip":
                return self.send(200, branding.tvapp_kit(), "application/zip",
                                 {"Content-Disposition": 'attachment; filename="tv-app-branding.zip"', "Cache-Control": "no-cache"})
            if path.startswith("/static/"):
                return self.static(path[len("/static/"):])
            if path in ("/app", "/app/"):
                return self.send(200, self.app_page(), "text/html; charset=utf-8", {"Cache-Control": "no-cache"})
            if path in ("/app/BarnesTV.apk", "/BarnesTV.apk", "/app.apk"):
                apk = WEB / "app" / "BarnesTV.apk"
                if not apk.is_file():
                    return self.error(404, "The TV app hasn't been built yet - see /app")
                return self.send(200, apk.read_bytes(), "application/vnd.android.package-archive",
                                 {"Content-Disposition": 'attachment; filename="BarnesTV.apk"', "Cache-Control": "no-cache"})
            if path == "/api/tvapp/hello":      # how the TV app finds this server on the network
                return self.json({"app": "barnes-tv", "name": branding.name(),
                                  "version": __version__, "tv": "/tv?app=1"})
            if path == "/theme.css":
                T = themes.get(qs.get("theme") or app.store.settings.get("theme"))
                css = themes.css(T, qs.get("font") or app.store.settings.get("ui_font"))
                if not branding.recolor():      # full-colour logos: never tint or darken them
                    css += "\n.brandart { filter: none !important; }\n"
                return self.send(200, css, "text/css; charset=utf-8", {"Cache-Control": "no-cache"})
            m = re.fullmatch(r"/fonts/custom/([^/\\]+\.(?:ttf|otf|TTF|OTF))", path)
            if m:
                f = (app.store.data_dir / "fonts" / urllib.parse.unquote(m.group(1)))
                if f.is_file() and f.parent == app.store.data_dir / "fonts":
                    return self.send(200, f.read_bytes(), "font/ttf", {"Cache-Control": "max-age=3600"})
                return self.error(404, "not found")
            m = re.fullmatch(r"/fonts/([A-Za-z0-9_.-]+\.ttf)", path)
            if m:
                f = WEB / "fonts" / m.group(1)
                if f.is_file():
                    return self.send(200, f.read_bytes(), "font/ttf", {"Cache-Control": "max-age=604800"})
                return self.error(404, "not found")
            if path in ("/iptv/channels.m3u", "/channels.m3u", "/playlist.m3u", "/iptv.m3u"):
                return self.send(200, epg.m3u(app, self.base), "audio/x-mpegurl; charset=utf-8")
            if path in ("/iptv/xmltv.xml", "/xmltv.xml", "/epg.xml"):
                return self.send(200, epg.xmltv(app, self.base), "application/xml; charset=utf-8")
            if path == "/discover.json":
                return self.json(epg.hdhr_discover(app, self.base))
            if path == "/lineup.json":
                return self.json(epg.hdhr_lineup(app, self.base))
            if path == "/lineup_status.json":
                return self.json({"ScanInProgress": 0, "ScanPossible": 1, "Source": "Cable", "SourceList": ["Cable"]})
            if path == "/device.xml":
                return self.send(200, epg.hdhr_device_xml(app, self.base), "application/xml")
            m = re.fullmatch(r"/stream/([^/]+?)(?:\.ts)?", path)
            if m:
                return self.stream(m.group(1), qs)
            m = re.fullmatch(r"/hls/([^/]+)/([A-Za-z0-9_.-]+)", path)
            if m:
                return self.hls(m.group(1), m.group(2), qs)
            m = re.fullmatch(r"/logos/([^/]+?)\.png", path)
            if m:
                return self.logo(m.group(1))
            m = re.fullmatch(r"/img/([0-9a-fA-F-]+)\.jpg", path)
            if m:
                return self.image(m.group(1), int(qs.get("h", 360)))
        if path.startswith("/api/"):
            return self.api(method, path[5:], qs)
        self.error(404, "not found")

    # ------------------------------------------------------------------ streaming
    def stream(self, key, qs=None):
        ch = self.app.store.channel(key)
        if not ch or not ch.get("enabled", True):
            return self.error(404, "no such channel")
        if not self.app.lock.allowed(ch, self.unlock_token(qs), (qs or {}).get("k")):
            return self.locked_response()
        if self.command == "HEAD":
            self.send_response(200)
            self.send_header("Content-Type", "video/mp2t")
            self.end_headers()
            return
        session = self.app.sessions.get(ch)
        q = session.broadcast.subscribe()
        self.close_connection = True
        try:
            self.send_response(200)
            self.send_header("Content-Type", "video/mp2t")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            log.info("viewer %s tuned to %s %s", self.client_address[0], ch["number"], ch["name"])
            while True:
                try:
                    chunk = q.get(timeout=20)
                except queue.Empty:
                    if not session.is_alive():
                        break
                    continue
                if chunk is None:
                    break
                self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            session.broadcast.unsubscribe(q)
            log.info("viewer %s left %s", self.client_address[0], ch["name"])

    def client_log(self):
        """The browser TV page reports player errors here so they show up in broadcast.log."""
        try:
            d = self.body_json()
        except Exception:
            d = {}
        level = log.info if d.get("type") == "note" else log.warning
        level("%s (%s) on channel %s: %s", "TV app" if d.get("app") else "browser player", self.client_address[0],
              str(d.get("channel", "?"))[:20], " | ".join(str(d.get(k, ""))[:300] for k in ("type", "detail", "info") if d.get(k)))
        self.json({"ok": True})

    HLS_TYPES = {".m3u8": "application/vnd.apple.mpegurl", ".m4s": "video/mp4", ".mp4": "video/mp4",
                 ".ts": "video/mp2t"}

    def hls(self, key, name, qs=None):
        ch = self.app.store.channel(key)
        if not ch or not ch.get("enabled", True):
            return self.error(404, "no such channel")
        cors = {"Access-Control-Allow-Origin": "*", "Access-Control-Expose-Headers": "Content-Length"}
        qs = qs or {}
        lk = self.app.lock
        token, key = self.unlock_token(qs), qs.get("k")
        if not lk.allowed(ch, token, key):
            return self.send(403, json.dumps({"error": "This channel is locked", "locked": True}), "application/json", cors)
        # carry the credential on to the playlist / segment links (they're relative)
        cred = ("?k=" + urllib.parse.quote(key)) if lk.key_ok(key) else ("?unlock=" + urllib.parse.quote(token)) if token else ""
        ext = name[name.rfind("."):].lower() if "." in name else ""
        if ext not in self.HLS_TYPES:
            return self.error(404, "not found")
        self.app.hls.note(self.client_address[0], ch["id"], name)
        if name in ("index.m3u8", "master.m3u8"):
            self.app.hls.ensure(ch)
            from .hls import master_playlist
            return self.send(200, master_playlist(self.app.store.settings).replace("live.m3u8", "live.m3u8" + cred),
                             self.HLS_TYPES[".m3u8"], dict(cors, **{"Cache-Control": "no-cache"}))
        if name == "live.m3u8":
            stream = self.app.hls.ensure(ch)
            deadline = time.time() + 25
            while not stream.ready() and time.time() < deadline and stream.alive:
                time.sleep(0.25)
            if not stream.ready():
                return self.send(503, "stream is starting, try again", "text/plain", cors)
        else:
            stream = self.app.hls.get(ch["id"])
            if not stream:
                return self.send(404, "no such segment", "text/plain", cors)
            stream.touch()
        p = stream.dir / name
        data = None
        for _ in range(8):   # the playlist is replaced atomically every couple of seconds; retry a brief clash
            try:
                data = p.read_bytes()
                break
            except FileNotFoundError:
                break
            except OSError:
                time.sleep(0.05)
        if data is None:
            return self.send(404, "no such segment", "text/plain", cors)
        if name == "live.m3u8":
            from .hls import hold_back
            text = hold_back(data.decode("utf-8", "replace"))
            if cred:
                text = "\n".join((l + cred) if l and not l.startswith("#") else
                                  l.replace('URI="init.mp4"', f'URI="init.mp4{cred}"') for l in text.splitlines()) + "\n"
            data = text.encode("utf-8")
        cache = "no-cache" if ext == ".m3u8" else "max-age=60"
        self.send(200, data, self.HLS_TYPES[ext], dict(cors, **{"Cache-Control": cache}))

    def cast_api(self, method, action):
        cm = self.app.cast
        if action == "devices" and method == "GET":
            return self.json({"available": cm.available, "error": cm.error, "devices": cm.devices(),
                              "base_url": cm.base_url()})
        data = self.body_json() if method == "POST" else {}
        dev = data.get("device") or ""
        try:
            if action == "play" and method == "POST":
                ch = self.app.store.channel(str(data.get("channel", "")))
                if not ch:
                    return self.error(404, "no such channel")
                if not self.app.lock.allowed(ch, self.unlock_token()):
                    return self.locked_response()
                return self.json(cm.play(dev, ch))
            if action == "stop" and method == "POST":
                return self.json(cm.stop(dev))
            if action == "reload" and method == "POST":
                return self.json(cm.reload(dev))
            if action == "volume" and method == "POST":
                return self.json(cm.volume(dev, data.get("delta"), data.get("mute"), data.get("level")))
        except Exception as e:
            log.warning("cast %s failed: %s", action, e)
            return self.error(502, str(e))
        self.error(404, "unknown cast action")

    def logo(self, key):
        ch = self.app.store.channel(key)
        if not ch:
            return self.error(404, "no such channel")
        p = self.app.store.data_dir / "logos" / f"{ch['id']}.png"
        if (ch.get("logo") or {}).get("file") and p.exists():
            return self.send(200, p.read_bytes(), "image/png", {"Cache-Control": "max-age=60"})
        self.send(200, default_logo(self.app.fonts(), ch), "image/png", {"Cache-Control": "max-age=60"})

    def image(self, item_id, h):
        h = max(60, min(h, 1080))
        p = self.app.store.data_dir / "images" / f"{item_id}-{h}.jpg"
        if not p.exists():
            jf = self.app.sched.jellyfin()
            try:
                data = jf.fetch_bytes(jf.image_url(item_id, "Primary", h))
                p.write_bytes(data)
            except Exception:
                return self.error(404, "no image")
        self.send(200, p.read_bytes(), "image/jpeg", {"Cache-Control": "max-age=86400"})

    # ------------------------------------------------------------------ API
    def api(self, method, path, qs):
        app, store, sched = self.app, self.app.store, self.app.sched
        public_get = method == "GET" and (path in ("channels", "guide") or path.startswith("channels/")
                                          and path.endswith("/schedule"))
        if path.startswith("cast/"):
            return self.cast_api(method, path[5:])
        if path.startswith("lock/"):
            return self.lock_api(method, path[5:])
        if not public_get and not self.authorized():
            return
        if path == "brand" and method == "GET":
            return self.json(branding.public())
        m = re.fullmatch(r"brand/(wordmark|mark|icon)", path)
        if m and method in ("POST", "DELETE"):
            try:
                if method == "POST":
                    branding.save_upload(m.group(1), self.body())
                else:
                    branding.remove(m.group(1))
            except Exception as e:
                return self.error(400, f"That doesn't look like an image ({e})")
            app.brand_changed()
            return self.json(branding.public())
        if path == "brand/reset" and method == "POST":
            for k in branding.KINDS:
                branding.remove(k)
            store.update_settings({"station_name": "", "station_short": "", "brand_color": "", "brand_recolor": None})
            app.brand_changed()
            return self.json(branding.public())
        if path == "status" and method == "GET":
            st = store.settings
            return self.json({"version": __version__, "brand": branding.public(), "started": app.started, "ffmpeg": app.ffmpeg_info(), "fonts": app.font_paths(),
                              "base_url": self.base, "configured": bool(st.get("jellyfin_api_key")),
                              "sessions": app.sessions.status(), "time": time.time()})
        m = re.fullmatch(r"commercials/([A-Za-z0-9_-]+)/(rescan|mode|thumb\.jpg)", path)
        if m:
            return self.commercial_api(method, m.group(1), m.group(2), qs)
        if path == "server/restart" and method == "POST":
            log.info("restart requested from %s", self.client_address[0])
            app.restart()
            return self.json({"ok": True, "started": app.started})
        if path == "themes" and method == "GET":
            from .graphics import CLOCK_FORMATS
            st = store.settings
            return self.json({"themes": themes.public_list(), "fonts": fontlib.public_list(),
                              "clock_formats": CLOCK_FORMATS, "current": st.get("theme"), "ui_font": st.get("ui_font"),
                              "fonts_folder": str(store.data_dir / "fonts")})
        m = re.fullmatch(r"themes/([a-z0-9_-]+)/(guide|slate)\.jpg", path)
        if m and method == "GET":
            return self.theme_preview(m.group(1), m.group(2), qs)
        m = re.fullmatch(r"themes/([a-z0-9_-]+)/spec", path)
        if m and method == "GET":       # a theme in the builder's format (built-in ones as a starting point)
            if m.group(1) in themes.CUSTOM:
                return self.json(themes.CUSTOM[m.group(1)])
            return self.json(themes.builtin_spec(m.group(1)))
        m = re.fullmatch(r"themes/preview/(guide|slate)\.jpg", path)
        if m and method == "POST":      # live preview of an unsaved theme from the builder
            return self.theme_preview(None, m.group(1), qs, themes.normalize(self.body_json()))
        if path == "themes/preview.css" and method == "POST":
            T = themes.Theme(spec=themes.normalize(self.body_json()))
            return self.send(200, themes.css(T, store.settings.get("ui_font")), "text/css; charset=utf-8")
        if path == "themes/custom" and method == "POST":
            spec = store.save_theme(self.body_json())
            if self.body_json().get("use"):
                store.update_settings({"theme": spec["id"]})
            return self.json(spec)
        m = re.fullmatch(r"themes/custom/([a-z0-9_-]+)", path)
        if m and method == "DELETE":
            store.delete_theme(m.group(1))
            return self.json({"ok": True})
        if path == "settings":
            if method == "GET":
                st = store.settings
                if st.get("jellyfin_api_key"):
                    st["jellyfin_api_key"] = MASK
                if st.get("admin_password"):
                    st["admin_password"] = MASK
                if st.get("map_api_key"):
                    st["map_api_key"] = MASK
                st["lock_has_code"] = bool(st.pop("lock_code_hash", ""))
                for k in ("lock_salt", "tuner_key"):
                    st.pop(k, None)
                return self.json(st)
            patch = self.body_json()
            for k in ("jellyfin_api_key", "admin_password", "map_api_key"):
                if patch.get(k) == MASK:
                    patch.pop(k)
            for k in ("lock_code_hash", "lock_salt", "tuner_key", "lock_has_code"):
                patch.pop(k, None)
            new_code = str(patch.pop("lock_new_code", "") or "").strip()
            if new_code:
                try:
                    app.lock.set_code(new_code)
                except ValueError as e:
                    return self.error(400, str(e))
            if patch.get("lock_enabled") and not store.settings.get("lock_code_hash"):
                return self.error(400, "Choose a lock code before turning the channel lock on")
            old = store.settings
            store.update_settings(patch)
            if any(old.get(k) != store.settings.get(k) for k in ("station_name", "station_short", "brand_color", "brand_recolor")):
                app.brand_changed()
            if old.get("map_api_key") != store.settings.get("map_api_key"):
                app.weather.reset_radar()
            if any(old.get(k) != store.settings.get(k) for k in ("resolution", "framerate", "video_encoder",
                                                                  "encoder_preset", "video_bitrate_kbps")):
                app.sessions.stop_all()  # encoder changes need a fresh stream
            return self.json({"ok": True})
        if path == "settings/test" and method == "POST":
            data = self.body_json()
            st = store.settings
            key = data.get("jellyfin_api_key") or ""
            if not key or key == MASK:
                key = st.get("jellyfin_api_key")
            jf = Jellyfin(data.get("jellyfin_url") or st["jellyfin_url"], key, data.get("jellyfin_user_id") or "")
            info = jf.system_info()
            users = [{"id": u["Id"], "name": u["Name"], "admin": (u.get("Policy") or {}).get("IsAdministrator")}
                     for u in jf.users()]
            return self.json({"ok": True, "server": info.get("ServerName"), "version": info.get("Version"),
                              "os": info.get("OperatingSystem") or info.get("OperatingSystemDisplayName"),
                              "users": users})
        if path == "jellyfin/sources":
            return self.json(sched.jellyfin().list_sources(qs.get("type", "library"), qs.get("q", "")))
        if path == "jellyfin/episodes":       # what a source holds, in order (marathon "start with" picker)
            from .jellyfin import normalize_item
            from .scheduler import _ep_label, sort_key
            raw = sched.jellyfin().resolve_source({"type": qs.get("type", "series"), "id": qs.get("id", "")},
                                                  ["Movie", "Episode", "MusicVideo", "Video"])
            its = [normalize_item(r) for r in raw]
            its = [i for i in its if i["duration"] >= 5 and i["location"] != "Virtual"]
            if qs.get("type") != "playlist":
                its.sort(key=sort_key)
            return self.json([{"id": i["id"], "label": (f"{_ep_label(i)} · {i.get('episode_title') or i['title']}"
                                                         if i["type"] == "Episode" else i["title"]),
                               "minutes": round(i["duration"] / 60)} for i in its[:3000]])
        if path == "guide":
            hours = min(12.0, float(qs.get("hours", 3)))
            now = time.time()
            t0 = float(qs.get("start") or now - ((now + time.localtime(now).tm_gmtoff) % 1800))
            out = []
            for ch in store.channels():
                if not ch.get("enabled", True):
                    continue
                entries = epg.channel_entries(app, ch, t0, t0 + hours * 3600, wait=False)
                out.append({"id": ch["id"], "number": ch["number"], "name": ch["name"], "type": ch["type"],
                            "locked": app.lock.is_locked(ch),
                            "logo": f"/logos/{ch['id']}.png", "entries": [entry_json(e) for e in entries]})
            return self.json({"start": t0, "end": t0 + hours * 3600, "now": now, "channels": out})
        if path == "bumpers" or path.startswith("bumpers/"):
            return self.bumper_api(method, path[len("bumpers"):].strip("/"), qs)
        if path == "channels":
            if method == "GET":
                return self.json([self.channel_summary(c) for c in store.channels()])
            if method == "POST":
                ch = store.add_channel(self.body_json())
                return self.json(self.channel_summary(ch, deep=False))
        m = re.fullmatch(r"channels/([^/]+)(?:/(.+))?", path)
        if m:
            return self.channel_api(method, m.group(1), m.group(2) or "", qs)
        self.error(404, "unknown endpoint")

    def lock_api(self, method, action):
        lk = self.app.lock
        token = self.unlock_token()
        if action == "status" and method == "GET":
            return self.json({"enabled": lk.enabled, "unlocked": lk.valid(token), "until": lk.expiry(token),
                              "minutes": self.app.store.settings.get("lock_unlock_minutes")})
        if action == "unlock" and method == "POST":
            code = str(self.body_json().get("code", "")).strip()
            try:
                tok, until = lk.unlock(code, self.client_address[0])
            except PermissionError as e:
                return self.json({"error": str(e)}, 403)
            return self.json({"ok": True, "token": tok, "until": until})
        if action == "lock" and method == "POST":
            lk.relock(token)
            return self.json({"ok": True})
        self.error(404, "unknown lock action")

    SAMPLE_CTX = {"show": "Cosmic Diner", "episode": "The One With The Toaster", "next": "Midnight Mysteries"}
    SAMPLE_WEATHER = {"weather": "41° and light rain", "temp": "41°", "feels_like": "35°", "conditions": "light rain",
                      "high": "46°", "low": "33°", "rain_chance": "80%", "wind": "14 mph", "humidity": "88%",
                      "tomorrow": "partly cloudy", "tomorrow_high": "52°", "sunset": "4:31 PM", "sunrise": "6:58 AM",
                      "city": "Springfield", "weather_channel": "Weather Now", "weather_number": "11"}

    def bumper_api(self, method, rest, qs=None):
        store = self.app.store
        if not rest:
            if method == "GET":
                from .graphics import bumper_needs_weather
                return self.json([dict(b, duration=store.bumper_duration(b), weather=bumper_needs_weather(b))
                                  for b in store.bumpers()])
            if method == "POST":
                data = self.body_json()
                is_new = not data.get("id") or store.bumper(data["id"]) is None
                b = store.save_bumper(data)
                if is_new:
                    self._reschedule_bumper_channels()
                return self.json(dict(b, duration=store.bumper_duration(b)))
        if rest == "render" and method == "POST":
            data = self.body_json()
            b = store._norm_bumper(data.get("bumper") or {})
            n = max(0, min(int(data.get("card") or 0), len(b["cards"]) - 1))
            ch = store.channel(data.get("channel") or "") or {"name": "Toon TV", "number": 7}
            from .graphics import bumper_vars, render_bumper_card
            live = self.app.weather.bumper_info()[0]
            values = bumper_vars(dict(self.SAMPLE_CTX, next_start=time.time() + 300), ch,
                                 store.settings.get("station_name"), weather=dict(self.SAMPLE_WEATHER, **live))
            img = render_bumper_card(self.app.fonts(), 960, 540, b, b["cards"][n]["text"], values)
            import io as _io
            buf = _io.BytesIO()
            img.save(buf, "PNG")
            return self.send(200, buf.getvalue(), "image/png")
        if rest == "music_check" and method == "GET":    # is this music path usable on the server?
            from .streamer import AUDIO_EXT
            p = Path(((qs or {}).get("path") or "").strip().strip('"'))
            if not str(p) or str(p) == ".":
                return self.json({"kind": "none"})
            from . import loudness
            lv = {}
            if p.is_file() or p.is_dir():
                if store.settings.get("music_match_loudness", True):
                    loudness.prewarm([str(p)])          # start measuring right away
                done, total = loudness.status(str(p))
                lv = {"measured": done, "measurable": total}
            if p.is_file():
                return self.json({"kind": "file", "ok": p.suffix.lower() in AUDIO_EXT, "name": p.name, **lv})
            if p.is_dir():
                n = 0
                for f in p.rglob("*"):
                    if f.suffix.lower() in AUDIO_EXT:
                        n += 1
                        if n >= 5000:
                            break
                return self.json({"kind": "folder", "ok": n > 0, "files": n, **lv})
            return self.json({"kind": "missing", "ok": False})
        if rest == "packs" and method == "GET":
            from .graphics import bumper_needs_weather
            wx = self.app.weather.bumper_channel()
            values, tags = self.app.weather.bumper_info()
            return self.json({"missing": store.missing_pack_bumpers(), "weather_channel": bool(wx),
                              "weather_now": sorted(tags), "weather_values": values,
                              "weather_bumpers": sum(1 for b in store.bumpers() if bumper_needs_weather(b))})
        if rest == "restore" and method == "POST":
            n = store.restore_pack_bumpers()
            if n:
                self._reschedule_bumper_channels()
            return self.json({"restored": n})
        if method == "DELETE" and rest:
            store.delete_bumper(rest)
            self._reschedule_bumper_channels()
            return self.json({"ok": True})
        self.error(404, "unknown bumper endpoint")

    def _reschedule_bumper_channels(self):
        """New or deleted bumpers: re-plan the future (after the current show) of channels that use bumpers."""
        self.app.sched._bump_cache = None
        for ch in self.app.store.channels():
            if (ch.get("bumpers") or {}).get("enabled") and ch.get("type") not in epg.SPECIAL:
                try:
                    self.app.sched.reset(ch, keep_current=True)
                except Exception as e:
                    log.info("reschedule after bumper change failed for %s: %s", ch["name"], e)

    def channel_summary(self, ch, deep=True):
        out = dict(ch)
        out["logo_url"] = f"/logos/{ch['id']}.png?v={int(time.time() // 30)}"
        out["stream_url"] = f"{self.base}/stream/{ch['id']}.ts"
        out["locked"] = self.app.lock.is_locked(ch)
        sess = self.app.sessions.status().get(ch["id"])
        out["session"] = sess
        out["rebuilding"] = self.app.sched.busy(ch["id"])
        if deep and ch.get("type") == "weather":
            now = time.time()
            progs = epg.weather_entries(self.app, ch, now, now + 7200)
            out["now"], out["next"] = entry_json(progs[0]), entry_json(progs[1]) if len(progs) > 1 else None
        elif deep and ch.get("type") != "guide" and self.app.store.settings.get("jellyfin_api_key"):
            try:
                now = time.time()
                progs = epg.merged_programs(self.app.sched.entries_between(ch, now - 6 * 3600, now + 12 * 3600, wait=False))
                cur = next((p for p in progs if p["s"] <= now < p["s"] + p["d"]), None)
                nxt = next((p for p in progs if p["s"] > now and p["k"] == "program"), None)
                out["now"] = entry_json(cur)
                out["next"] = entry_json(nxt)
                pool = self.app.sched.pools.get(ch["id"])
                if pool:
                    out["pool"] = {"items": len(pool.items), "hours": round(pool.total_seconds / 3600, 1),
                                   "fillers": len(pool.fillers), "commercials": len(pool.commercials),
                                   "video_bumpers": len(pool.bumpers), "error": pool.error, "fetched": pool.fetched}
            except Exception as ex:
                out["error"] = str(ex)
        return out

    def channel_api(self, method, cid, action, qs):
        app, store, sched = self.app, self.app.store, self.app.sched
        ch = store.channel(cid)
        if not ch:
            return self.error(404, "no such channel")
        cid = ch["id"]
        if not action:
            if method == "GET":
                return self.json(self.channel_summary(ch))
            if method == "PUT":
                data = self.body_json()
                data.pop("id", None)
                for k in ("now", "next", "pool", "session", "logo_url", "stream_url", "error"):
                    data.pop(k, None)
                new = store.update_channel(cid, data)
                if new.get("type") != ch.get("type") or not new.get("enabled", True):
                    app.sessions.stop(cid)
                if any(ch.get(k) != new.get(k) for k in SCHEDULE_KEYS):
                    # re-plan in the background (re-reading the library only if the sources changed): the page
                    # gets its answer right away, and the stream picks up the new plan when it's ready
                    sched.rebuild_async(cid, on_done=lambda: app.sessions.reload(cid))
                else:
                    app.sessions.reload(cid)
                return self.json(self.channel_summary(new))
            if method == "DELETE":
                app.sessions.stop(cid)
                sched.delete(cid)
                store.delete_channel(cid)
                for p in (store.data_dir / "logos" / f"{cid}.png", store.data_dir / "logos" / f"{cid}-header.png"):
                    if p.exists():
                        p.unlink()
                return self.json({"ok": True})
        if action == "schedule":
            hours = min(72.0, float(qs.get("hours", 24)))
            now = time.time()
            return self.json([entry_json(e) for e in epg.channel_entries(app, ch, now - 3600, now + hours * 3600, wait=False)])
        if action == "logo":
            p = store.data_dir / "logos" / f"{cid}.png"
            if method == "POST":
                w, h = normalize_logo(self.body(), p)
                logo = dict(ch.get("logo") or {}, file=f"{cid}.png")
                store.update_channel(cid, {"logo": logo})
                app.sessions.reload(cid)
                return self.json({"ok": True, "width": w, "height": h})
            if method == "DELETE":
                if p.exists():
                    p.unlink()
                store.update_channel(cid, {"logo": dict(ch.get("logo") or {}, file="")})
                app.sessions.reload(cid)
                return self.json({"ok": True})
        if action == "header_logo":       # guide / weather channels: the artwork in the top-left corner
            p = store.data_dir / "logos" / f"{cid}-header.png"
            hl = dict(ch.get("header_logo") or {})
            if method == "GET":
                if hl.get("file") and p.exists():
                    return self.send(200, p.read_bytes(), "image/png", {"Cache-Control": "no-cache"})
                return self.error(404, "no header logo uploaded")
            if method == "POST":
                try:
                    w, h = normalize_logo(self.body(), p)
                except Exception as e:
                    return self.error(400, f"That doesn't look like an image ({e})")
                store.update_channel(cid, {"header_logo": dict(hl, file=f"{cid}-header.png", mode="custom")})
                return self.json({"ok": True, "width": w, "height": h})
            if method == "DELETE":
                if p.exists():
                    p.unlink()
                store.update_channel(cid, {"header_logo": dict(hl, file="",
                                                               mode="station" if hl.get("mode") == "custom" else hl.get("mode"))})
                return self.json({"ok": True})
        if action == "breakdown" and method == "GET":
            if ch.get("type") in ("guide", "weather"):
                return self.json({"groups": []})
            return self.json(sched.breakdown(ch))
        if action == "skip" and method == "POST":
            if ch.get("type") in ("guide", "weather"):
                return self.error(400, "nothing to skip on this channel")
            skipped = sched.skip(ch)
            app.sessions.reload(cid)
            return self.json(dict(self.channel_summary(store.channel(cid)), skipped=skipped))
        if action == "slots" and method == "GET":         # time slots: what each found, and its next airings
            if ch.get("type") in ("guide", "weather"):
                return self.json([])
            return self.json(sched.slots_info(ch))
        m = re.fullmatch(r"slots/([^/]+)/next", action or "")
        if m and method == "POST":                        # in-order slot: choose the next episode
            sid, item = m.group(1), (self.body_json() or {}).get("id")
            if not item or not any(s.get("id") == sid for s in ch.get("slots") or []):
                return self.error(400, "unknown time slot or episode")
            sched.slot_next(ch, sid, item)
            app.sessions.reload(cid)
            return self.json(sched.slots_info(ch))
        if action in ("rebuild_now", "rebuild") and method == "POST":     # runs in the background
            sched.rebuild_async(cid, on_done=lambda: app.sessions.reload(cid),
                                mode="now" if action == "rebuild_now" else "refresh")
            return self.json(self.channel_summary(store.channel(cid)))
        if action == "status" and method == "GET":        # is a background re-plan still running?
            job = sched.jobs.get(cid) or {}
            return self.json({"rebuilding": sched.busy(cid), "since": job.get("started")})
        if action == "refresh" and method == "POST":
            pool = sched.pool(ch, force=True)
            return self.json({"items": len(pool.items), "hours": round(pool.total_seconds / 3600, 1),
                              "error": pool.error})
        if action == "restart" and method == "POST":
            app.sessions.reload(cid)
            return self.json({"ok": True})
        if action == "log" and method == "GET":
            p = store.data_dir / "logs" / f"channel-{cid}.log"
            txt = p.read_text(encoding="utf-8", errors="replace")[-20000:] if p.exists() else ""
            return self.send(200, txt, "text/plain; charset=utf-8")
        if action == "preview.jpg" and method == "GET":
            self.qs_slide = qs.get("slide") if qs.get("slide") in ("current", "hourly", "daily", "radar_local",
                                                                   "radar_regional", "radar_future", "almanac", "alerts") else None
            return self.preview(ch)
        if action == "weather" and method == "GET":
            return self.json(self.weather_check(ch, qs.get("slide")))
        if action == "commercials" and method == "GET":     # compilation splitting status
            pool = sched.pools.get(cid) or sched.pool(ch)
            files = [app.adsplit.status(c) for c in pool.compilations]
            with app.adsplit.lock:
                waiting = len(app.adsplit.queue) + (1 if app.adsplit.current else 0)
            return self.json({"files": files, "spots": len(pool.commercials), "scanning": waiting,
                              "refreshing": any(f["state"] == "done" and f["mode"] == "auto" and
                                                not any(c["id"] == f["id"] for c in pool.commercials) for f in files)})
        if action == "subtitles" and method == "GET":
            return self.json(self.subtitle_check(ch))
        self.error(404, "unknown channel action")

    def _compilation(self, iid):
        for pool in list(self.app.sched.pools.values()):
            for c in pool.compilations:
                if c["id"] == iid:
                    return c
        return None

    def commercial_api(self, method, iid, action, qs):
        app = self.app
        item = self._compilation(iid)
        if not item:
            return self.error(404, "not one of the commercial compilations")
        if action == "thumb.jpg" and method == "GET":
            t = max(0.0, float(qs.get("t", 0) or 0))
            p = app.store.data_dir / "cache" / "adsplit" / "thumbs" / f"{iid}-{t:.2f}.jpg"
            if not p.exists():
                src, headers = app.adsplit._source(item)
                cmd = [app.ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-nostdin"]
                if headers:
                    cmd += ["-headers", headers]
                cmd += ["-ss", f"{t:.3f}", "-i", src, "-frames:v", "1", "-vf", "scale=240:-2", "-q:v", "5",
                        "-f", "mjpeg", "pipe:1"]
                try:
                    r = subprocess.run(cmd, capture_output=True, timeout=30, creationflags=NO_WINDOW)
                except subprocess.TimeoutExpired:
                    return self.error(504, "timed out")
                if not r.stdout:
                    return self.error(502, r.stderr.decode("utf-8", "replace")[-200:] or "no picture")
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(r.stdout)
            return self.send(200, p.read_bytes(), "image/jpeg", {"Cache-Control": "max-age=86400"})
        if method != "POST":
            return self.error(405, "POST only")
        if action == "rescan":
            app.adsplit.forget(item)
            app.adsplit.enqueue(item, front=True)
            return self.json(app.adsplit.status(item))
        if action == "mode":
            mode = (self.body_json() or {}).get("mode")
            if mode not in ("auto", "whole"):
                return self.error(400, "mode is auto or whole")
            app.adsplit.set_mode(item, mode)
            if mode == "auto":
                app.adsplit.spots(item)
            threading.Thread(target=app.adsplit._refresh_channels, daemon=True).start()
            return self.json(app.adsplit.status(item))

    def page(self, name, mode="tv"):
        """index.html / tv.html with the station's name filled in."""
        short = branding.short()
        title = f"{short} Remote" if mode == "remote" else short
        html = (WEB / name).read_text(encoding="utf-8")
        html = (html.replace("%%MODE%%", mode).replace("%%TITLE%%", self._h(title)).replace("%%BRAND%%", self._h(branding.name()))
                .replace("%%SHORT%%", self._h(short)).replace("%%BRANDV%%", branding.version())
                .replace("%%BRANDJSON%%", json.dumps(branding.public()).replace("</", "<\\/")))
        return self.send(200, html, "text/html; charset=utf-8", {"Cache-Control": "no-cache"})

    @staticmethod
    def _h(text):
        return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    def brand_file(self, kind, size=None):
        if kind == "favicon":
            data = (WEB / "favicon.png").read_bytes() if branding.is_default() else branding.generated("favicon")
        elif kind == "icon":
            data = (WEB / f"icon-{size}.png").read_bytes() if branding.is_default() else branding.generated("icon", size)
        else:
            data = branding.path(kind).read_bytes()
        return self.send(200, data, "image/png", {"Cache-Control": "no-cache"})

    def manifest(self, mode):
        short = branding.short()
        icons = [{"src": f"/static/icon-192.png?v={branding.version()}", "sizes": "192x192", "type": "image/png"},
                 {"src": f"/static/icon-512.png?v={branding.version()}", "sizes": "512x512", "type": "image/png",
                  "purpose": "any maskable"}]
        m = {"name": f"{short} Remote — {branding.name()}" if mode == "remote" else f"{short} — {branding.name()}",
             "short_name": f"{short} Remote" if mode == "remote" else short,
             "start_url": "/remote" if mode == "remote" else "/tv", "scope": "/", "display": "standalone",
             "orientation": "portrait" if mode == "remote" else "any",
             "background_color": "#050a1f", "theme_color": branding.color(), "icons": icons}
        return self.send(200, json.dumps(m, ensure_ascii=False), "application/manifest+json; charset=utf-8",
                         {"Cache-Control": "no-cache"})

    def app_page(self):
        base = self.base
        short = self._h(branding.short())
        app_name = short if not branding.is_default() else "Barnes TV"
        has_apk = (WEB / "app" / "BarnesTV.apk").is_file()
        dl = (f'<p><a class="btn primary" href="/app/BarnesTV.apk">⬇ Download BarnesTV.apk</a></p>'
              f'<p>Short link to type on the TV: <code>{base}/app.apk</code></p>') if has_apk else (
              '<p class="warn">The app file isn\'t in this copy yet. Build it from the <code>android-tv</code> folder '
              '(open it in Android Studio and choose <b>Build → Build APK(s)</b>), then copy the APK to '
              '<code>web/app/BarnesTV.apk</code>. See GUIDE.md → “TV app for Google TV and Android TV”.</p>')
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{short} app</title><link rel="icon" href="/favicon.png"><link rel="stylesheet" href="/static/app.css"><link rel="stylesheet" href="/theme.css"></head>
<body><main><h1>📺 {short} for Google TV &amp; Android TV</h1><div class="card stack">
<p>Watch every channel right on the TV, with the TV remote: <b>▲▼</b> change channel, <b>OK</b> opens the guide,
<b>◀</b> jumps back to the last channel, <b>▶</b> shows what's on, <b>Back</b> closes things. TV remotes with
<b>CH +/−</b>, <b>Guide</b> or number buttons work too.</p>{dl}
<h2>Install it on a Google TV Streamer / Chromecast with Google TV</h2><ol class="steps">
<li>On the TV: <b>Settings → System → About</b>, then click <b>Android TV OS build</b> 7 times to turn on developer options.</li>
<li>From the TV's Play Store, install <b>Downloader</b> (by AFTVnews).</li>
<li><b>Settings → Apps → Security &amp; restrictions → Unknown sources</b>: allow <b>Downloader</b>.</li>
<li>Open Downloader, type <code>{base}/app.apk</code> and press Go, then <b>Install</b>.</li>
<li>Open <b>{app_name}</b> from your apps. It finds this server on its own the first time.</li></ol>
<p class="sub">Phone instead? Any “send files to TV” app works too: send BarnesTV.apk to the TV and open it there.</p>
</div></main></body></html>"""

    def theme_preview(self, tid, kind, qs, spec=None):
        from . import preview as pv
        app = self.app
        T = themes.Theme(spec=spec) if spec else themes.get(tid)
        Ft, Fd = app.theme_fonts(T, qs.get("font"), qs.get("display"))
        if kind == "guide":
            img = pv.guide_preview(T, Ft, Fd, app.fonts(), station=branding.name(),
                                   clock_fmt=qs.get("fmt") or "12h")
        else:
            img = pv.slate_preview(T, Ft, Fd, app.store.data_dir / "slates")
        self.send(200, pv.jpeg(img), "image/jpeg", {"Cache-Control": "no-cache"})

    def weather_check(self, ch, slide=None):
        """Look the location up now and report what the weather channel will show (admin page 'Check')."""
        app = self.app
        loc, err = app.weather.location(ch, wait=True)
        if not loc:
            return {"ok": False, "error": err or "Couldn't find the location"}
        snap = app.weather.snapshot(ch, wait=True, refresh=True)     # fetch the forecast now, to show any error
        fc = snap.get("forecast")
        out = {"ok": bool(fc), "location": loc, "imperial": snap.get("imperial"),
               "errors": {k: v for k, v in (snap.get("errors") or {}).items() if v}, "alerts": len(snap.get("alerts") or [])}
        if fc:
            out["forecast_age_min"] = round((time.time() - fc.get("fetched", 0)) / 60)
        rd = (snap.get("radar") or {}).get("local") or {}
        if rd.get("frames"):
            out["radar_age_min"] = round((time.time() - rd["frames"][-1][0]) / 60)
        if fc:
            from .weather import describe
            cur = fc["current"]
            out["now"] = f"{round(cur['temp'])}° {describe(cur['code'])[0]}"
        return out

    def subtitle_check(self, ch):
        """What the subtitle settings do for the show on this channel right now (for the admin page)."""
        from .streamer import ChannelSession
        app = self.app
        if ch.get("type") in epg.SPECIAL:
            return {"ok": False, "reason": "This channel has no shows."}
        _, e = app.sched.entry_at(ch, time.time())
        if e and e["k"] != "program":       # in a break: look at the next show
            e = app.sched.next_program(ch, e["s"] + e["d"]) or e
        if not e or not e.get("i"):
            return {"ok": False, "reason": "Nothing is scheduled right now."}
        sess = app.sessions.active.get(ch["id"])
        if not isinstance(sess, ChannelSession):
            sess = ChannelSession(app, ch)
        sess.details.pop(e["i"]["id"], None)        # look the tracks up fresh
        info = sess._item_info(e["i"])
        sub, why = sess.subtitle_choice(e["i"], info, e["k"])
        return {"ok": bool(sub), "title": e["i"].get("title"), "reason": why, "audio": info.get("audio_lang") or "",
                "libass": app.ffmpeg_has_filter("subtitles"),
                "tracks": [{k: t[k] for k in ("lang", "codec", "forced", "text", "external", "title")}
                           for t in info.get("subs") or []]}

    def preview(self, ch):
        """One still frame of 'what's on' with this channel's logo/clock overlays applied."""
        from .graphics import render_slate
        from .streamer import ChannelSession
        app = self.app
        b = app.builder()
        logo = str(app.store.data_dir / "logos" / f"{ch['id']}.png")
        logo = logo if (ch.get("logo") or {}).get("file") and Path(logo).exists() else None
        now = time.time()
        cmd = None
        up = app.up_next_overlay(ch, -1, 9999, "Your next show") if (ch.get("up_next") or {}).get("enabled") else None
        if ch.get("type") == "weather":     # the weather channel: its current-conditions screen, live data
            from . import preview as pv
            from .weathergfx import WeatherRenderer
            T = app.theme(ch)
            Ft, Fd = app.theme_fonts(T, ch.get("guide_font"), ch.get("guide_display_font"))
            R = WeatherRenderer(T, Ft, Fd, b.W, b.H, (ch.get("clock") or {}).get("format", "12h"),
                                branding.name(), app.header_logo(ch))
            snap = app.weather.snapshot(ch, R.map_size, T.light, wait=True)
            slide = self.qs_slide if getattr(self, "qs_slide", None) else "current"
            img = R.frame(snap, slide, 0, time.time(), [slide])
            return self.send(200, pv.jpeg(img, None), "image/jpeg")
        if ch.get("type") == "guide":       # the guide channel: a sample frame in its theme and fonts
            from . import preview as pv
            T = app.theme(ch)
            Ft, Fd = app.theme_fonts(T, ch.get("guide_font"), ch.get("guide_display_font"))
            img = pv.guide_preview(T, Ft, Fd, app.fonts(), b.W, b.H, branding.name(),
                                   (ch.get("clock") or {}).get("format", "12h"), header=app.header_logo(ch))
            return self.send(200, pv.jpeg(img, None), "image/jpeg")
        if app.store.settings.get("jellyfin_api_key"):
            try:
                _, e = app.sched.entry_at(ch, now)
                if e and e["k"] in ("program", "filler"):
                    sess = ChannelSession(app, ch)
                    info = sess._item_info(e["i"])
                    src, headers = sess._source(e["i"], info)
                    try:
                        sub = sess._subtitle(e["i"], info, e["k"])
                    except Exception:
                        sub = None
                    cmd = b.segment(ch, source=src, headers=headers, offset=max(1.0, now - e["s"] + e.get("o", 0.0)),
                                    duration=1, audio_index=info["audio_index"], has_audio=info["has_audio"],
                                    hdr=info["hdr"], logo_path=logo, up_next=up, preview=True, subtitle=sub)
            except Exception as ex:
                log.info("preview fell back to slate: %s", ex)
        if cmd is None:
            T = app.theme(ch)
            Ft, Fd = app.theme_fonts(T)
            img = render_slate(Ft, app.store.data_dir / "slates", b.W, b.H, "upnext", ch,
                               {"s": now + 600, "d": 1800, "k": "program",
                                "i": {"title": "Sample Program", "type": "Movie", "year": 1999}}, logo, T, Fd)
            cmd = b.segment(ch, image=str(img), duration=1, logo_path=logo, up_next=up, preview=True)
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=45, creationflags=NO_WINDOW)
        except subprocess.TimeoutExpired:
            return self.error(504, "preview timed out")
        if r.returncode != 0 or not r.stdout:
            return self.error(500, r.stderr.decode("utf-8", "replace")[-600:] or "ffmpeg failed")
        self.send(200, r.stdout, "image/jpeg")


def serve(app, host, port):
    Handler.app = app
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    return httpd

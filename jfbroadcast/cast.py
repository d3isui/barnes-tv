"""Chromecast control from the server.

Browsers only allow their built-in Cast button on HTTPS sites, so instead the Broadcast server itself finds the
Chromecasts on your network (mDNS, or IP addresses you enter) and tells them to play a channel's HLS stream through
Google's standard media receiver. Any phone or browser can then act as the remote - no HTTPS, no app registration.
"""
import logging
import threading
import time

log = logging.getLogger("cast")

MEDIA_RECEIVER = "CC1AD845"   # Google's Default Media Receiver
SWITCH_SETTLE = 0.7           # rapid channel flips: only the last one within this many seconds is sent to the TV
STUCK_AFTER = 25              # seconds without playback progress (after it was playing) before a reload
START_TIMEOUT = 75            # a load that never starts playing gets one more try after this long
RELOAD_GAP = 40               # minimum seconds between (re)loads of one TV
MAX_RELOADS = 5               # give up (and say so) after this many reloads in a row that didn't help

# Cast "detailed error codes" most relevant to us (subset of Google's list)
CAST_ERRORS = {
    102: "the TV couldn't decode the video", 103: "network error while loading the stream",
    104: "the TV doesn't support this stream format", 110: "the TV's player rejected the stream data",
    301: "couldn't download a video segment", 311: "couldn't load the playlist", 312: "couldn't load the playlist",
    315: "a video segment had the wrong format", 316: "couldn't parse a video segment",
    411: "the playlist was invalid", 412: "the playlist was invalid", 905: "the TV failed to load the stream",
}

try:
    import pychromecast
    from pychromecast.discovery import CastBrowser, SimpleCastListener
    import zeroconf
    IMPORT_ERROR = ""
except Exception as e:  # pragma: no cover - optional dependency
    pychromecast = None
    IMPORT_ERROR = str(e)


class _Listener:
    """Receives media status from one device so we can tell 'loading' from 'failed'."""

    def __init__(self, mgr, uid):
        self.mgr, self.uid = mgr, uid

    def new_media_status(self, status):
        p = self.mgr.playing.get(self.uid)
        if p and status and status.player_state == "IDLE" and getattr(status, "idle_reason", None) == "ERROR":
            if not p.get("error"):           # keep a more specific load-failure reason if we already have one
                p["error"] = "The TV stopped with a playback error"
            log.warning("cast %s: playback error (idle_reason=ERROR)", self.uid)
        elif p and status and status.player_state == "PLAYING":
            p["started"] = True

    def load_media_failed(self, item, error_code):
        p = self.mgr.playing.get(self.uid)
        msg = CAST_ERRORS.get(int(error_code or 0), "the TV failed to load the stream")
        if p:
            p["error"] = f"{msg} (Cast error {error_code})"
        log.warning("cast %s: load failed, error code %s (%s)", self.uid, error_code, msg)


class CastManager:
    def __init__(self, app):
        self.app = app
        self.lock = threading.RLock()
        self.browser = None
        self.zconf = None
        self.casts = {}        # uuid -> pychromecast.Chromecast
        self.playing = {}      # uuid -> {"cid":..., "since":..., watchdog bookkeeping}
        self.gen = {}          # uuid -> play request counter (newer requests supersede older ones)
        self.dev_locks = {}    # uuid -> lock serialising loads on one TV
        self._watchdog = None
        self.resume = self._load_resume()    # TVs to put back on their channel after a server restart
        self.error = "" if pychromecast else f"Chromecast support needs the pychromecast package ({IMPORT_ERROR})"
        self._hosts_key = None

    @property
    def available(self):
        return pychromecast is not None

    # ------------------------------------------------------------------ discovery
    def start(self):
        if not self.available:
            return
        hosts = [h.strip() for h in (self.app.store.settings.get("cast_hosts") or "").replace(";", ",").split(",")
                 if h.strip()]
        key = tuple(hosts)
        with self.lock:
            if self.browser and key == self._hosts_key:
                return
            self._stop_browser()
            try:
                self.zconf = zeroconf.Zeroconf()
                self.browser = CastBrowser(SimpleCastListener(self._changed, self._removed, self._changed),
                                           self.zconf, known_hosts=hosts or None)
                self.browser.start_discovery()
                self._hosts_key = key
                if self._watchdog is None:
                    self._watchdog = threading.Thread(target=self._watch, daemon=True, name="cast-watchdog")
                    self._watchdog.start()
                self.error = ""
                log.info("Chromecast discovery started%s", f" (also polling {', '.join(hosts)})" if hosts else "")
            except Exception as e:
                self.error = f"Chromecast discovery failed: {e}"
                log.warning(self.error)

    def _stop_browser(self):
        try:
            if self.browser:
                self.browser.stop_discovery()
        except Exception:
            pass
        try:
            if self.zconf:
                self.zconf.close()
        except Exception:
            pass
        self.browser = self.zconf = None

    def _changed(self, uuid, service):
        info = self.browser.devices.get(uuid) if self.browser else None
        if info:
            log.info("found cast device %s (%s, %s)", info.friendly_name, info.model_name, info.host)

    def _removed(self, uuid, service, info):
        with self.lock:
            cc = self.casts.pop(str(uuid), None)
        if cc:
            try:
                cc.disconnect(blocking=False)
            except Exception:
                pass

    def devices(self):
        if not self.available:
            return []
        self.start()
        out = []
        for uuid, info in list((self.browser.devices if self.browser else {}).items()):
            if info.cast_type and info.cast_type not in ("cast",):   # skip speaker-only devices and groups
                continue
            uid = str(uuid)
            d = {"id": uid, "name": info.friendly_name or info.host, "model": info.model_name or "",
                 "host": info.host, "channel": self._playing_cid(uid), "state": self._state(uid)}
            d.update(self._diagnose(uid, info.host))
            cc = self.casts.get(uid)
            if cc is not None and cc.status:
                d["volume"], d["muted"] = round(cc.status.volume_level or 0, 2), bool(cc.status.volume_muted)
            out.append(d)
        return sorted(out, key=lambda d: d["name"].lower())

    def _playing_cid(self, uid):
        """Which of our channels the device is showing - checked against the device, in case someone switched
        to another app or stopped casting from their phone."""
        playing = self.playing.get(uid)
        cc = self.casts.get(uid)
        if not playing or not cc:
            return None
        try:
            st = cc.media_controller.status
            if st and st.content_id and f"/hls/{playing['cid']}/" not in st.content_id:
                return None
            if time.time() - playing["since"] > 30 and (not st or st.player_state in ("IDLE", "UNKNOWN")):
                return None
        except Exception:
            pass
        return playing["cid"]

    def _diagnose(self, uid, host):
        """A plain-language status for a device we cast to: playing / starting / unreachable / error."""
        p = self.playing.get(uid)
        if not p:
            return {"status": "idle", "message": ""}
        if p.get("error"):
            return {"status": "error", "message": p["error"]}
        if self._state(uid) == "PLAYING" or p.get("started"):
            return {"status": "playing", "message": ""}
        hit = self.app.hls.hits.get(host)
        reached = bool(hit and hit["t"] >= p["since"] - 1)
        age = time.time() - p["since"]
        if not reached and age > 20:
            return {"status": "unreachable", "message":
                    f"The TV never requested the stream from {self.base_url()}. It can't reach this computer: "
                    "allow port %d through the firewall (see GUIDE.md → Casting to a Chromecast) and make sure that address is "
                    "this machine's network IP." % self.app.port}
        if reached and age > 40:
            return {"status": "error", "message": "The TV downloaded the stream but didn't start playing. "
                    "Try Settings → Chromecast → stream format \"HLS MPEG-TS\"."}
        return {"status": "starting", "message": "Restarting the stream on the TV…" if p.get("reloading") else "Loading on the TV…"}

    def _state(self, uid):
        cc = self.casts.get(uid)
        try:
            st = cc.media_controller.status if cc else None
            return st.player_state if st else ""
        except Exception:
            return ""

    def _cast(self, uid):
        with self.lock:
            cc = self.casts.get(uid)
            if cc is not None:
                return cc
            if not self.browser:
                raise RuntimeError(self.error or "Chromecast discovery is not running")
            info = next((i for u, i in self.browser.devices.items() if str(u) == uid), None)
            if info is None:
                raise RuntimeError("That Chromecast is no longer on the network")
            cc = pychromecast.get_chromecast_from_cast_info(info, self.zconf, tries=2, timeout=10)
            cc.wait(timeout=15)
            try:
                cc.media_controller.register_status_listener(_Listener(self, uid))
            except Exception as e:
                log.info("couldn't attach status listener: %s", e)
            self.casts[uid] = cc
            return cc

    # ------------------------------------------------------------------ control
    def base_url(self):
        pub = (self.app.store.settings.get("public_url") or "").rstrip("/")
        if pub and "localhost" not in pub and "127.0.0.1" not in pub:
            return pub
        from .app import lan_ip
        return f"http://{lan_ip()}:{self.app.port}"

    def play(self, uid, ch, reload=False):
        if not self.available:
            raise RuntimeError(self.error)
        self.app.hls.ensure(ch)                     # warm up the stream while the Chromecast launches its player
        if not reload:
            # someone flipping through channels: wait a moment and only send the TV the last channel picked
            gen = self.gen[uid] = self.gen.get(uid, 0) + 1
            time.sleep(SWITCH_SETTLE)
            if self.gen.get(uid) != gen:
                return {"ok": True, "device": uid, "channel": ch["id"], "superseded": True}
        with self.dev_locks.setdefault(uid, threading.Lock()):
            if not reload and self.gen.get(uid) != gen:
                return {"ok": True, "device": uid, "channel": ch["id"], "superseded": True}
            return self._load(uid, ch, reload)

    def _load(self, uid, ch, reload):
        base = self.base_url()
        cc = self._cast(uid)
        fmt = (self.app.store.settings.get("cast_hls_format") or "fmp4").lower()
        title = f"{ch['number']} · {ch['name']}"
        subtitle = ""
        try:
            if ch.get("type") == "weather":
                subtitle = self.app.weather.summary(ch)
            elif ch.get("type") != "guide":
                _, e = self.app.sched.entry_at(ch, time.time())
                if e and e.get("i"):
                    from .graphics import program_label
                    subtitle = " — ".join(x for x in program_label(e["i"]) if x)
            else:
                subtitle = "Program Guide"
        except Exception:
            pass
        mc = cc.media_controller
        prev = self.playing.get(uid) or {}
        now = time.time()
        self.playing[uid] = {"cid": ch["id"], "since": now, "progress_at": now, "ct": -1.0, "reloading": reload,
                             "reloads": (prev.get("reloads", 0) if reload and prev.get("cid") == ch["id"] else 0),
                             "last_reload": now}
        url = f"{base}/hls/{ch['id']}/index.m3u8?k={self.app.lock.tuner_key}&r={int(now)}"
        mc.play_media(url, "application/x-mpegURL",
                      title=title, thumb=f"{base}/logos/{ch['id']}.png", stream_type="LIVE",
                      metadata={"metadataType": 0, "title": title, "subtitle": subtitle},
                      media_info={"hlsSegmentFormat": "fmp4" if fmt == "fmp4" else "ts",
                                  "hlsVideoSegmentFormat": "fmp4" if fmt == "fmp4" else "mpeg2_ts"})
        log.info("%s channel %s to %s via %s", "reloading" if reload else "casting", ch["number"],
                 cc.cast_info.friendly_name, base)
        return {"ok": True, "device": uid, "channel": ch["id"]}

    def reload(self, uid):
        """Load the TV's current channel again from scratch (the remote's 'Fix picture' button)."""
        p = self.playing.get(uid)
        if not p:
            raise RuntimeError("Nothing from this server is playing on that TV")
        ch = self.app.store.channel(p["cid"])
        if not ch:
            raise RuntimeError("That channel no longer exists")
        with self.dev_locks.setdefault(uid, threading.Lock()):
            p["reloads"] = 0
            return self._load(uid, ch, True)

    def _load_resume(self):
        import json
        p = self.app.store.data_dir / "state" / "restart.json"
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            p.unlink()
            if time.time() - float(data.get("t", 0)) < 180:
                return {uid: {"cid": cid, "until": time.time() + 90} for uid, cid in (data.get("casting") or {}).items()}
        except Exception:
            pass
        return {}

    def _resume(self):
        for uid, r in list(self.resume.items()):
            if time.time() > r["until"]:
                self.resume.pop(uid, None)
                continue
            if not self.browser or not any(str(u) == uid for u in self.browser.devices):
                continue      # not discovered yet
            self.resume.pop(uid, None)
            ch = self.app.store.channel(r["cid"])
            if ch:
                try:
                    with self.dev_locks.setdefault(uid, threading.Lock()):
                        self._load(uid, ch, True)
                    log.info("after the restart, put channel %s back on %s", ch["number"], uid)
                except Exception as e:
                    log.warning("couldn't resume casting on %s: %s", uid, e)

    # ------------------------------------------------------------------ watchdog
    def _watch(self):
        """Every few seconds: is each TV we cast to actually moving forward? If the picture is frozen, stuck
        buffering, or the player stopped with an error, load the channel again."""
        while True:
            time.sleep(4)
            if self.resume:
                self._resume()
            if not self.app.store.settings.get("cast_watchdog", True):
                continue
            for uid, p in list(self.playing.items()):
                try:
                    self._check(uid, p)
                except Exception as e:
                    log.debug("watchdog check failed for %s: %s", uid, e)

    def _check(self, uid, p):
        cc = self.casts.get(uid)
        if cc is None or self.playing.get(uid) is not p:
            return
        now = time.time()
        age = now - p["since"]
        app_id = getattr(cc.status, "app_id", None) if cc.status else None
        if app_id == MEDIA_RECEIVER:
            p["app_seen"] = True
        elif p.get("app_seen") or age > 45:
            # the TV left the Cast player (Home, Back, another app, turned off): stop watching it. Never relaunch.
            log.info("cast %s: the TV left the Cast player (now %s); no longer watching it", uid, app_id or "idle")
            self.playing.pop(uid, None)
            return
        else:
            return      # the player is still starting up
        mc = cc.media_controller
        if mc.is_active:
            # only ask a running player for its status: asking when it isn't running would relaunch it on the TV
            try:
                mc.update_status()
            except Exception:
                pass
        st = mc.status
        state = (st.player_state if st else None) or "UNKNOWN"
        if st and st.content_id:
            if f"/hls/{p['cid']}/" in st.content_id:
                p["ours"] = True
            elif p.get("ours") or age > 30:      # someone cast something else to it
                log.info("cast %s: now showing something else; no longer watching it", uid)
                self.playing.pop(uid, None)
                return
        ct = float(st.current_time or 0) if st else 0.0
        if state == "PLAYING" and ct > p["ct"] + 0.5:
            if p["ct"] >= 0:
                p["advancing"] = True       # this TV reports a moving position, so a stopped one means frozen
            if p.get("reloads"):
                log.info("cast %s: playing again after reload", uid)
                p["reloads"] = 0
                p.pop("error", None)
            p["ct"], p["progress_at"] = ct, now
            p["started"] = True
            return
        if state == "PAUSED":          # paused on purpose from the TV or the Google Home app: leave it alone
            p["progress_at"] = now
            return
        idle_reason = getattr(st, "idle_reason", None) if st else None
        if state == "IDLE" and idle_reason == "CANCELLED":
            log.info("cast %s: stopped from the TV or another phone", uid)
            self.playing.pop(uid, None)
            return
        stuck = None
        if state == "IDLE" and idle_reason in ("ERROR", "FINISHED") and age > 10:
            stuck = f"player stopped ({idle_reason.lower()})"
        elif p.get("advancing") and state in ("PLAYING", "BUFFERING") and now - p["progress_at"] > STUCK_AFTER:
            stuck = "picture frozen" if state == "PLAYING" else "stuck buffering"
        elif not p.get("started") and age > START_TIMEOUT:
            stuck = f"never started playing (player is {state.lower()})"
        if not stuck or now - p.get("last_reload", 0) < RELOAD_GAP:
            return
        if p.get("reloads", 0) >= MAX_RELOADS:
            if not p.get("gave_up"):
                p["gave_up"] = True
                p["error"] = ("The TV keeps getting stuck on this channel. Check the channel's Log in the admin page; "
                              "if it says it's encoding slower than real time, pick a faster preset or a GPU encoder.")
                log.warning("cast %s: still stuck after %d reloads; giving up", uid, MAX_RELOADS)
            return
        ch = self.app.store.channel(p["cid"])
        if not ch:
            return
        log.warning("cast %s: %s on channel %s; reloading the stream (try %d)", uid, stuck, ch["number"],
                    p.get("reloads", 0) + 1)
        with self.dev_locks.setdefault(uid, threading.Lock()):
            if self.playing.get(uid) is p:
                p["reloads"] = p.get("reloads", 0) + 1
                self._load(uid, ch, True)

    def stop(self, uid):
        self.playing.pop(uid, None)
        cc = self.casts.get(uid)
        if cc:
            try:
                cc.quit_app()
            except Exception as e:
                log.info("stop failed: %s", e)
        return {"ok": True}

    def volume(self, uid, delta=None, mute=None, level_abs=None):
        cc = self._cast(uid)
        level = cc.status.volume_level if cc.status else 0.5
        muted = cc.status.volume_muted if cc.status else False
        if mute is not None:
            muted = bool(mute)
            cc.set_volume_muted(muted)
        if level_abs is not None:
            level = max(0.0, min(1.0, float(level_abs)))
            cc.set_volume(level)
        elif delta:
            level = max(0.0, min(1.0, level + float(delta)))
            cc.set_volume(level)
        return {"ok": True, "volume": round(level, 2), "muted": muted}

    def shutdown(self):
        for cc in list(self.casts.values()):
            try:
                cc.disconnect(blocking=False)
            except Exception:
                pass
        self._stop_browser()

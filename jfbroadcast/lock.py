"""Channel lock ("kids mode").

When the lock is on, only channels marked as Kids channels play freely. Everything else needs the lock code, which
unlocks *that device* for a while (an unlock token). The server enforces it - streams, Chromecast casting and admin
changes all check - so it can't be skipped by typing a stream address into a browser.

Jellyfin and Chromecasts can't type a code, so the links this app hands them (the M3U playlist, casting) carry a
private "tuner key" instead. Parents can also hide locked channels from Jellyfin entirely.
"""
import hashlib
import hmac
import logging
import secrets
import threading
import time

log = logging.getLogger("lock")

MAX_FAILS = 5            # wrong codes allowed ...
FAIL_WINDOW = 300        # ... within this many seconds, before a cool-down
COOLDOWN = 60


def _hash(code, salt):
    return hashlib.pbkdf2_hmac("sha256", code.encode(), bytes.fromhex(salt), 120_000).hex()


class ChannelLock:
    def __init__(self, store):
        self.store = store
        self.tokens = {}         # token -> expiry (epoch seconds)
        self.fails = {}          # client ip -> [timestamps]
        self.lockout = {}        # client ip -> until
        self.mutex = threading.Lock()
        if not store.settings.get("tuner_key"):
            store.update_settings({"tuner_key": secrets.token_urlsafe(18)})

    # ---------- state ----------
    @property
    def enabled(self):
        st = self.store.settings
        return bool(st.get("lock_enabled") and st.get("lock_code_hash"))

    def is_locked(self, ch):
        ch = ch or {}
        # the guide channel only shows listings, so it's always available
        return self.enabled and not ch.get("kids") and ch.get("type") not in ("guide", "weather")

    @property
    def tuner_key(self):
        return self.store.settings.get("tuner_key") or ""

    def key_ok(self, key):
        return bool(key) and hmac.compare_digest(str(key), self.tuner_key)

    # ---------- codes ----------
    @staticmethod
    def valid_code_format(code):
        return isinstance(code, str) and code.isdigit() and 4 <= len(code) <= 8

    def set_code(self, code):
        if not self.valid_code_format(code):
            raise ValueError("The lock code must be 4 to 8 digits")
        salt = secrets.token_hex(16)
        self.store.update_settings({"lock_code_hash": _hash(code, salt), "lock_salt": salt})
        with self.mutex:
            self.tokens.clear()          # a new code signs everyone out

    def check_code(self, code):
        st = self.store.settings
        if not st.get("lock_code_hash") or not isinstance(code, str):
            return False
        return hmac.compare_digest(_hash(code, st.get("lock_salt") or "00"), st["lock_code_hash"])

    # ---------- unlock tokens ----------
    def unlock(self, code, ip):
        """Returns (token, expiry) or raises PermissionError with a user-facing message."""
        now = time.time()
        with self.mutex:
            until = self.lockout.get(ip, 0)
            if until > now:
                raise PermissionError(f"Too many wrong codes. Try again in {int(until - now) + 1} seconds.")
            if not self.check_code(code):
                fails = [t for t in self.fails.get(ip, []) if now - t < FAIL_WINDOW] + [now]
                self.fails[ip] = fails
                if len(fails) >= MAX_FAILS:
                    self.lockout[ip] = now + COOLDOWN
                    self.fails[ip] = []
                    log.warning("channel lock: too many wrong codes from %s, cooling down", ip)
                    raise PermissionError(f"Too many wrong codes. Try again in {COOLDOWN} seconds.")
                raise PermissionError("Wrong code")
            self.fails.pop(ip, None)
            minutes = float(self.store.settings.get("lock_unlock_minutes") or 60)
            token = secrets.token_urlsafe(18)
            expiry = now + minutes * 60
            self.tokens[token] = expiry
            for t, exp in list(self.tokens.items()):
                if exp < now:
                    del self.tokens[t]
            log.info("channel lock: unlocked for %d minutes by %s", minutes, ip)
            return token, expiry

    def valid(self, token):
        if not token:
            return False
        exp = self.tokens.get(token)
        return bool(exp and exp > time.time())

    def expiry(self, token):
        return self.tokens.get(token) if self.valid(token) else None

    def relock(self, token):
        with self.mutex:
            self.tokens.pop(token, None)

    def allowed(self, ch, token=None, key=None):
        return not self.is_locked(ch) or self.valid(token) or self.key_ok(key)

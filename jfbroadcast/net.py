"""HTTPS that trusts the same certificates your browser does.

Python checks certificates with its own copy of the trusted roots. On Windows that copy is read once from the
certificate store, and Windows only adds newer roots on demand when Windows' own programs need them, so a site that
works in the browser can fail in Python with "certificate verify failed" (or "certificate has expired", when the only
root Python has for that site is an old, expired one). This happens most under the SYSTEM account the startup task
uses. So:
  1. with the "truststore" package, certificates are checked by Windows / macOS itself, like the browser does;
  2. otherwise Python's usual check;
  3. if that fails on a certificate, one retry with the "certifi" bundle (Mozilla's list of trusted roots).
"""
import logging
import ssl
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger("net")
_ctx = {}
_warned = set()


def _system():
    if "system" not in _ctx:
        ctx = None
        try:
            import truststore
            ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        except Exception:
            ctx = ssl.create_default_context()
        _ctx["system"] = ctx
    return _ctx["system"]


def _certifi():
    if "certifi" not in _ctx:
        try:
            import certifi
            _ctx["certifi"] = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            _ctx["certifi"] = None
    return _ctx["certifi"]


def _cert_problem(e):
    reason = getattr(e, "reason", e)
    return isinstance(reason, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(reason)


def urlopen(req, timeout=20):
    """urllib.request.urlopen with the certificate handling described above."""
    url = req.full_url if isinstance(req, urllib.request.Request) else str(req)
    if not url.startswith("https:"):
        return urllib.request.urlopen(req, timeout=timeout)
    try:
        return urllib.request.urlopen(req, timeout=timeout, context=_system())
    except urllib.error.URLError as e:
        alt = _certifi()
        if not _cert_problem(e) or alt is None:
            if _cert_problem(e) and "nocertifi" not in _warned:
                _warned.add("nocertifi")
                log.warning("HTTPS certificate check failed and the 'certifi' package isn't installed. Run start.bat once "
                            "(or: .venv\\Scripts\\python -m pip install -r requirements.txt) to install it.")
            raise
        host = urllib.parse.urlparse(url).hostname
        if host not in _warned:
            _warned.add(host)
            log.info("certificate check for %s failed with this computer's certificate list (%s); "
                     "using the bundled certifi list instead", host, getattr(e, "reason", e))
        return urllib.request.urlopen(req, timeout=timeout, context=alt)

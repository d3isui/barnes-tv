#!/usr/bin/env python3
"""Barnes Television Broadcasting System - 24/7 cable-style TV channels from your own Jellyfin library.

    python broadcast.py                 # serve on port 8420, data in ./data
    python broadcast.py --port 9000 --data D:\\Broadcast\\data
"""
import argparse
import logging
import os
import signal
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

if sys.version_info < (3, 8):
    sys.exit("Barnes Television Broadcasting System needs Python 3.8 or newer (3.12 recommended). You have " + sys.version.split()[0])

try:
    import PIL  # noqa: F401
except ImportError:
    sys.exit("Pillow is missing. Install it with:  python -m pip install -r requirements.txt")

from jfbroadcast import BRAND, __version__  # noqa: E402
from jfbroadcast.app import App  # noqa: E402
from jfbroadcast.server import serve  # noqa: E402


RESTART_CODE = 3      # the server exits with this to ask the supervisor for a fresh start


def _windows_kill_job():
    """A Windows "job object" that kills everything in it when this process ends, however it ends (Task Scheduler
    "End", Task Manager, closing the window). The server and its ffmpeg processes are put in it, so they never outlive
    the supervisor. (Python's own launcher lets them slip out of its job, which is why they used to keep running.)"""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

        class IOC(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes", "OtherBytes")]

        class EXTENDED(ctypes.Structure):
            _fields_ = [("Basic", BASIC), ("Io", IOC), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        job = k32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = EXTENDED()
        info.Basic.LimitFlags = 0x2000          # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):   # ExtendedLimitInformation
            return None
        return (k32, job)
    except Exception:
        return None


def _die_with_parent():
    """Linux: the server gets SIGTERM if the supervisor is killed (so it never runs on orphaned)."""
    try:
        import ctypes
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)   # PR_SET_PDEATHSIG
    except Exception:
        pass


def supervise():
    """Run the real server as a child process and start it again whenever it exits asking for a restart
    (Settings -> Restart server). Works the same under start.bat, the Windows startup task, start.sh and systemd."""
    env = dict(os.environ, BTV_CHILD="1")
    child = None

    def forward(signum, _frame):
        if child and child.poll() is None:
            try:
                child.send_signal(signum)
            except Exception:
                child.terminate()

    for sig in ("SIGTERM", "SIGBREAK"):
        if hasattr(signal, sig):
            signal.signal(getattr(signal, sig), forward)
    job = _windows_kill_job()
    while True:
        child = subprocess.Popen([sys.executable, os.path.abspath(__file__)] + sys.argv[1:], env=env,
                                 preexec_fn=_die_with_parent if sys.platform.startswith("linux") else None)
        if job:
            try:
                job[0].AssignProcessToJobObject(job[1], int(child._handle))
            except Exception:
                pass
        try:
            code = child.wait()
        except KeyboardInterrupt:      # Ctrl+C reaches the child too; let it shut down cleanly
            try:
                code = child.wait(timeout=20)
            except Exception:
                child.kill()
                code = 0
            return code
        if code != RESTART_CODE:
            return code
        print("Restarting the server...", flush=True)
        time.sleep(0.5)


def main():
    ap = argparse.ArgumentParser(description="Barnes Television Broadcasting System")
    ap.add_argument("--host", default=os.environ.get("JFB_HOST", "0.0.0.0"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("JFB_PORT", 8420)))
    ap.add_argument("--data", default=os.environ.get("JFB_DATA", os.path.join(HERE, "data")))
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--no-supervise", action="store_true", help="don't run under the restart supervisor")
    args = ap.parse_args()
    if not os.environ.get("BTV_CHILD") and not args.no_supervise:
        sys.exit(supervise())

    os.makedirs(args.data, exist_ok=True)
    handlers = [logging.StreamHandler(sys.stdout)] if sys.stdout else []     # pythonw (startup task): no console
    try:
        handlers.append(logging.FileHandler(os.path.join(args.data, "broadcast.log"), encoding="utf-8"))
    except OSError:
        pass
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", handlers=handlers)

    app = App(args.data, args.port)
    httpd = None
    for attempt in range(40):      # after a restart the old process may still hold the port for a moment
        try:
            httpd = serve(app, args.host, args.port)
            break
        except OSError as e:
            if attempt == 39:
                raise
            if attempt == 0:
                logging.getLogger("main").info("port %d busy (%s); waiting for it", args.port, e)
            time.sleep(0.5)
    app.start_maintenance()
    ff = app.ffmpeg_info()
    log = logging.getLogger("main")
    log.info("%s %s", BRAND, __version__)
    log.info("ffmpeg: %s (%s)", ff["path"], ff["version"] or "NOT FOUND - set the ffmpeg path in Settings")
    base = app.default_base()
    log.info("Admin page:   %s/", base)
    log.info("Watch in browser: %s/tv", base)
    log.info("M3U tuner:    %s/iptv/channels.m3u", base)
    log.info("XMLTV guide:  %s/iptv/xmltv.xml", base)

    def shutdown(*_):
        log.info("restarting" if app.restart_requested else "shutting down")
        app.stop_evt.set()
        try:
            app.hls.stop_all()
        except Exception:
            pass
        app.sessions.stop_all()
        app.cast.shutdown()
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    app.shutdown_hook = shutdown

    signal.signal(signal.SIGINT, shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, shutdown)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, shutdown)
    try:
        httpd.serve_forever(poll_interval=0.5)
    finally:
        httpd.server_close()
    if app.restart_requested:
        sys.exit(RESTART_CODE)


if __name__ == "__main__":
    main()

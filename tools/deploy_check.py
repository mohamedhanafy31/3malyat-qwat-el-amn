#!/usr/bin/env python3
"""Deployment preflight and readiness helpers used by the Windows batch files.

Standard library only and ASCII console output: it runs before the project
runtime is configured (an embedded Python ignores the script directory until
SETUP_OFFLINE.bat has edited its ._pth) and its text is shown in cmd.exe.

    python tools/deploy_check.py host-python [--wheel-abi cp311]
    python tools/deploy_check.py preflight --mode prepare|setup
    python tools/deploy_check.py ready --port 5000 [--timeout 2]
    python tools/deploy_check.py choose-port --output logs/server.port

`ready` exit codes: 0 this application is ready, 10 nothing is listening,
11 this application answered but reports it is unavailable (data cannot be
loaded), 12 another service answered with something other than this
application's readiness marker, 13 a listener did not answer within the timeout
(possibly this application still starting).
"""
from __future__ import annotations

import argparse
import errno
import http.client
import json
import os
import platform
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Keep in sync with backend/routes/health.py (tests compare them).
SERVICE_ID = "personnel-system"
READY_PATH = "/api/health/ready"
DEFAULT_PORT = 5000

# Oldest host Python able to run tools/prepare_offline_bundle.py.
MIN_HOST_PYTHON = (3, 9)

MIN_FREE_MB = {"prepare": 1500, "setup": 700}

READY, NOT_LISTENING, UNAVAILABLE, FOREIGN, NO_ANSWER = 0, 10, 11, 12, 13


# ---------- host Python ----------

def host_python_problem(version, pip_ok, bits=64, wheel_abi=None, implementation="cpython"):
    """Return why this interpreter cannot be used, or None when it can."""
    if tuple(version[:2]) < MIN_HOST_PYTHON:
        return (f"Python {version[0]}.{version[1]} is too old; "
                f"{MIN_HOST_PYTHON[0]}.{MIN_HOST_PYTHON[1]} or newer is required")
    if not pip_ok:
        return "pip is not working for this Python (python -m pip --version failed)"
    if wheel_abi:
        wanted = f"{wheel_abi[2]}.{wheel_abi[3:]}" if wheel_abi.startswith("cp") else wheel_abi
        if implementation != "cpython" or f"{version[0]}.{version[1]}" != wanted:
            return (f"the offline wheels target CPython {wanted} 64-bit but this is "
                    f"{implementation} {version[0]}.{version[1]}")
        if bits != 64:
            return f"the offline wheels target 64-bit Python but this is {bits}-bit"
    return None


def pip_works(python=None):
    try:
        result = subprocess.run([python or sys.executable, "-m", "pip", "--version"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=120, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def cmd_host_python(args):
    version = sys.version_info
    bits = struct.calcsize("P") * 8
    problem = host_python_problem(version, pip_works(), bits, args.wheel_abi,
                                  platform.python_implementation().lower())
    label = f"{version[0]}.{version[1]}.{version[2]} {bits}-bit at {sys.executable}"
    if problem:
        print(f"[X] Unusable Python ({label}): {problem}.")
        return 1
    print(f"[OK] Usable Python: {label}")
    return 0


# ---------- platform, folders, disk ----------

def platform_problem(system, machine, win_version="10.0"):
    """Windows 10+ on x64 only (the bundled runtime and wheels are win_amd64)."""
    if system != "Windows":
        return f"this setup supports Windows 10 x64 only (found {system or 'unknown'})"
    try:
        major = int(str(win_version).split(".")[0])
    except ValueError:
        major = 0
    if major < 10:
        return f"Windows 10 or newer is required (found version {win_version})"
    if str(machine).upper() not in ("AMD64", "X86_64"):
        return f"a 64-bit x64 CPU is required (found {machine or 'unknown'})"
    return None


def native_machine(environ=None):
    """OS architecture even when a 32-bit process runs on 64-bit Windows."""
    env = os.environ if environ is None else environ
    return (env.get("PROCESSOR_ARCHITEW6432") or env.get("PROCESSOR_ARCHITECTURE")
            or platform.machine())


def writable_problem(path):
    """None when files can be created in `path` (or where it would be created)."""
    probe = Path(path)
    while not probe.exists():
        if probe.parent == probe:
            return f"no existing parent folder for {path}"
        probe = probe.parent
    if not probe.is_dir():
        return f"{probe} is not a folder"
    try:
        with tempfile.NamedTemporaryFile(dir=probe, prefix=".write-test-", delete=True):
            pass
    except OSError as exc:
        return f"cannot write to {probe} ({exc})"
    return None


def free_space_problem(path, need_mb, free_bytes=None):
    probe = Path(path)
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        free = shutil.disk_usage(probe).free if free_bytes is None else free_bytes
    except OSError as exc:
        return f"cannot read free disk space for {probe} ({exc})"
    if free < need_mb * 1024 * 1024:
        return f"only {free // (1024 * 1024)} MB free on the drive of {probe}; {need_mb} MB are required"
    return None


def data_dir(root, environ=None):
    """Same rule as backend.store: PERSONNEL_DATA_DIR (absolute) or <root>/data."""
    env = os.environ if environ is None else environ
    raw = (env.get("PERSONNEL_DATA_DIR") or "").strip()
    return Path(raw) if raw else Path(root) / "data"


# ---------- running server detection ----------

def is_file_locked(path):
    """True when another process holds the OS lock the server/supervisor keeps.

    Never creates the file: a missing lock file means nothing is running.
    """
    try:
        fd = os.open(path, os.O_RDWR)
    except OSError:
        return False
    try:
        if os.name == "nt":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError:
                return True
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            return False
        import fcntl
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def classify_response(http_status, body):
    """Map an HTTP answer from the readiness URL to a `ready` exit code."""
    try:
        payload = json.loads(bytes(body[:4096]).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return FOREIGN
    if not isinstance(payload, dict) or payload.get("service") != SERVICE_ID:
        return FOREIGN
    if (http_status == 200 and payload.get("status") == "ready"
            and isinstance(payload.get("schema"), int)):
        return READY
    return UNAVAILABLE


def parse_port(value):
    text = str(DEFAULT_PORT if value in (None, "") else value).strip()
    if not text.isdigit() or not 1 <= int(text) <= 65535:
        raise ValueError(f"PORT must be a number from 1 to 65535 (found {text!r})")
    return int(text)


def _error_numbers(error):
    """Collect portable errno and Windows WSA codes from a socket error."""
    values = {getattr(error, "errno", None), getattr(error, "winerror", None)}
    if getattr(error, "args", None) and isinstance(error.args[0], int):
        values.add(error.args[0])
    return {value for value in values if isinstance(value, int)}


def classify_transport_error(error):
    """Map connection-stage failures without mistaking Windows refusal for HTTP."""
    if isinstance(error, (socket.timeout, TimeoutError)):
        return NO_ANSWER
    if isinstance(error, ConnectionRefusedError):
        return NOT_LISTENING
    numbers = _error_numbers(error)
    refused = {errno.ECONNREFUSED, 10061}  # WSAECONNREFUSED
    timed_out = {errno.ETIMEDOUT, 10060}   # WSAETIMEDOUT
    interrupted = {
        errno.ECONNRESET, errno.ECONNABORTED, errno.EPIPE,
        10053, 10054, 10058,               # WSAECONNABORTED/RESET/SHUTDOWN
    }
    if numbers & refused:
        return NOT_LISTENING
    if numbers & (timed_out | interrupted):
        return NO_ANSWER
    return None


def _transport_detail(error):
    numbers = sorted(_error_numbers(error))
    suffix = f" codes={numbers}" if numbers else ""
    return f"{type(error).__name__}{suffix}"


def probe_ready_detail(port, timeout=2.0):
    """Return readiness code plus a safe diagnostic description."""
    url = f"http://127.0.0.1:{port}{READY_PATH}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=timeout) as response:
            code = classify_response(response.status, response.read(4097))
            return code, f"HTTP {response.status}; {READY_MESSAGES[code]}"
    except urllib.error.HTTPError as exc:
        try:
            code = classify_response(exc.code, exc.read(4097))
            return code, f"HTTP {exc.code}; {READY_MESSAGES[code]}"
        finally:
            exc.close()
    except urllib.error.URLError as exc:
        code = classify_transport_error(exc.reason) or FOREIGN
        return code, f"URL transport {_transport_detail(exc.reason)}; {READY_MESSAGES[code]}"
    except (socket.timeout, TimeoutError) as exc:
        return NO_ANSWER, f"transport {_transport_detail(exc)}; {READY_MESSAGES[NO_ANSWER]}"
    except http.client.RemoteDisconnected as exc:
        return NO_ANSWER, f"HTTP {type(exc).__name__}; {READY_MESSAGES[NO_ANSWER]}"
    except OSError as exc:
        code = classify_transport_error(exc) or FOREIGN
        return code, f"socket {_transport_detail(exc)}; {READY_MESSAGES[code]}"
    except ValueError as exc:
        return FOREIGN, f"request {type(exc).__name__}; {READY_MESSAGES[FOREIGN]}"
    except Exception as exc:  # malformed/non-HTTP answer: not our service
        return FOREIGN, f"HTTP {type(exc).__name__}; {READY_MESSAGES[FOREIGN]}"


def probe_ready(port, timeout=2.0):
    """Ask 127.0.0.1:<port> whether *this* application is ready."""
    return probe_ready_detail(port, timeout)[0]


def port_is_available(port, host="127.0.0.1"):
    """Return True only when a new local server can bind this TCP port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # On Windows this prevents a misleading successful bind when another
        # process already owns the address with sharing enabled.
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            sock.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        sock.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def choose_available_port(preferred, range_start=5000, range_end=5099):
    """Keep a healthy existing instance, otherwise return a bindable port."""
    preferred = parse_port(preferred)
    range_start = parse_port(range_start)
    range_end = parse_port(range_end)
    if range_start > range_end:
        raise ValueError("port range start must not be greater than its end")

    if probe_ready(preferred, 0.5) in (READY, UNAVAILABLE):
        return preferred, "existing"
    candidates = [preferred]
    candidates.extend(port for port in range(range_start, range_end + 1)
                      if port != preferred)
    for port in candidates:
        if port_is_available(port):
            return port, "preferred" if port == preferred else "fallback"
    raise RuntimeError(f"no free local TCP port was found from {range_start} to {range_end}")


def atomic_write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="ascii")
    os.replace(temporary, path)


def cmd_choose_port(args):
    preferred = args.preferred
    if preferred in (None, ""):
        preferred = os.environ.get("PORT")
    if preferred in (None, "") and args.output:
        try:
            preferred = Path(args.output).read_text(encoding="ascii").strip()
            parse_port(preferred)
        except (OSError, UnicodeError, ValueError):
            preferred = None
    try:
        port, reason = choose_available_port(
            preferred, args.range_start, args.range_end)
    except (ValueError, RuntimeError) as exc:
        print(f"[X] Cannot select a server port: {exc}.")
        return 1
    if args.output:
        try:
            atomic_write_text(args.output, f"{port}\n")
        except OSError as exc:
            print(f"[X] Cannot save the selected port to {args.output}: {exc}.")
            return 1
    if reason == "existing":
        print(f"[OK] The Personnel System is already running on port {port}.")
    elif reason == "fallback":
        print(f"[OK] Requested port {parse_port(preferred)} is busy; using free port {port}.")
    else:
        print(f"[OK] Using available port {port}.")
    return 0


def cmd_saved_port(args):
    try:
        value = Path(args.file).read_text(encoding="ascii").strip()
        print(parse_port(value))
    except (OSError, UnicodeError, ValueError):
        return 1
    return 0


READY_MESSAGES = {
    READY: "This application is ready.",
    NOT_LISTENING: "Nothing is listening on the port.",
    UNAVAILABLE: "This application is running but its data cannot be loaded. "
                 "See logs\\server.log and logs\\server-console.log.",
    FOREIGN: "The port is used by a different program (or one that did not answer correctly). "
             "Close it or set the PORT environment variable to a free port.",
    NO_ANSWER: "Something is listening on the port but did not answer in time "
               "(the application may still be starting).",
}


def cmd_ready(args):
    try:
        port = parse_port(args.port)
    except ValueError as exc:
        print(f"[X] {exc}")
        return FOREIGN
    code, detail = probe_ready_detail(port, args.timeout)
    if args.trace:
        print(f"[TRACE] readiness port={port} exit={code}: {detail}")
    if not args.quiet:
        print(f"[{'OK' if code == READY else 'X'}] Port {port}: {READY_MESSAGES[code]}")
    return code


def running_server_problem(root, port):
    """Reason to refuse replacing runtime files, or None when nothing is running."""
    data_lock = data_dir(root) / ".lock"
    if is_file_locked(data_lock):
        return "the Personnel System server is running"
    if probe_ready(port, 1.0) in (READY, UNAVAILABLE):
        return f"the Personnel System server is already answering on port {port}"
    return None


def retire_legacy_autostart(root, environ=None, timeout=65.0, sleep=time.sleep):
    """Disable the retired background supervisor and wait for it to release its lock.

    This is deliberately scoped to this project's exact lock/stop files and the
    old exact Startup shortcut name. It never scans for or kills Python processes.
    Returns None on success, otherwise a printable problem.
    """
    root = Path(root)
    env = os.environ if environ is None else environ
    logs = root / "logs"
    lock = logs / "autostart.lock"
    stop = logs / "autostart.stop"
    appdata = (env.get("APPDATA") or "").strip()
    if appdata:
        shortcut = (Path(appdata) / "Microsoft" / "Windows" / "Start Menu" /
                    "Programs" / "Startup" / "Personnel System.lnk")
        try:
            shortcut.unlink(missing_ok=True)
        except OSError as exc:
            return f"could not remove the old Personnel System Startup shortcut ({exc})"
    if not is_file_locked(lock):
        stop.unlink(missing_ok=True)
        return None
    try:
        logs.mkdir(parents=True, exist_ok=True)
        stop.write_text("stop\n", encoding="ascii")
    except OSError as exc:
        return f"could not request the old autostart supervisor to stop ({exc})"
    deadline = time.monotonic() + timeout
    while is_file_locked(lock) and time.monotonic() < deadline:
        sleep(0.5)
    if is_file_locked(lock):
        return ("the old autostart supervisor did not stop in time; sign out of Windows "
                "or restart the PC, then run PREPARE_ONLINE.bat again")
    stop.unlink(missing_ok=True)
    return None


def cmd_retire_autostart(args):
    root = Path(args.root).resolve() if args.root else ROOT
    problem = retire_legacy_autostart(root, timeout=args.timeout)
    if problem:
        print(f"[X] {problem}.")
        return 1
    print("[OK] Legacy background autostart is disabled. Use START_SYSTEM.bat to run the system.")
    return 0


def cmd_preflight(args):
    root = Path(args.root).resolve() if args.root else ROOT
    failures = []

    def check(problem):
        if problem:
            failures.append(problem)
            print(f"[X] {problem}.")

    check(platform_problem(platform.system(), native_machine(), platform.version())
          if not args.skip_platform else None)
    for name, path in (("installation folder", root), ("data folder", data_dir(root)),
                       ("logs folder", root / "logs"),
                       ("backups folder", data_dir(root).parent / "backups")):
        problem = writable_problem(path)
        check(f"The {name} is not writable: {problem}" if problem else None)
    check(free_space_problem(root, args.min_free_mb or MIN_FREE_MB[args.mode]))
    try:
        port = parse_port(os.environ.get("PORT"))
    except ValueError as exc:
        check(str(exc))
    else:
        running = running_server_problem(root, port)
        if running:
            check(f"Cannot continue: {running}. Run STOP_SYSTEM.bat first, then run this step again")
    if failures:
        return 1
    print("[OK] Preflight checks passed (Windows x64, writable folders, free disk space, server stopped).")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_py = sub.add_parser("host-python")
    p_py.add_argument("--wheel-abi", default=None, help="for example cp311")
    p_pre = sub.add_parser("preflight")
    p_pre.add_argument("--mode", choices=sorted(MIN_FREE_MB), required=True)
    p_pre.add_argument("--root", default=None)
    p_pre.add_argument("--min-free-mb", type=int, default=0)
    p_pre.add_argument("--skip-platform", action="store_true", help="tests only")
    p_ready = sub.add_parser("ready")
    p_ready.add_argument("--port", default=None)
    p_ready.add_argument("--timeout", type=float, default=2.0)
    p_ready.add_argument("--quiet", action="store_true")
    p_ready.add_argument("--trace", action="store_true")
    p_choose = sub.add_parser("choose-port")
    p_choose.add_argument("--preferred", default=None)
    p_choose.add_argument("--range-start", default=5000)
    p_choose.add_argument("--range-end", default=5099)
    p_choose.add_argument("--output", default=None)
    p_saved = sub.add_parser("saved-port")
    p_saved.add_argument("--file", required=True)
    p_retire = sub.add_parser("retire-autostart")
    p_retire.add_argument("--root", default=None)
    p_retire.add_argument("--timeout", type=float, default=65.0)
    args = parser.parse_args(argv)
    return {"host-python": cmd_host_python, "preflight": cmd_preflight,
            "ready": cmd_ready, "choose-port": cmd_choose_port,
            "saved-port": cmd_saved_port,
            "retire-autostart": cmd_retire_autostart}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())

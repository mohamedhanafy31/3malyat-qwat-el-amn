"""Console + log-file output for the deployment helpers (standard library only).

The .bat scripts used to redirect every Python helper into the log, so the
console stayed silent for minutes.  Helpers that import this module print each
line on the console AND append it to the deployment log (the DEPLOY_LOG
environment variable set by tools\\deploy_console.bat), so the caller must not
redirect their stdout into the same file again.

Failure lines start with "[X]" so deploy_console.bat's `failures` command shows
them at the end of a run.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

_STARTED = time.monotonic()


def _log_path() -> str:
    return os.environ.get("DEPLOY_LOG", "")


def _write_console(text: str) -> None:
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        print(text.encode("ascii", "backslashreplace").decode("ascii"), flush=True)
    except (OSError, ValueError):
        pass  # a closed console must never break an install


def _write_log(text: str) -> None:
    path = _log_path()
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8", errors="replace") as stream:
            stream.write(text + "\n")
    except OSError:
        pass


def emit(message: str = "", level: str = "") -> None:
    """Print one line to the console and the log.

    level: "" plain, "OK", "WARN", "INFO", or "X" (failure, line starts "[X]").
    """
    if level == "X":
        line = f"[X] {message}"
    else:
        stamp = time.strftime("%H:%M:%S")
        tag = f"[{level}] " if level else ""
        line = f"[{stamp}] {tag}{message}"
    _write_console(line)
    _write_log(line)


def elapsed() -> str:
    return f"{time.monotonic() - _STARTED:.0f}s"


def human_size(count: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if count < 1024 or unit == "GB":
            return f"{count:.0f} {unit}" if unit == "B" else f"{count:.1f} {unit}"
        count /= 1024
    return f"{count:.1f} GB"


def stream_run(command, env=None, cwd=None, timeout=None, check=False, label="", prefix="    | "):
    """Run a command, echoing every output line live to console and log.

    Returns an object with .returncode and .tail (last 40 output lines).  A
    timeout kills the process and reports returncode -9 with .timed_out set.
    """
    command = [str(part) for part in command]
    # A Python child writing to a pipe buffers stdout, which would reorder its
    # lines against stderr in the live log.
    env = dict(os.environ if env is None else env)
    env.setdefault("PYTHONUNBUFFERED", "1")
    emit(f"{label or 'Running'}: {' '.join(command)}", "INFO")
    started = time.monotonic()
    tail: list[str] = []
    timed_out = threading.Event()
    try:
        process = subprocess.Popen(
            command, env=env, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1)
    except OSError as exc:
        emit(f"Could not start the command: {type(exc).__name__}: {exc}", "WARN")
        return SimpleNamespace(returncode=127, tail=[str(exc)], timed_out=False)
    timer = None
    if timeout:
        def kill():
            timed_out.set()
            process.kill()
        timer = threading.Timer(timeout, kill)
        timer.daemon = True
        timer.start()
    try:
        for raw in process.stdout:
            line = raw.rstrip("\r\n")
            if not line.strip():
                continue
            tail.append(line)
            del tail[:-40]
            _write_console(prefix + line)
            _write_log(prefix + line)
        process.wait()
    finally:
        if timer:
            timer.cancel()
    code = -9 if timed_out.is_set() else process.returncode
    note = f" (killed after {timeout}s timeout)" if timed_out.is_set() else ""
    emit(f"Command finished with exit code {code}{note} in {time.monotonic() - started:.1f}s",
         "INFO" if code == 0 else "WARN")
    result = SimpleNamespace(returncode=code, tail=tail, timed_out=timed_out.is_set())
    if check and code != 0:
        raise subprocess.CalledProcessError(code, command)
    return result

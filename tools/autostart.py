"""مشرف التشغيل التلقائي — بيشتغل مخفي مع دخول ويندوز (اختصار في مجلد Startup
بيعمله INSTALL_AUTOSTART.bat) ويشغّل serve.py، ولو السيرفر وقع لأي سبب بيرجّعه
تاني بعد مهلة بتزيد تدريجيًا لحد دقيقة.

الإيقاف المقصود: STOP_SYSTEM.bat بيكتب `logs/autostart.stop` وبعدين يقفل السيرفر،
فالمشرف يشوف الملف ويخرج بدل ما يعيد التشغيل.

التشغيل اليدوي (للتجربة): pythonw tools\\autostart.py
"""
import logging
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"
STOP_FILE = LOG_DIR / "autostart.stop"
LOCK_FILE = LOG_DIR / "autostart.lock"

MIN_DELAY = 5
MAX_DELAY = 60
# لو السيرفر فضل شغّال أطول من كده، الوقعة دي مش جزء من سلسلة فشل متكرر
HEALTHY_RUN = 60


def _single_instance():
    """قفل على ملف — نسخة واحدة بس من المشرف. نظام التشغيل بيفك القفل لو العملية ماتت."""
    handle = open(LOCK_FILE, "a+")
    try:
        if sys.platform == "win32":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def _logger():
    handler = logging.FileHandler(LOG_DIR / "autostart.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log = logging.getLogger("autostart")
    log.setLevel(logging.INFO)
    log.addHandler(handler)
    return log


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    lock = _single_instance()
    if lock is None:
        return 0
    log = _logger()
    STOP_FILE.unlink(missing_ok=True)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    delay = MIN_DELAY
    log.info("Supervisor started (python=%s)", sys.executable)
    while not STOP_FILE.exists():
        started = time.monotonic()
        proc = subprocess.Popen([sys.executable, str(ROOT / "serve.py")],
                                cwd=str(ROOT), creationflags=flags)
        code = proc.wait()
        if STOP_FILE.exists():
            break
        delay = MIN_DELAY if time.monotonic() - started > HEALTHY_RUN else min(delay * 2, MAX_DELAY)
        log.warning("Server exited with code %s; restarting in %ss", code, delay)
        time.sleep(delay)
    log.info("Stop requested; supervisor exiting")
    STOP_FILE.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

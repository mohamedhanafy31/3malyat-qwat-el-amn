"""تشغيل أكثر استقرارًا من `python app.py` — بيستخدم waitress (سيرفر WSGI حقيقي)
بدل سيرفر التطوير بتاع Flask، وبيعيد المحاولة تلقائيًا لو السيرفر وقع.

`python app.py` كافي تمامًا للاستخدام العادي اليومي. استخدم السكربت ده بدله لو
عايز السيستم يفضل شغال أطول فترة من غير تدخل (مثلاً كخدمة خلفية على الجهاز).

waitress بتتجهّز مع باقي الحزم في SETUP_OFFLINE.bat — مفيش تثبيت منفصل
ولا إنترنت. START_SYSTEM.bat بيستخدم الملف ده تلقائيًا لو waitress موجودة.

التشغيل اليدوي: python serve.py   (أو: PORT=5050 python serve.py)
"""
import errno
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import time
from pathlib import Path

# Python Embedded مع `python311._pth` لا يضيف مجلد السكربت تلقائيًا.
# استخدم مسار serve.py نفسه حتى يعمل النقل إلى أي قرص/مجلد، حتى مع المسافات.
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from waitress import serve
except ImportError:
    raise SystemExit(
        "waitress مش موجودة في بيئة التشغيل.\n"
        "شغّل SETUP_OFFLINE.bat مرة واحدة، أو شغّل بدل كده: python app.py\n"
        "(سيرفر Flask العادي شغّال تمامًا للاستخدام اليومي)."
    )

from app import app
from backend import store
from backend.daily_files import start_worker

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "5000"))
THREADS = max(2, int(os.environ.get("WAITRESS_THREADS", "8")))


def _configure_logging():
    """إخراج موحد للكونسول وملف دوّار بدل فقدان أخطاء التشغيل."""
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / "server.log", maxBytes=5 * 1024 * 1024,
                                  backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)
    # pythonw.exe has no console and may expose stdout as None.
    if sys.stdout is not None:
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        root.addHandler(console)
    logging.getLogger("waitress").setLevel(logging.INFO)
    return logging.getLogger("personnel-system")

# «المنفذ مستخدم بالفعل» رقمه بيختلف حسب النظام:
#   لينكس   : errno.EADDRINUSE = 98
#   ويندوز  : errno.EADDRINUSE = 100، والسوكت بيرجّع كمان WSAEADDRINUSE = 10048
# `errno.EADDRINUSE` لوحده بيجيب الرقم الصح لكل نظام، و10048 مكتوب صراحةً
# عشان الفحص ما يعتمدش على إن وحدة errno فيها WSAEADDRINUSE أصلًا (مش
# موجودة على لينكس، والرقم ده مش errno صالح هناك فمش هيلخبط حاجة).
WSAEADDRINUSE = 10048
_PORT_IN_USE = {errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", WSAEADDRINUSE),
                WSAEADDRINUSE}


def _is_port_in_use(exc):
    if not isinstance(exc, OSError):
        return False
    # ويندوز ساعات بيحطّ الكود في winerror بدل errno
    return (exc.errno in _PORT_IN_USE
            or getattr(exc, "winerror", None) == WSAEADDRINUSE)


def _port_conflict_message():
    """رسالة واضحة بالعربي والإنجليزي — المنفذ مشغول مش عطل مؤقت.

    ده مش سبب لإعادة المحاولة: طول ما الحاجة التانية ماسكة المنفذ، كل محاولة
    جاية هتفشل بنفس الشكل. الإصرار كان بيملا الشاشة برسايل متكررة للأبد
    من غير ما يقول للمشغّل يعمل إيه.
    """
    return (
        f"\n[X] المنفذ {PORT} مستخدم بالفعل — السيستم مش هيقدر يشتغل عليه.\n"
        f"[X] Port {PORT} is already in use.\n"
        f"\n"
        f"    الأغلب إن السيستم شغّال في شاشة تانية مفتوحة — اقفلها وجرّب تاني.\n"
        f"    Most likely the system is already running in another window.\n"
        f"\n"
        f"    ولو محتاج تغيّر رقم المنفذ، اضبط متغير البيئة PORT قبل التشغيل،\n"
        f"    مثلًا من نافذة CMD:\n"
        f'        set PORT=5050\n'
        f"        START_SYSTEM.bat\n"
        f"    (START_SYSTEM.bat بيستخدم PORT لو متضبط، وإلا 5000).\n"
    )


def main():
    logger = _configure_logging()
    logger.info("[startup 1/5] Python=%s root=%s", sys.executable, PROJECT_ROOT)
    try:
        logger.info("[startup 2/5] Acquiring exclusive data lock in %s", store.DATA_DIR)
        store.acquire_process_lock()
        logger.info("[startup 3/5] Data lock acquired; starting daily-files worker")
        start_worker()
    except SystemExit as exc:
        logger.error("Startup stopped before the HTTP server could bind: %s", exc)
        return exc.code if isinstance(exc.code, int) else 1
    except Exception:
        logger.exception("Startup failed before the HTTP server could bind")
        return 1
    logger.info("[startup 4/5] Binding Waitress to http://%s:%s (threads=%s)",
                HOST, PORT, THREADS)
    while True:
        try:
            serve(app, host=HOST, port=PORT, threads=THREADS,
                  channel_timeout=120, asyncore_use_poll=True)
            logger.info("[startup 5/5] Waitress stopped normally")
            break  # serve() ما بترجعش إلا لو السيرفر اتقفل عمدًا
        except Exception as exc:
            # تعارض المنفذ حالة نهائية — خروج نضيف برسالة، من غير إعادة محاولة
            if _is_port_in_use(exc):
                logger.error(_port_conflict_message())
                return 1
            logger.exception("Server stopped unexpectedly; retrying in 3 seconds")
            time.sleep(3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

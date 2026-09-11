"""تشغيل أكثر استقرارًا من `python app.py` — بيستخدم waitress (سيرفر WSGI حقيقي)
بدل سيرفر التطوير بتاع Flask، وبيعيد المحاولة تلقائيًا لو السيرفر وقع.

`python app.py` كافي تمامًا للاستخدام العادي اليومي. استخدم السكربت ده بدله لو
عايز السيستم يفضل شغال أطول فترة من غير تدخل (مثلاً كخدمة خلفية على الجهاز).

waitress بتتجهّز مع باقي الحزم في SETUP_OFFLINE.bat — مفيش تثبيت منفصل
ولا إنترنت. START_SYSTEM.bat بيستخدم الملف ده تلقائيًا لو waitress موجودة.

التشغيل اليدوي: python serve.py   (أو: PORT=5050 python serve.py)
"""
import errno
import os
import time

try:
    from waitress import serve
except ImportError:
    raise SystemExit(
        "waitress مش موجودة في بيئة التشغيل.\n"
        "شغّل SETUP_OFFLINE.bat مرة واحدة، أو شغّل بدل كده: python app.py\n"
        "(سيرفر Flask العادي شغّال تمامًا للاستخدام اليومي)."
    )

from app import app

PORT = int(os.environ.get("PORT", "5000"))

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
        f"    ولو محتاج تغيّر رقم المنفذ، افتح الملف:  START_SYSTEM.bat\n"
        f"    ودوّر على السطر:\n"
        f'        set "PORT={PORT}"\n'
        f"    غيّر الرقم (مثلاً 5050) واحفظ الملف وشغّله تاني.\n"
    )


if __name__ == "__main__":
    print(f"Personnel System (waitress) starting on http://127.0.0.1:{PORT} ...")
    while True:
        try:
            serve(app, host="127.0.0.1", port=PORT)
            break  # serve() ما بترجعش إلا لو السيرفر اتقفل عمدًا
        except Exception as exc:
            # تعارض المنفذ حالة نهائية — خروج نضيف برسالة، من غير إعادة محاولة
            if _is_port_in_use(exc):
                raise SystemExit(_port_conflict_message())
            print(f"السيرفر وقع ({exc}) — بيعيد التشغيل خلال 3 ثواني...")
            time.sleep(3)

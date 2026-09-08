"""تشغيل أكثر استقرارًا من `python app.py` — بيستخدم waitress (سيرفر WSGI حقيقي)
بدل سيرفر التطوير بتاع Flask، وبيعيد المحاولة تلقائيًا لو السيرفر وقع.

`python app.py` كافي تمامًا للاستخدام العادي اليومي. استخدم السكربت ده بدله لو
عايز السيستم يفضل شغال أطول فترة من غير تدخل (مثلاً كخدمة خلفية على الجهاز).

التثبيت (مرة واحدة بس): pip install waitress
التشغيل: python serve.py   (أو: PORT=5050 python serve.py)
"""
import os
import time

try:
    from waitress import serve
except ImportError:
    raise SystemExit(
        "waitress مش متثبت. ثبّته الأول بـ: pip install waitress\n"
        "أو شغّل بدل كده: python app.py (سيرفر التطوير العادي، شغال برضو)."
    )

from app import app

PORT = int(os.environ.get("PORT", "5000"))

if __name__ == "__main__":
    print(f"Personnel System (waitress) running at http://127.0.0.1:{PORT}")
    while True:
        try:
            serve(app, host="127.0.0.1", port=PORT)
            break  # serve() ما بترجعش إلا لو السيرفر اتقفل عمدًا
        except Exception as exc:
            print(f"السيرفر وقع ({exc}) — بيعيد التشغيل خلال 3 ثواني...")
            time.sleep(3)

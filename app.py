import os

from flask import Flask, jsonify

from backend.routes import register_routes
from backend.store import SchemaMismatch, acquire_process_lock

app = Flask(__name__)

# النظام كله عربي، وFlask افتراضيًا بيهرّب كل حرف عربي لـ\uXXXX في الـJSON
# — ده بيكبّر كل استجابة لأكتر من الضعف على الفاضي. UTF-8 مباشرة أصغر وأسرع.
app.json.ensure_ascii = False

# سقف حجم الطلب كله — قبل ما فلاسك حتى يبدأ يقرا جسم الطلب، عشان رفع صورة
# ضخم أو غلط ما يحاولش يتحمّل كامل في الذاكرة الأول. صور دليل الخدمات
# نفسها محدودة بـ8MB (`service_catalog.MAX_IMAGE_BYTES`)، والسقف هنا أعلى
# شوية لأي هامش بروتوكول.
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024

register_routes(app)


@app.url_defaults
def _bust_static_cache(endpoint, values):
    """كل رابط `static` بياخد `?v=<وقت تعديل الملف>` تلقائيًا، عشان المتصفح
    يجيب نسخة جديدة أول ما JS/CSS يتغيّر بدل ما يفضل شغّال على نسخة قديمة
    متخزّنة عنده من قبل — ده كان بيسبب صفحة فاضية تمامًا بعد أي تحديث
    للسيستم من غير ما المستخدم يعمل Hard Refresh."""
    if endpoint == "static" and "filename" in values:
        path = os.path.join(app.static_folder, values["filename"])
        try:
            values["v"] = int(os.path.getmtime(path))
        except OSError:
            pass


@app.errorhandler(SchemaMismatch)
def _schema_mismatch(exc):
    """ملف بيانات ببنية مختلفة — رسالة واضحة بدل 500 صامت."""
    return jsonify({"error": str(exc)}), 503


if __name__ == "__main__":
    acquire_process_lock()
    port = int(os.environ.get("PORT", "5000"))
    print(f"Personnel System running at http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)

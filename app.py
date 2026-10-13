import gzip
import os

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge
import uuid

from backend.routes import register_routes
from backend.store import SchemaMismatch, acquire_process_lock
from backend.auth import init_app as init_auth

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
init_auth(app)


@app.url_defaults
def _bust_static_cache(endpoint, values):
    """كل رابط `static` بياخد `?v=<وقت تعديل الملف>` تلقائيًا، عشان المتصفح
    يجيب نسخة جديدة أول ما JS/CSS يتغيّر بدل ما يفضل شغّال على نسخة قديمة
    متخزّنة عنده من قبل — ده كان بيسبب صفحة فاضية تمامًا بعد أي تحديث
    للسيستم من غير ما المستخدم يعمل Hard Refresh."""
    if endpoint == "static" and "filename" in values:
        path = os.path.join(app.static_folder, values["filename"])
        # بيتحسب مع كل رابط (مش مرة واحدة لكل تشغيل): الملفات الثابتة بتتخزّن عند
        # المتصفح سنة كاملة (`_compress_and_cache`)، فلو ملف اتعدّل والسيستم شغّال
        # والختم ثابت، المتصفح هيفضل على النسخة القديمة لحد إعادة التشغيل.
        try:
            values["v"] = int(os.path.getmtime(path))
        except OSError:
            pass


_COMPRESSIBLE = ("application/json", "application/javascript", "image/svg+xml")
_GZIP_MIN_BYTES = 1024
# نسخة مضغوطة واحدة لكل ملف ثابت (مفتاحها المسار + الـETag) بدل ما نضغط
# pdf.worker (1MB+) من الأول مع كل طلب
_STATIC_GZIP = {}


@app.after_request
def _compress_and_cache(response):
    """الموبايل بيوصل للسيستم عبر Tailscale وأحيانًا عبر Relay بعيد — حجم الرد
    وعدد الرحلات هما اللي بيحددوا السرعة، مش وقت السيرفر.

    - الملفات الثابتة المختومة بـ`?v=` (_bust_static_cache) اسمها بيتغيّر مع أي
      تعديل، فبتتخزّن عند المتصفح سنة كاملة بدل ما كل صفحة تسأل عنها السيرفر تاني.
    - JSON وHTML وCSS وJS بيتضغطوا gzip: بيانات زي سجل الراحات بتصغر ~94%.
    """
    is_static = request.path.startswith("/static/")
    if is_static and response.status_code in (200, 304) and request.args.get("v"):
        response.cache_control.no_cache = None
        response.cache_control.public = True
        response.cache_control.max_age = 31536000
        response.cache_control.immutable = True

    mimetype = response.mimetype or ""
    if (response.status_code != 200
            or "gzip" not in request.headers.get("Accept-Encoding", "").lower()
            or "Content-Encoding" in response.headers
            or not (mimetype.startswith("text/") or mimetype in _COMPRESSIBLE)
            or (response.is_streamed and not response.direct_passthrough)):
        return response

    response.vary.add("Accept-Encoding")
    key = None
    if is_static:
        etag = response.get_etag()[0]
        key = (request.path, etag) if etag else None
    body = _STATIC_GZIP.get(key) if key else None
    if body is None:
        response.direct_passthrough = False
        raw = response.get_data()
        if len(raw) < _GZIP_MIN_BYTES:
            return response
        body = gzip.compress(raw, compresslevel=6)
        if key:
            _STATIC_GZIP[key] = body
    response.direct_passthrough = False
    response.set_data(body)
    response.headers["Content-Encoding"] = "gzip"
    return response


@app.errorhandler(SchemaMismatch)
def _schema_mismatch(exc):
    """ملف بيانات ببنية مختلفة — رسالة واضحة بدل 500 صامت."""
    return jsonify({"error": str(exc)}), 503


@app.errorhandler(RequestEntityTooLarge)
def _too_large(exc):
    return jsonify({"error": "حجم الطلب أكبر من الحد المسموح.", "code": "payload_too_large"}), 413


@app.errorhandler(Exception)
def _unexpected(exc):
    if isinstance(exc, HTTPException):
        return exc
    if app.testing:
        raise exc
    incident = uuid.uuid4().hex[:12]
    app.logger.exception("Unhandled incident %s", incident)
    return jsonify({"error": "حدث خطأ داخلي.", "incident": incident}), 500


if __name__ == "__main__":
    acquire_process_lock()
    port = int(os.environ.get("PORT", "5000"))
    print(f"Personnel System running at http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)

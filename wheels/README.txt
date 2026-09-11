مجلد الحزم الجاهزة للتثبيت بدون إنترنت.

بيتملى مرة واحدة على جهاز فيه إنترنت بتشغيل:  PREPARE_ONLINE.bat
وبعدين بينتقل مع المشروع كله للجهاز المعزول، و SETUP_OFFLINE.bat بيفكّه.

المفروض يحتوي على (لويندوز 64-bit / Python 3.11):
    flask, werkzeug, jinja2, markupsafe, itsdangerous, click, blinker, waitress

ملاحظة: markupsafe فيها جزء مكتوب بـC، فلازم الحزمة تكون منزّلة لنفس
نسخة بايثون اللي في runtime\  (cp311 لو النسخة 3.11).

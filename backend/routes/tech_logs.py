"""صفحة السجلات الفنية للمشرف (صلاحية view_logs): آخر الأسطر + تنزيل الملفات."""
import io
import logging
import tempfile
import zipfile

from flask import Blueprint, jsonify, request, send_file

from .. import tech_log

bp = Blueprint("tech_logs", __name__)


@bp.get("/api/tech-logs")
def tail():
    name = request.args.get("file", "system")
    level = request.args.get("level", "").upper() or None
    try:
        count = max(1, min(2000, int(request.args.get("lines", 300))))
    except ValueError:
        count = 300
    if name not in tech_log.FILES:
        return jsonify(error="ملف سجل غير معروف.", code="invalid"), 400
    if level and level not in tech_log.LEVELS:
        return jsonify(error="مستوى غير معروف.", code="invalid"), 400
    result = tech_log.read_tail(name, count, level, request.args.get("q"))
    result["level"] = logging.getLevelName(logging.getLogger().level)
    return jsonify(result)


@bp.get("/api/tech-logs/download")
def download():
    """`file=system|errors` ملف واحد، أو `file=all` ملف zip بكل الملفات (للإرسال للدعم)."""
    name = request.args.get("file", "all")
    files = tech_log.list_log_files()
    if name in tech_log.FILES:
        wanted = [p for p in files if p.name == tech_log.FILES[name]]
        if not wanted:
            return jsonify(error="الملف غير موجود بعد.", code="not_found"), 404
        return send_file(wanted[0], as_attachment=True, download_name=wanted[0].name,
                         mimetype="text/plain")
    if name != "all":
        return jsonify(error="ملف سجل غير معروف.", code="invalid"), 400
    if not files:
        return jsonify(error="لا توجد ملفات سجل بعد.", code="not_found"), 404
    buffer = tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024)
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            try:
                archive.write(path, path.name)
            except OSError:
                continue
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="technical-logs.zip",
                     mimetype="application/zip")

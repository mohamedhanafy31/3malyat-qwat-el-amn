"""سجل خدمات الضابط — API للقراءة بس، مفيش كتابة فمفيش قفل."""
from io import BytesIO
from datetime import date

from flask import Blueprint, jsonify, request, send_file

from .. import officer_log as officer_log_lib
from ..store import load_data
from ..utils import range_filters, recorded_range_scope
from ..register_export import build_register_docx, register_file_name

bp = Blueprint("officer_log", __name__)
_MONTHS = ("يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
           "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر")


def _date_label(value):
    parsed = date.fromisoformat(value)
    return f"{parsed.day} {_MONTHS[parsed.month - 1]} {parsed.year}"


@bp.get("/api/officer-log/<officer_id>")
def get_officer_log(officer_id):
    filters, error = range_filters(request.args)
    if error:
        return jsonify({"error": error}), 400
    # الأيام المسجّلة فعلًا جوّه المدى بس (الافتراضي آخر 30 يوم مسجّل)
    data = load_data(recorded_range_scope(filters))
    result = officer_log_lib.build(data, officer_id, filters)
    if result is None:
        return jsonify({"error": "الضابط غير موجود."}), 404
    return jsonify(result)


@bp.get("/api/officer-log/<officer_id>/export.docx")
def export_officer_log(officer_id):
    filters, error = range_filters(request.args)
    if error:
        return jsonify({"error": error}), 400
    data = load_data(recorded_range_scope(filters))
    result = officer_log_lib.build(data, officer_id, filters)
    if result is None:
        return jsonify({"error": "الضابط غير موجود."}), 404
    rows = []
    for row in result["rows"]:
        services = "\n".join(f'{s["name"]} — {s["shift"]}' for s in row["services"]) or "—"
        if row["taqseera"]:
            services += "\nتقصيرة"
        status = row["leave"]["type"] if row["leave"] else row["group"]
        if row["group"] != "صافي" and row["bucket"]:
            status += f' — {row["bucket"]}'
        rows.append([_date_label(row["date"]), row["weekday"], services, status, row["note"] or "—"])
    title = f'سجل خدمات {result["officer"]["role"]} / {result["officer"]["name"]}'
    subtitle = f'من {_date_label(result["date_from"])} إلى {_date_label(result["date_to"])}'
    content = build_register_docx(title, [("التاريخ", 1), ("اليوم", .8), ("الخدمات", 2.2),
        ("الحالة", 1.2), ("ملاحظة", 1.8)], rows, subtitle=subtitle)
    return send_file(BytesIO(content), as_attachment=True,
                     download_name=register_file_name("سجل خدمات الضابط"),
                     mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

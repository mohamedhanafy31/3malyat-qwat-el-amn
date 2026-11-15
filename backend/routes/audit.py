"""قراءة سجل النشاط بالتصفية والتقسيم لصفحات."""
from datetime import date, timedelta
from io import BytesIO

from flask import Blueprint, jsonify, request, send_file

from ..auth.audit_log import activity_stats, query
from ..auth.labels import EVENT_LABELS
from ..register_export import build_register_docx, register_file_name

bp = Blueprint("audit", __name__)
_MONTHS = ("يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
           "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر")


def _date_label(value):
    try:
        parsed = date.fromisoformat(value)
        return f"{parsed.day} {_MONTHS[parsed.month - 1]} {parsed.year}"
    except (TypeError, ValueError):
        return value or "—"


@bp.get("/api/audit")
def get_audit():
    try:
        limit = max(1, min(500, int(request.args.get("limit", 100))))
    except ValueError:
        limit = 100
    entries, next_before, names = query(limit, request.args.get("before"),
        request.args.get("user"), request.args.get("event"), request.args.get("from"),
        request.args.get("to"), request.args.get("q"))
    return jsonify(entries=entries, next_before=next_before,
                   events=[{"key": k, "label": v} for k, v in EVENT_LABELS.items()], users=names)


@bp.get("/api/audit/export.docx")
def export_audit():
    params = {key: request.args.get(key) for key in ("user", "event", "from", "to", "q")}
    entries, _, _ = query(3001, user=params["user"], event=params["event"],
        from_day=params["from"], to_day=params["to"], q=params["q"])
    capped = len(entries) > 3000
    entries = entries[:3000]
    rows = [[f'{_date_label(e["ts"][:10])}\n{e["ts"][11:19]}', e.get("display_name") or e.get("username") or "—",
        e.get("event_label") or e.get("event") or "—", e.get("action_label") or "—"] for e in entries]
    filters = []
    if params["from"]: filters.append(f'من {_date_label(params["from"])}')
    if params["to"]: filters.append(f'إلى {_date_label(params["to"])}')
    if params["user"]: filters.append(f'المستخدم: {params["user"]}')
    if params["event"]: filters.append(f'الحدث: {EVENT_LABELS.get(params["event"], params["event"])}')
    if params["q"]: filters.append(f'بحث: «{params["q"]}»')
    content = build_register_docx("سجل النشاط", [("الوقت", 1.2), ("المستخدم", 1.2),
        ("الحدث", 1), ("التفاصيل", 2)], rows, subtitle=" — ".join(filters) or "كل سجلات النشاط",
        footer_note="تم عرض أحدث 3000 سجل فقط." if capped else "")
    return send_file(BytesIO(content), as_attachment=True, download_name=register_file_name("سجل النشاط"),
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


def _activity_range():
    today = date.today()
    raw_from = request.args.get("from") or (today - timedelta(days=29)).isoformat()
    raw_to = request.args.get("to") or today.isoformat()
    try:
        start, end = date.fromisoformat(raw_from), date.fromisoformat(raw_to)
    except ValueError:
        return None, None, (jsonify(error="مدى التاريخ غير صحيح.", code="invalid_date"), 400)
    if start > end:
        return None, None, (jsonify(error="تاريخ البداية يجب ألا يتجاوز تاريخ النهاية.",
                                           code="invalid_range"), 400)
    if (end - start).days > 366:
        return None, None, (jsonify(error="أقصى مدى للتحليل 367 يومًا.",
                                           code="range_too_large"), 400)
    return start.isoformat(), end.isoformat(), None


@bp.get("/api/activity-stats")
def get_activity_stats():
    from_day, to_day, error = _activity_range()
    if error:
        return error
    return jsonify(activity_stats(from_day, to_day))

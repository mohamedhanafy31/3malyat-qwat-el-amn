"""قراءة سجل النشاط بالتصفية والتقسيم لصفحات."""
from datetime import date, timedelta

from flask import Blueprint, jsonify, request

from ..auth.audit_log import activity_stats, query
from ..auth.labels import EVENT_LABELS

bp = Blueprint("audit", __name__)


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

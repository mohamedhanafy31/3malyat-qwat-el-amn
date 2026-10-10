"""قراءة سجل النشاط بالتصفية والتقسيم لصفحات."""
from flask import Blueprint, jsonify, request

from ..auth.audit_log import query
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

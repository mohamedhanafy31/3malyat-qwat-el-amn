"""سجل التغييرات — عرض وتصفية بالكيان أو بسجل بعينه."""
from flask import Blueprint, jsonify, request

from .. import changes
from ..store import load_data
from ..utils import canonical_day

bp = Blueprint("changes", __name__)


@bp.get("/api/changes")
def get_changes():
    data = load_data(())
    try:
        limit = min(int(request.args.get("limit", 200) or 200), 1000)
    except ValueError:
        limit = 200
    entity = request.args.get("entity", "").strip() or None
    entity_id = request.args.get("entity_id", "").strip() or None
    day = canonical_day(request.args.get("day", "").strip()) or None
    from_day = canonical_day(request.args.get("from_day", "").strip()) or None
    to_day = canonical_day(request.args.get("to_day", "").strip()) or None
    return jsonify({"entries": changes.recent(data, limit=limit, entity=entity,
                                              entity_id=entity_id, day=day,
                                              from_day=from_day, to_day=to_day)})

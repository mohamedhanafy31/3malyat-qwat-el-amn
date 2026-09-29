"""إغلاق/فتح اليوم."""
from flask import Blueprint, jsonify

from .. import changes
from .. import day_status as day_status_lib
from ..store import AbortRequest, load_data, with_data
from ..utils import canonical_day, json_payload

bp = Blueprint("day_status", __name__)


@bp.get("/api/day-status/<day>")
def get_day_status(day):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    return jsonify(day_status_lib.status_of(load_data(), day))


@bp.post("/api/day-status/<day>/close")
def close_day(day):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    payload = json_payload()
    closed_by = str(payload.get("closed_by", "")).strip()

    def mutate(data):
        if day_status_lib.is_closed(data, day):
            raise AbortRequest((jsonify({"error": "اليوم مغلق بالفعل."}), 409))
        entry = day_status_lib.close_day(data, day, closed_by)
        changes.record(data, "day_lock", day, "close", after=dict(entry), day=day,
                       text=f"قفل يوم {day}" + (f" — {closed_by}" if closed_by else ""))
        return jsonify(entry), 201

    return with_data(mutate)


@bp.post("/api/day-status/<day>/reopen")
def reopen_day(day):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    payload = json_payload()
    reason = str(payload.get("reason", "")).strip()
    if not reason:
        return jsonify({"error": "سبب فتح اليوم مطلوب."}), 400

    reopened_by = str(payload.get("reopened_by", "")).strip()

    def mutate(data):
        if not day_status_lib.is_closed(data, day):
            raise AbortRequest((jsonify({"error": "اليوم غير مغلق أصلًا."}), 409))
        before = dict(day_status_lib.status_of(data, day))
        entry = day_status_lib.reopen_day(data, day, reason, reopened_by)
        changes.record(data, "day_lock", day, "reopen", before=before, after=dict(entry),
                       reason=reason, day=day,
                       text=f"فتح استثنائي ليوم {day} — السبب: {reason}")
        return jsonify(entry)

    return with_data(mutate)

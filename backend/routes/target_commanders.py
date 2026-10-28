from flask import Blueprint, jsonify

from .. import day_status
from .. import target_commanders as lib
from ..store import AbortRequest, load_data, stale_revision, with_data
from ..utils import canonical_day, json_payload

bp = Blueprint("target_commanders", __name__)


@bp.get("/api/target-commanders/<day>")
def get_target_commanders(day):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    return jsonify(lib.view(load_data(()), day))


@bp.put("/api/target-commanders/<day>")
def put_target_commanders(day):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    if day < day_status.today_iso():
        return jsonify({"error": "لا يمكن تغيير قادة الأهداف بتاريخ سابق. يمكنك عرضه فقط."}), 409
    body = json_payload()

    def mutate(data):
        stale = stale_revision(data, body.get("revision"), ())
        if stale:
            raise AbortRequest((jsonify({
                "code": "stale_revision", "revision": stale,
                "error": "تغيّرت بيانات الضباط؛ أعد تحميل الكشف قبل الحفظ.",
            }), 409))
        payload, error = lib.apply(data, day, body.get("assignments"))
        if error:
            raise AbortRequest((jsonify({"error": error}), 400))
        return jsonify(payload)

    return with_data(mutate, ())

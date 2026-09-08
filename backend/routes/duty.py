"""يومية تشغيل الضباط — العرض، وحالة الضابط اليومية.

التكليف بخدمة بقى من `/api/assignments/<day>` (نفس النقطة اللي اللوحة
بتستخدمها) — الصفحة دي بتعدّل **حالة** الضابط بس: تقصيرة، انتداب/غياب/
مرضي/فرقة/طارئة، وملاحظة. دي حقيقة مختلفة عن التكليف مش نسخة تانية منه.
"""
from flask import Blueprint, jsonify

from ..assignments import OFFICER_STATUSES, set_officer_state
from ..duty import summarise
from ..people import officers_on
from ..store import AbortRequest, load_data, with_data
from ..utils import json_payload, parse_date

bp = Blueprint("duty", __name__)


@bp.get("/api/duty/<day>")
def get_duty(day):
    if not parse_date(day):
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    return jsonify(summarise(load_data(), day))


@bp.put("/api/duty/<day>/<person_id>")
def set_state(day, person_id):
    """حالة الضابط في يوم معيّن. التكليفات مش هنا — دي في /api/assignments."""
    if not parse_date(day):
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    payload = json_payload()

    status = str(payload.get("status", "")).strip()
    if status and status not in OFFICER_STATUSES:
        return jsonify({"error": "حالة غير صحيحة."}), 400

    def mutate(data):
        # الحالة بتتقاس على قوة اليوم نفسه، فالضابط المتأرشف ينفع يتعدّل
        # في يوم كان فيه بالقوة
        if not any(o.get("id") == person_id for o in officers_on(data, day)):
            raise AbortRequest((jsonify({"error": "الضابط لم يكن على القوة في هذا اليوم."}), 404))
        set_officer_state(data, day, person_id,
                          taqseera=bool(payload.get("taqseera")),
                          status=status,
                          note=str(payload.get("note", "")).strip())
        return jsonify(summarise(data, day))

    return with_data(mutate)

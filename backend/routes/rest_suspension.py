"""وقف الراحات — أوامر الوقف العام (إنشاء/مرشّحين/فتح/عرض).
إيقاف راحة واحدة بعينها في `routes/leaves.py` (`POST /api/leaves/<id>/stop`)."""
from flask import Blueprint, jsonify, request

from .. import day_status
from .. import rest_suspension as lib
from .. import retro
from ..constants import LEAVE_TYPES
from ..store import load_data, with_data
from ..utils import canonical_day, json_payload

bp = Blueprint("rest_suspension", __name__)


@bp.get("/api/rest-suspensions")
def list_suspensions():
    out = lib.listing(load_data(()))
    today = day_status.today_iso()
    for o in out["active"]:
        o["can_restore"] = lib.can_restore(o, today)
    return jsonify(out)


@bp.get("/api/rest-suspensions/candidates")
def list_candidates():
    types = [t for t in request.args.getlist("type") if t in LEAVE_TYPES]
    today = day_status.today_iso()
    return jsonify({"today": today, "rows": lib.candidates(load_data(()), types, today)})


@bp.get("/api/rest-suspensions/day/<day>")
def day_summary(day):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    return jsonify(lib.on_day(load_data(()), day))


@bp.post("/api/rest-suspensions")
def create_suspension():
    payload = json_payload()

    def mutate(data):
        order, report = lib.create(data, payload, day_status.today_iso())
        return jsonify({"suspension": order, **report}), 201

    return with_data(mutate, retro.status_scope)


@bp.post("/api/rest-suspensions/<order_id>/lift")
def lift_suspension(order_id):
    payload = json_payload()

    def mutate(data):
        return jsonify(lib.lift(data, order_id, payload, day_status.today_iso()))

    return with_data(mutate, ())

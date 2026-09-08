"""يومية تشغيل الضباط — الجدول الكامل وتكليف ضابط بخدمة معيّنة."""
from flask import Blueprint, jsonify, request

from ..constants import SHIFTS
from ..duty import summarise
from ..people import officers_on
from ..store import load_data, save_data
from ..utils import parse_date

bp = Blueprint("duty", __name__)


@bp.get("/api/duty/<day>")
def get_duty(day):
    if not parse_date(day):
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    return jsonify(summarise(load_data(), day))


@bp.put("/api/duty/<day>/<person_id>")
def set_duty(day, person_id):
    """تكليف ضابط بخدمة (أو أكتر) في يوم معيّن."""
    if not parse_date(day):
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    payload = request.get_json(silent=True) or {}
    data = load_data()
    # التكليف بيتقاس على قوة اليوم نفسه، فالضابط المؤرشف ينفع يتكلّف في يوم كان فيه بالقوة
    if not any(o.get("id") == person_id for o in officers_on(data, day)):
        return jsonify({"error": "الضابط لم يكن على القوة في هذا اليوم."}), 404

    known = {s["id"] for s in data["services"]}
    items = []
    for it in payload.get("items", []):
        sid = str(it.get("service_id", "")).strip()
        if sid not in known:
            return jsonify({"error": "خدمة غير معروفة."}), 400
        sh = str(it.get("shift", "صباحية")).strip()
        items.append({"service_id": sid, "shift": sh if sh in SHIFTS else "صباحية"})

    status = str(payload.get("status", "")).strip()
    if status and status not in ("انتداب", "غياب"):
        return jsonify({"error": "حالة غير صحيحة."}), 400

    entry = {"items": items, "taqseera": bool(payload.get("taqseera")),
             "note": str(payload.get("note", "")).strip()}
    if status:
        entry["status"] = status

    data["duties"].setdefault(day, {})[person_id] = entry
    if not items and not entry["taqseera"] and not status and not entry["note"]:
        data["duties"][day].pop(person_id, None)     # مفيش تكليف = صافي
    if not data["duties"][day]:
        data["duties"].pop(day, None)
    save_data(data)
    return jsonify(summarise(data, day))

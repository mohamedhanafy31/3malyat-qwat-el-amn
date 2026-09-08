"""نقاط الراحات والإجازات."""
from flask import Blueprint, jsonify, request

from ..leaves import build_leave, overlapping
from ..store import load_data, next_id, save_data

bp = Blueprint("leaves", __name__)


@bp.post("/api/leaves")
def add_leave():
    payload = request.get_json(silent=True) or {}
    data = load_data()
    leave_id = next_id(data["leaves"], "LV")

    leave, err = build_leave(payload, data, leave_id)
    if err:
        return jsonify({"error": err}), 400
    clash = overlapping(data, leave)
    if clash:
        return jsonify({"error": f"يوجد راحة متداخلة لنفس الشخص ({clash['start']} → {clash['end']})."}), 409

    data["leaves"].append(leave)
    data["leaves"].sort(key=lambda l: (l["start"], l.get("name", "")))
    save_data(data)
    return jsonify(leave), 201


@bp.patch("/api/leaves/<leave_id>")
def edit_leave(leave_id):
    payload = request.get_json(silent=True) or {}
    data = load_data()
    current = next((l for l in data["leaves"] if l.get("id") == leave_id), None)
    if not current:
        return jsonify({"error": "سجل الراحة غير موجود."}), 404

    merged = {**current, **payload}
    leave, err = build_leave(merged, data, leave_id)
    if err:
        return jsonify({"error": err}), 400
    clash = overlapping(data, leave, ignore_id=leave_id)
    if clash:
        return jsonify({"error": f"يوجد راحة متداخلة لنفس الشخص ({clash['start']} → {clash['end']})."}), 409

    data["leaves"] = [leave if l.get("id") == leave_id else l for l in data["leaves"]]
    data["leaves"].sort(key=lambda l: (l["start"], l.get("name", "")))
    save_data(data)
    return jsonify(leave)


@bp.delete("/api/leaves/<leave_id>")
def delete_leave(leave_id):
    data = load_data()
    before = len(data["leaves"])
    data["leaves"] = [l for l in data["leaves"] if l.get("id") != leave_id]
    if len(data["leaves"]) == before:
        return jsonify({"error": "سجل الراحة غير موجود."}), 404
    save_data(data)
    return jsonify({"ok": True})

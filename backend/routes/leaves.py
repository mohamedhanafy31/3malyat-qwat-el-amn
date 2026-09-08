"""نقاط الراحات والإجازات."""
from flask import Blueprint, jsonify

from ..leaves import build_leave, overlapping
from ..store import AbortRequest, next_id, with_data
from ..utils import json_payload

bp = Blueprint("leaves", __name__)


@bp.post("/api/leaves")
def add_leave():
    payload = json_payload()

    def mutate(data):
        leave_id = next_id(data["leaves"], "LV")
        leave, err = build_leave(payload, data, leave_id)
        if err:
            raise AbortRequest((jsonify({"error": err}), 400))
        clash = overlapping(data, leave)
        if clash:
            raise AbortRequest((jsonify({"error": f"يوجد راحة متداخلة لنفس الشخص ({clash['start']} → {clash['end']})."}), 409))

        data["leaves"].append(leave)
        data["leaves"].sort(key=lambda l: (l["start"], l.get("name", "")))
        return jsonify(leave), 201

    return with_data(mutate)


@bp.patch("/api/leaves/<leave_id>")
def edit_leave(leave_id):
    payload = json_payload()

    def mutate(data):
        current = next((l for l in data["leaves"] if l.get("id") == leave_id), None)
        if not current:
            raise AbortRequest((jsonify({"error": "سجل الراحة غير موجود."}), 404))

        merged = {**current, **payload}
        leave, err = build_leave(merged, data, leave_id)
        if err:
            raise AbortRequest((jsonify({"error": err}), 400))
        clash = overlapping(data, leave, ignore_id=leave_id)
        if clash:
            raise AbortRequest((jsonify({"error": f"يوجد راحة متداخلة لنفس الشخص ({clash['start']} → {clash['end']})."}), 409))

        data["leaves"] = [leave if l.get("id") == leave_id else l for l in data["leaves"]]
        data["leaves"].sort(key=lambda l: (l["start"], l.get("name", "")))
        return jsonify(leave)

    return with_data(mutate)


@bp.delete("/api/leaves/<leave_id>")
def delete_leave(leave_id):
    def mutate(data):
        before = len(data["leaves"])
        data["leaves"] = [l for l in data["leaves"] if l.get("id") != leave_id]
        if len(data["leaves"]) == before:
            raise AbortRequest((jsonify({"error": "سجل الراحة غير موجود."}), 404))
        return jsonify({"ok": True})

    return with_data(mutate)

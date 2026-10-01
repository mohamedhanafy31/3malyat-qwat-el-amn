"""المأموريات — إضافة/تعديل/حذف، ومتابعة حالتها."""
from flask import Blueprint, jsonify, request

from .. import changes
from .. import missions as missions_lib
from ..repo import Repos
from ..store import AbortRequest, load_data, with_data
from ..utils import json_payload

bp = Blueprint("missions", __name__)


@bp.get("/api/missions")
def list_missions():
    data = load_data(())
    status = request.args.get("status", "").strip()
    entries = missions_lib.missions(data)
    if status:
        entries = [m for m in entries if m["status"] == status]
    ordered = sorted(entries, key=lambda m: m.get("start") or "9999-99-99")
    return jsonify({
        "missions": [missions_lib.with_member_names(data, m) for m in ordered],
        "statuses": missions_lib.STATUSES,
    })


@bp.post("/api/missions")
def add_mission():
    payload = json_payload()
    name = str(payload.get("name", "")).strip()
    if not name:
        return jsonify({"error": "اسم المأمورية مطلوب."}), 400

    def mutate(data):
        entries = missions_lib.missions(data)
        mission = missions_lib.blank_mission(missions_lib.new_id(data), name)
        mission, err = missions_lib.apply_mission(data, mission, payload)
        if err:
            raise AbortRequest((jsonify({"error": err}), 400))
        entries.append(mission)
        changes.record(data, "mission", mission["id"], "create", after=dict(mission))
        return jsonify(missions_lib.with_member_names(data, mission)), 201

    return with_data(mutate, ())


@bp.patch("/api/missions/<mission_id>")
def edit_mission(mission_id):
    payload = json_payload()

    def mutate(data):
        entries = missions_lib.missions(data)
        mission = next((m for m in entries if m["id"] == mission_id), None)
        if not mission:
            raise AbortRequest((jsonify({"error": "المأمورية غير موجودة."}), 404))
        before = dict(mission)
        mission, err = missions_lib.apply_mission(data, mission, payload)
        if err:
            raise AbortRequest((jsonify({"error": err}), 400))
        changes.record(data, "mission", mission_id, "update", before=before, after=dict(mission))
        return jsonify(missions_lib.with_member_names(data, mission))

    return with_data(mutate, ())


@bp.delete("/api/missions/<mission_id>")
def delete_mission(mission_id):
    def mutate(data):
        repos = Repos(data)
        mission = repos.missions.find(mission_id)
        if not mission:
            raise AbortRequest((jsonify({"error": "المأمورية غير موجودة."}), 404))
        repos.missions.remove(mission_id)
        changes.record(data, "mission", mission_id, "delete", before=mission.as_dict())
        return jsonify({"ok": True})

    return with_data(mutate, ())

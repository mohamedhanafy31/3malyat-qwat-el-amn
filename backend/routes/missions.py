"""المأموريات — إضافة/تعديل/حذف، ومتابعة حالتها."""
from flask import Blueprint, jsonify, request, send_file
from io import BytesIO

from .. import changes
from .. import missions as missions_lib
from ..repo import Repos
from ..store import AbortRequest, load_data, with_data
from ..utils import json_payload
from ..utils import canonical_day
from ..register_export import build_register_docx, register_file_name
from datetime import date

bp = Blueprint("missions", __name__)


@bp.get("/api/missions/day/<day>")
def daily_missions(day):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "التاريخ غير صحيح."}), 400
    data = load_data({day})
    groups = missions_lib.daily_assignments(data, day)
    return jsonify({
        "date": day,
        "internal": groups["داخلية"],
        "external": groups["خارجية"],
        "counts": {
            "internal": len(groups["داخلية"]),
            "external": len(groups["خارجية"]),
            "total": len(groups["داخلية"]) + len(groups["خارجية"]),
        },
    })


@bp.get("/api/missions/export.docx")
def export_daily_missions():
    day = canonical_day(request.args.get("day", ""))
    if not day:
        return jsonify({"error": "التاريخ غير صحيح."}), 400
    data = load_data({day})
    groups = missions_lib.daily_assignments(data, day)
    records = groups["خارجية"] + groups["داخلية"]
    def people_text(row):
        assigned = [f"{p.get('role','') + '/ ' if p.get('role') else ''}{p.get('name') or 'غير مسجل'}" for p in row.get("officers", []) + row.get("personnel", [])]
        return " + ".join(assigned) or row.get("source_manning") or "لم يُعيَّن قائم بالخدمة"
    rows = [[r.get("kind", ""), r.get("section", ""), r.get("name", ""), r.get("shift", ""), people_text(r),
             " + ".join(f"{x.get('class','مجند')} ×{x.get('count')}" if x.get('count') else x.get('class','مجند') for x in r.get("conscripts", [])) or (str(r.get("conscript_count")) + " مجند" if r.get("conscript_count") else "—"),
             r.get("time", ""), r.get("party", ""), r.get("weapon", ""), r.get("note", "") or "—"] for r in records]
    d = date.fromisoformat(day)
    months = ("", "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر")
    content = build_register_docx("كشف المأموريات والتراحيل", [("التصنيف",.8),("القسم",1),("الخدمة",1.4),("الفترة",.8),("القائمون بها",2),("المجندون",1.2),("الانتظام",1),("الجهة",1),("التسليح",1),("ملاحظات",1.5)], rows, subtitle=f"تاريخ الكشف: {d.day} {months[d.month]} {d.year}")
    return send_file(BytesIO(content), as_attachment=True, download_name=register_file_name("كشف المأموريات والتراحيل", day), mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


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
        changes.record(data, "mission", mission["id"], "create", after=dict(mission),
                       text=f"إضافة مأمورية «{mission.get('name', '')}»")
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
        changes.record(data, "mission", mission_id, "update", before=before, after=dict(mission),
                       text=f"تعديل مأمورية «{mission.get('name', '')}»")
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
        changes.record(data, "mission", mission_id, "delete", before=mission.as_dict(),
                       text=f"حذف مأمورية «{mission.as_dict().get('name', '')}»")
        return jsonify({"ok": True})

    return with_data(mutate, ())

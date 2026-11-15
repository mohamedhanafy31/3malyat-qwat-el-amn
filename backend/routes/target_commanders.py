from flask import Blueprint, jsonify, request, send_file
from io import BytesIO
import json

from .. import day_status
from .. import target_commanders as lib
from ..store import AbortRequest, load_data, stale_revision, with_data
from ..utils import canonical_day, json_payload
from ..register_export import build_register_docx, register_file_name
from datetime import date

bp = Blueprint("target_commanders", __name__)


@bp.get("/api/target-commanders/<day>")
def get_target_commanders(day):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    return jsonify(lib.view(load_data(()), day))


@bp.get("/api/target-commanders/export.docx")
def export_target_commanders():
    day = canonical_day(request.args.get("day", ""))
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    payload = lib.view(load_data(()), day)
    try:
        selected = json.loads(request.args.get("assignments", "{}"))
        if not isinstance(selected, dict): selected = {}
    except (TypeError, ValueError):
        selected = {}
    officers = {p["id"]: p for p in payload["officers"]}
    chosen = {target["name"]: (selected.get(target["name"]) if target["name"] in selected else (target["commanders"][0]["id"] if target["commanders"] else None)) for target in payload["targets"]}
    counts = {person_id: list(chosen.values()).count(person_id) for person_id in chosen.values() if person_id}
    rows = []
    for target in payload["targets"]:
        current = target.get("commanders", [])
        new_id = chosen[target["name"]]
        new_person = officers.get(new_id, {})
        current_label = " + ".join(f"{p.get('role','') + '/ ' if p.get('role') else ''}{p.get('name','')}" for p in current) or "شاغر"
        new_label = (f"{new_person.get('role','') + '/ ' if new_person.get('role') else ''}{new_person.get('name','')}" if new_person else "شاغر")
        unchanged = [p.get("id") for p in current] == ([new_id] if new_id else [])
        state = "مكرر" if new_id and counts.get(new_id, 0) > 1 else ("ثابت" if unchanged else ("إخلاء" if not new_id else "تغيير"))
        rows.append([target.get("name", ""), current_label, new_label, state])
    d = date.fromisoformat(day)
    months = ("", "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر")
    content = build_register_docx("قادة الأهداف", [("الهدف",1.4),("القائد الحالي",2),("القائد الجديد",2),("حالة الصف",1)], rows,
                                  subtitle=f"تاريخ السريان: {d.day} {months[d.month]} {d.year}")
    return send_file(BytesIO(content), as_attachment=True, download_name=register_file_name("قادة الأهداف", day), mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


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

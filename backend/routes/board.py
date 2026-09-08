"""لوحة التشغيل المختصرة — عرض وتعديل خدمات اليوم بحرية كاملة."""
from flask import Blueprint, jsonify, request

from ..board import build_board, clean_requirements, get_day_services, remember_category, remember_tags
from ..constants import CATEGORY_OCCASIONAL, SHIFTS
from ..people import find_person
from ..store import load_data, next_id, save_data
from ..utils import parse_date

bp = Blueprint("board", __name__)


@bp.get("/api/board/<day>")
def get_board(day):
    if not parse_date(day):
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    return jsonify(build_board(load_data(), day))


@bp.post("/api/board/<day>/entries")
def add_board_entry(day):
    if not parse_date(day):
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    payload = request.get_json(silent=True) or {}
    service = str(payload.get("service", "")).strip()
    if not service:
        return jsonify({"error": "اسم الخدمة مطلوب."}), 400
    category = str(payload.get("category", "")).strip() or CATEGORY_OCCASIONAL
    shift = str(payload.get("shift", "")).strip()
    if shift and shift not in SHIFTS:
        return jsonify({"error": "الفترة غير صحيحة."}), 400

    data = load_data()
    entries = get_day_services(data, day)

    officer_id = str(payload.get("officer_id", "")).strip() or None
    officer_name = str(payload.get("officer_name", "")).strip()
    if officer_id:
        p, _, _ = find_person(data, officer_id)
        if not p:
            return jsonify({"error": "الضابط غير موجود."}), 404
        officer_name = p["name"]

    tags = [str(t).strip() for t in payload.get("tags", []) if str(t).strip()]
    entry = {
        "id": next_id(entries, "DS", width=4), "category": category, "service": service,
        "shift": shift, "officer_id": officer_id, "officer_name": officer_name,
        "requirements": clean_requirements(payload.get("requirements")),
        "tags": tags, "note": str(payload.get("note", "")).strip(),
    }
    entries.append(entry)
    remember_category(data, category)
    remember_tags(data, tags)
    save_data(data)
    return jsonify(entry), 201


@bp.patch("/api/board/<day>/entries/<entry_id>")
def edit_board_entry(day, entry_id):
    if not parse_date(day):
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    payload = request.get_json(silent=True) or {}
    data = load_data()
    entries = get_day_services(data, day)
    entry = next((e for e in entries if e["id"] == entry_id), None)
    if not entry:
        return jsonify({"error": "السجل غير موجود."}), 404

    if "service" in payload:
        service = str(payload["service"]).strip()
        if not service:
            return jsonify({"error": "اسم الخدمة مطلوب."}), 400
        entry["service"] = service
    if "category" in payload:
        entry["category"] = str(payload["category"]).strip() or CATEGORY_OCCASIONAL
        remember_category(data, entry["category"])
    if "shift" in payload:
        shift = str(payload["shift"]).strip()
        if shift and shift not in SHIFTS:
            return jsonify({"error": "الفترة غير صحيحة."}), 400
        entry["shift"] = shift
    if "officer_id" in payload:
        officer_id = str(payload["officer_id"]).strip() or None
        if officer_id:
            p, _, _ = find_person(data, officer_id)
            if not p:
                return jsonify({"error": "الضابط غير موجود."}), 404
            entry["officer_id"], entry["officer_name"] = officer_id, p["name"]
        else:
            entry["officer_id"] = None
            entry["officer_name"] = str(payload.get("officer_name", entry.get("officer_name", ""))).strip()
    elif "officer_name" in payload and not entry.get("officer_id"):
        entry["officer_name"] = str(payload["officer_name"]).strip()
    if "requirements" in payload:
        entry["requirements"] = clean_requirements(payload["requirements"])
    if "tags" in payload:
        entry["tags"] = [str(t).strip() for t in payload["tags"] if str(t).strip()]
        remember_tags(data, entry["tags"])
    if "note" in payload:
        entry["note"] = str(payload["note"]).strip()

    save_data(data)
    return jsonify(entry)


@bp.delete("/api/board/<day>/entries/<entry_id>")
def delete_board_entry(day, entry_id):
    if not parse_date(day):
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    data = load_data()
    entries = get_day_services(data, day)
    before = len(entries)
    data["day_services"][day] = [e for e in entries if e["id"] != entry_id]
    if len(data["day_services"][day]) == before:
        return jsonify({"error": "السجل غير موجود."}), 404
    save_data(data)
    return jsonify({"ok": True})

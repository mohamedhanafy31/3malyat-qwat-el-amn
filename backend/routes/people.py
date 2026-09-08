"""القوة — إضافة/تعديل/إخراج/استعادة/حذف الضباط والأفراد."""
from datetime import date

from flask import Blueprint, jsonify, request

from ..constants import EDITABLE, PERSONNEL_FAMILIES
from ..people import find_person, sort_active, valid_rest
from ..store import AbortRequest, with_data
from ..utils import category_for, parse_date

bp = Blueprint("people", __name__)


@bp.post("/api/person")
def add_person():
    payload = request.get_json(silent=True) or {}
    required = ["name", "code", "phone", "join_date", "type"]
    if any(not str(payload.get(k, "")).strip() for k in required):
        return jsonify({"error": "برجاء إدخال كل البيانات المطلوبة."}), 400

    person_type = payload["type"]
    if person_type == "personnel":
        # Grades carry a degree ("أمين شرطة ممتاز أول"), so match on the family.
        family = str(payload.get("role", "")).strip().split(" ")[0]
        if family not in PERSONNEL_FAMILIES:
            return jsonify({"error": "نوع الفرد غير صحيح."}), 400
    if person_type == "officer":
        payload["role"] = str(payload.get("role", "")).strip() or "ضابط"

    if not parse_date(payload["join_date"]):
        return jsonify({"error": "تاريخ الانضمام غير صحيح."}), 400

    errors = []
    valid_rest(payload, errors)
    if errors:
        return jsonify({"error": errors[0]}), 400

    category = category_for(person_type)
    code = str(payload["code"]).strip()

    def mutate(data):
        # Code must be unique among active members.
        if any(str(p.get("code")) == code for p in data[category]["active"]):
            raise AbortRequest((jsonify({"error": "رقم الأقدمية مستخدم بالفعل على القوة."}), 409))

        person = {
            "id": f"{date.today().isoformat()}-{code}",
            "name": str(payload["name"]).strip(),
            "role": str(payload.get("role", "")).strip(),
            "code": code,
            "phone": str(payload["phone"]).strip(),
            "join_date": str(payload["join_date"]).strip(),
            "post": str(payload.get("post", "")).strip(),
            "status": "active"
        }
        if category == "officers":
            person["rest_system"] = str(payload.get("rest_system", "—")).strip() or "—"
            person["rest_day"] = str(payload.get("rest_day", "")).strip()
        else:
            person["address"] = str(payload.get("address", "")).strip()

        data[category]["active"].append(person)
        sort_active(data, category)
        return jsonify(person), 201

    return with_data(mutate)


@bp.patch("/api/person/<person_id>")
def edit_person(person_id):
    payload = request.get_json(silent=True) or {}

    def mutate(data):
        person, category, bucket = find_person(data, person_id)
        if not person:
            raise AbortRequest((jsonify({"error": "الشخص غير موجود."}), 404))

        if "name" in payload and not str(payload["name"]).strip():
            raise AbortRequest((jsonify({"error": "الاسم مطلوب."}), 400))
        if "code" in payload:
            code = str(payload["code"]).strip()
            if not code:
                raise AbortRequest((jsonify({"error": "رقم الأقدمية مطلوب."}), 400))
            clash = any(str(p.get("code")) == code and p.get("id") != person_id
                        for p in data[category]["active"])
            if bucket == "active" and clash:
                raise AbortRequest((jsonify({"error": "رقم الأقدمية مستخدم بالفعل على القوة."}), 409))
        if "join_date" in payload and not parse_date(payload["join_date"]):
            raise AbortRequest((jsonify({"error": "تاريخ الانضمام غير صحيح."}), 400))
        if "role" in payload and category == "personnel":
            family = str(payload["role"]).strip().split(" ")[0]
            if family not in PERSONNEL_FAMILIES:
                raise AbortRequest((jsonify({"error": "نوع الفرد غير صحيح."}), 400))

        errors = []
        valid_rest(payload, errors)
        if errors:
            raise AbortRequest((jsonify({"error": errors[0]}), 400))

        for key in EDITABLE:
            if key in payload:
                person[key] = str(payload[key]).strip()

        if bucket == "archive" and "leave_date" in payload:
            leave = parse_date(payload["leave_date"])
            if not leave:
                raise AbortRequest((jsonify({"error": "تاريخ الخروج غير صحيح."}), 400))
            if payload["leave_date"] < person.get("join_date", ""):
                raise AbortRequest((jsonify({"error": "تاريخ الخروج لا يمكن أن يسبق تاريخ الانضمام."}), 400))
            person["leave_date"] = str(payload["leave_date"]).strip()
        if bucket == "archive" and "leave_reason" in payload:
            person["leave_reason"] = str(payload["leave_reason"]).strip()

        # keep any recorded rest periods showing the current name
        for lv in data["leaves"]:
            if lv.get("person_id") == person_id:
                lv["name"] = person.get("name", lv.get("name", ""))

        return jsonify(person)

    return with_data(mutate)


@bp.post("/api/person/<person_id>/remove")
def remove_person(person_id):
    payload = request.get_json(silent=True) or {}
    leave_date = str(payload.get("leave_date", "")).strip() or date.today().isoformat()
    reason = str(payload.get("reason", "")).strip()

    def mutate(data):
        found, category, bucket = find_person(data, person_id)
        if not found or bucket != "active":
            raise AbortRequest((jsonify({"error": "الشخص غير موجود على القوة."}), 404))

        if leave_date < found.get("join_date", ""):
            raise AbortRequest((jsonify({"error": "تاريخ الخروج لا يمكن أن يسبق تاريخ الانضمام."}), 400))

        found["leave_date"] = leave_date
        found["leave_reason"] = reason
        found["status"] = "archived"

        data[category]["active"] = [p for p in data[category]["active"] if p.get("id") != person_id]
        data[category]["archive"].append(found)
        data[category]["archive"].sort(key=lambda p: (p.get("leave_date", ""), p.get("name", "")), reverse=True)
        return jsonify(found)

    return with_data(mutate)


@bp.post("/api/person/<person_id>/restore")
def restore_person(person_id):
    def mutate(data):
        found, category, bucket = find_person(data, person_id)
        if not found or bucket != "archive":
            raise AbortRequest((jsonify({"error": "السجل غير موجود في الأرشيف."}), 404))

        code = str(found.get("code", ""))
        if any(str(p.get("code")) == code for p in data[category]["active"]):
            raise AbortRequest((jsonify({"error": "يوجد شخص على القوة بنفس رقم الأقدمية."}), 409))

        # Keep the historical record intact and create a new active period.
        restored = dict(found)
        restored.update({
            "id": f"{date.today().isoformat()}-{code}-restored-{len(data[category]['active'])}",
            "code": code,
            "join_date": str(date.today().isoformat()),
            "status": "active",
            "previous_archive_id": found.get("id"),
        })
        restored.pop("leave_date", None)
        restored.pop("leave_reason", None)
        data[category]["active"].append(restored)
        sort_active(data, category)
        return jsonify(restored), 201

    return with_data(mutate)


@bp.delete("/api/person/<person_id>")
def delete_archive_record(person_id):
    # Permanent delete is intentionally limited to archive records.
    def mutate(data):
        for cat in ["officers", "personnel"]:
            before = len(data[cat]["archive"])
            data[cat]["archive"] = [p for p in data[cat]["archive"] if p.get("id") != person_id]
            if len(data[cat]["archive"]) != before:
                data["leaves"] = [l for l in data["leaves"] if l.get("person_id") != person_id]
                return jsonify({"ok": True})
        raise AbortRequest((jsonify({"error": "السجل غير موجود."}), 404))

    return with_data(mutate)

"""القوة — إضافة/تعديل/إخراج/استعادة/حذف الضباط والأفراد."""
from datetime import date

from flask import Blueprint, jsonify

from ..constants import COMMAND_ROLES, EDITABLE, OFFICER_SECTIONS, PERSONNEL_FAMILIES
from ..people import HISTORY_FIELDS, find_person, record_change, sort_active, valid_rest
from ..store import AbortRequest, with_data
from ..utils import category_for, json_payload, parse_date

bp = Blueprint("people", __name__)


@bp.patch("/api/command")
def set_command():
    """تحديد ضابط لمنصب قيادي (مدير/وكيل الإدارة). المناصب ثابتة والضابط
    اللي شايلها هو اللي بيتغيّر مع حركة الضباط. ابعت null لتفريغ المنصب."""
    payload = json_payload()

    def mutate(data):
        for role, officer_id in payload.items():
            if role not in COMMAND_ROLES:
                raise AbortRequest((jsonify({"error": f"منصب غير معروف: {role}"}), 400))
            officer_id = str(officer_id or "").strip() or None
            if officer_id:
                person, category, bucket = find_person(data, officer_id)
                if not person or category != "officers":
                    raise AbortRequest((jsonify({"error": "الضابط غير موجود."}), 404))
                if bucket != "active":
                    raise AbortRequest((jsonify({"error": "الضابط مش على القوة."}), 400))
                clash = next((r for r, oid in data["command"].items()
                              if oid == officer_id and r != role), None)
                if clash:
                    raise AbortRequest((jsonify({
                        "error": f"الضابط ده شايل «{clash}» بالفعل."}), 409))
            data["command"][role] = officer_id
        sort_active(data, "officers")   # قيادة الإدارة أعلى اتنين في الترتيب
        return jsonify(data["command"])

    return with_data(mutate)


@bp.patch("/api/medical-officers")
def set_medical_officers():
    """تحديد قايمة ضباط العيادة الطبية — تشغيلهم "طبية" بيتحسب تلقائيًا
    كل يوم (موجود أو راحة) من غير تكليف يدوي. ابعت القايمة كاملة كل مرة."""
    payload = json_payload()
    ids = payload.get("officer_ids")
    if not isinstance(ids, list):
        return jsonify({"error": "officer_ids لازم تكون قايمة."}), 400

    def mutate(data):
        seen, clean = set(), []
        for officer_id in ids:
            officer_id = str(officer_id or "").strip()
            if not officer_id or officer_id in seen:
                continue
            person, category, bucket = find_person(data, officer_id)
            if not person or category != "officers":
                raise AbortRequest((jsonify({"error": "الضابط غير موجود."}), 404))
            if bucket != "active":
                raise AbortRequest((jsonify({"error": "الضابط مش على القوة."}), 400))
            seen.add(officer_id)
            clean.append(officer_id)
        data["medical_officers"] = clean
        return jsonify(data["medical_officers"])

    return with_data(mutate)


@bp.post("/api/person")
def add_person():
    payload = json_payload()
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
    payload = json_payload()

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
        if "section" in payload and category == "officers":
            if str(payload["section"]).strip() not in OFFICER_SECTIONS:
                raise AbortRequest((jsonify({"error": "قسم اليومية غير صحيح."}), 400))

        errors = []
        valid_rest(payload, errors)
        if errors:
            raise AbortRequest((jsonify({"error": errors[0]}), 400))

        # الرتبة/المنصب/القسم/جهة التشغيل بتتسجّل بتاريخ سريان بدل ما
        # تتكتب فوق الماضي — عشان إعادة توليد يوم قديم تطبع بياناته هو
        historic = {}
        for key in HISTORY_FIELDS:
            if key in payload:
                historic[key] = (bool(payload[key]) if key == "search_attached"
                                 else str(payload[key]).strip())
        if historic and category == "officers":
            effective_from = str(payload.get("effective_from", "")).strip() \
                or date.today().isoformat()
            if not parse_date(effective_from):
                raise AbortRequest((jsonify({"error": "تاريخ السريان غير صحيح."}), 400))
            record_change(person, effective_from, historic)

        for key in EDITABLE:
            if key in payload and not (historic and key in historic and category == "officers"):
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

        if bucket == "active":
            sort_active(data, category)   # الرتبة أو الاسم ممكن يتغيّر
        return jsonify(person)

    return with_data(mutate)


@bp.post("/api/person/<person_id>/remove")
def remove_person(person_id):
    payload = json_payload()
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

        # لو الضابط شايل منصب قيادي أو من ضباط العيادة، الإخراج من القوة
        # يفضّي المنصب — ميفضلش متعيّن لحد مش على القوة أصلًا
        for role, oid in data.get("command", {}).items():
            if oid == person_id:
                data["command"][role] = None
        data["medical_officers"] = [oid for oid in data.get("medical_officers", [])
                                     if oid != person_id]
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

        old_id = found.get("id")
        for lv in data.get("leaves", []):
            if lv.get("person_id") == old_id:
                lv["person_id"] = restored["id"]
                lv["name"] = restored.get("name", lv.get("name", ""))

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
                for day in list(data.get("day_officers", {})):
                    data["day_officers"][day].pop(person_id, None)
                    if not data["day_officers"][day]:
                        data["day_officers"].pop(day)
                return jsonify({"ok": True})
        raise AbortRequest((jsonify({"error": "السجل غير موجود."}), 404))

    return with_data(mutate)


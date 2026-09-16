"""القوة — إضافة/تعديل/إخراج/استعادة/حذف الضباط والأفراد."""
from datetime import date

from flask import Blueprint, jsonify

from ..constants import (
    COMMAND_ROLES, EDITABLE, OFFICER_ROLES, OFFICER_SECTIONS, PERSONNEL_FAMILIES,
)
from ..references import cascade_delete
from ..repo import Repos
from ..people import HISTORY_FIELDS, record_change, valid_rest
from ..store import AbortRequest, with_data
from ..utils import (
    MAX_LEN, canonical_day, category_for, check_lengths, json_payload, valid_phone,
)

bp = Blueprint("people", __name__)


def _require_active_officer(repos, officer_id):
    """ضابط موجود وعلى القوة — بيرمي 404/400 من غير ما يكمّل.

    المنصب القيادي وضباط العيادة الاتنين محتاجين نفس الشرطين بنفس
    الرسايل، وكانوا مكرّرين حرفيًا في الدالتين.
    """
    raw, category, bucket = repos.people.locate(officer_id)
    if raw is None or category != "officers":
        raise AbortRequest((jsonify({"error": "الضابط غير موجود."}), 404))
    if bucket != "active":
        raise AbortRequest((jsonify({"error": "الضابط مش على القوة."}), 400))
    return raw


@bp.patch("/api/command")
def set_command():
    """تحديد ضابط لمنصب قيادي (مدير/وكيل الإدارة). المناصب ثابتة والضابط
    اللي شايلها هو اللي بيتغيّر مع حركة الضباط. ابعت null لتفريغ المنصب."""
    payload = json_payload()

    def mutate(data):
        repos = Repos(data)
        for role, officer_id in payload.items():
            if role not in COMMAND_ROLES:
                raise AbortRequest((jsonify({"error": f"منصب غير معروف: {role}"}), 400))
            officer_id = str(officer_id or "").strip() or None
            if officer_id:
                _require_active_officer(repos, officer_id)
                clash = repos.config.role_of(officer_id)
                if clash and clash != role:
                    raise AbortRequest((jsonify({
                        "error": f"الضابط ده شايل «{clash}» بالفعل."}), 409))
            repos.config.assign_command(role, officer_id)
        repos.people.sort("officers")   # قيادة الإدارة أعلى اتنين في الترتيب
        return jsonify(repos.config.command())

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
        repos = Repos(data)
        seen, clean = set(), []
        for officer_id in ids:
            officer_id = str(officer_id or "").strip()
            if not officer_id or officer_id in seen:
                continue
            _require_active_officer(repos, officer_id)
            seen.add(officer_id)
            clean.append(officer_id)
        repos.config.set_medical(clean)
        return jsonify(repos.config.medical())

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
        if payload["role"] not in OFFICER_ROLES:
            return jsonify({"error": "رتبة الضابط غير صحيحة."}), 400

    join_date = canonical_day(payload["join_date"])
    if not join_date:
        return jsonify({"error": "تاريخ الانضمام غير صحيح."}), 400

    bad_length = check_lengths(payload, ("name", "code", "phone", "post", "address"))
    if bad_length:
        return jsonify({"error": bad_length}), 400
    if not valid_phone(payload["phone"]):
        return jsonify({"error": "رقم التليفون غير صحيح."}), 400

    errors = []
    valid_rest(payload, errors)
    if errors:
        return jsonify({"error": errors[0]}), 400

    category = category_for(person_type)
    code = str(payload["code"]).strip()

    def mutate(data):
        # Code must be unique among active members.
        repos = Repos(data)
        if repos.people.code_taken(category, code):
            raise AbortRequest((jsonify({"error": "رقم الأقدمية مستخدم بالفعل على القوة."}), 409))

        person = {
            "id": repos.people.new_id(category),
            "name": str(payload["name"]).strip(),
            "role": str(payload.get("role", "")).strip(),
            "code": code,
            "phone": str(payload["phone"]).strip(),
            # التاريخ بيتخزّن في صورته المعيارية دايمًا — كل المقارنات في
            # السيستم (officers_on مثلًا) نصية، فصورة تانية زي «20260101»
            # كانت بتخلي المقارنة تطلع بالعكس والضابط يختفي من اليوميات
            "join_date": join_date,
            "post": str(payload.get("post", "")).strip(),
            "status": "active"
        }
        if category == "officers":
            person["rest_system"] = str(payload.get("rest_system", "—")).strip() or "—"
            person["rest_day"] = str(payload.get("rest_day", "")).strip()
        else:
            person["address"] = str(payload.get("address", "")).strip()

        repos.people.add_raw(category, person)
        return jsonify(person), 201

    return with_data(mutate)


@bp.patch("/api/person/<person_id>")
def edit_person(person_id):
    payload = json_payload()

    def mutate(data):
        person, category, bucket = Repos(data).people.locate(person_id)
        if not person:
            raise AbortRequest((jsonify({"error": "الشخص غير موجود."}), 404))

        if "name" in payload and not str(payload["name"]).strip():
            raise AbortRequest((jsonify({"error": "الاسم مطلوب."}), 400))
        if "code" in payload:
            code = str(payload["code"]).strip()
            if not code:
                raise AbortRequest((jsonify({"error": "رقم الأقدمية مطلوب."}), 400))
            clash = Repos(data).people.code_taken(category, code, ignore_id=person_id)
            if bucket == "active" and clash:
                raise AbortRequest((jsonify({"error": "رقم الأقدمية مستخدم بالفعل على القوة."}), 409))
        if "join_date" in payload:
            join_date = canonical_day(payload["join_date"])
            if not join_date:
                raise AbortRequest((jsonify({"error": "تاريخ الانضمام غير صحيح."}), 400))
            payload["join_date"] = join_date      # يتخزّن معياري دايمًا
        if "role" in payload and category == "personnel":
            family = str(payload["role"]).strip().split(" ")[0]
            if family not in PERSONNEL_FAMILIES:
                raise AbortRequest((jsonify({"error": "نوع الفرد غير صحيح."}), 400))
        if "role" in payload and category == "officers":
            if str(payload["role"]).strip() not in OFFICER_ROLES:
                raise AbortRequest((jsonify({"error": "رتبة الضابط غير صحيحة."}), 400))
        if "section" in payload and category == "officers":
            if str(payload["section"]).strip() not in OFFICER_SECTIONS:
                raise AbortRequest((jsonify({"error": "قسم اليومية غير صحيح."}), 400))

        bad_length = check_lengths(payload, ("name", "code", "phone", "post",
                                             "address", "leave_reason"))
        if bad_length:
            raise AbortRequest((jsonify({"error": bad_length}), 400))
        if "phone" in payload and not valid_phone(payload["phone"]):
            raise AbortRequest((jsonify({"error": "رقم التليفون غير صحيح."}), 400))

        errors = []
        valid_rest(payload, errors, current=person)
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
            effective_from = canonical_day(
                str(payload.get("effective_from", "")).strip() or date.today().isoformat())
            if not effective_from:
                raise AbortRequest((jsonify({"error": "تاريخ السريان غير صحيح."}), 400))
            record_change(person, effective_from, historic)

        for key in EDITABLE:
            if key in payload and not (historic and key in historic and category == "officers"):
                person[key] = str(payload[key]).strip()

        if bucket == "archive" and "leave_date" in payload:
            leave_date = canonical_day(payload["leave_date"])
            if not leave_date:
                raise AbortRequest((jsonify({"error": "تاريخ الخروج غير صحيح."}), 400))
            if leave_date < person.get("join_date", ""):
                raise AbortRequest((jsonify({"error": "تاريخ الخروج لا يمكن أن يسبق تاريخ الانضمام."}), 400))
            person["leave_date"] = leave_date
        if bucket == "archive" and "leave_reason" in payload:
            person["leave_reason"] = str(payload["leave_reason"]).strip()

        # مافيش مزامنة لأسماء الراحات هنا خلاص: الاسم مابقاش متخزّن على سجل
        # الراحة، بيتحلّ من `person_id` وقت القراءة (`LeaveRepo.named`).
        # الكتلة اللي كانت بتمشي على كل راحات الشخص بعد كل تعديل اتشالت مع
        # الحقل المكرّر نفسه.
        if bucket == "active":
            Repos(data).people.sort(category)   # الرتبة أو الاسم ممكن يتغيّر
        return jsonify(person)

    return with_data(mutate)


@bp.post("/api/person/<person_id>/remove")
def remove_person(person_id):
    payload = json_payload()
    leave_date = canonical_day(
        str(payload.get("leave_date", "")).strip() or date.today().isoformat())
    reason = str(payload.get("reason", "")).strip()
    if not leave_date:
        return jsonify({"error": "تاريخ الخروج غير صحيح."}), 400
    if len(reason) > MAX_LEN["reason"]:
        return jsonify({"error": f"سبب الخروج أطول من الحد المسموح ({MAX_LEN['reason']} حرف)."}), 400

    def mutate(data):
        found, category, bucket = Repos(data).people.locate(person_id)
        if not found or bucket != "active":
            raise AbortRequest((jsonify({"error": "الشخص غير موجود على القوة."}), 404))

        if leave_date < found.get("join_date", ""):
            raise AbortRequest((jsonify({"error": "تاريخ الخروج لا يمكن أن يسبق تاريخ الانضمام."}), 400))

        found["leave_date"] = leave_date
        found["leave_reason"] = reason
        found["status"] = "archived"

        Repos(data).people.move(person_id, "archive")

        # لو الضابط شايل منصب قيادي أو من ضباط العيادة، الإخراج من القوة
        # يفضّي المنصب — ميفضلش متعيّن لحد مش على القوة أصلًا
        config = Repos(data).config
        config.clear_command(person_id)
        config.drop_medical(person_id)
        return jsonify(found)

    return with_data(mutate)


@bp.post("/api/person/<person_id>/restore")
def restore_person(person_id):
    def mutate(data):
        found, category, bucket = Repos(data).people.locate(person_id)
        if not found or bucket != "archive":
            raise AbortRequest((jsonify({"error": "السجل غير موجود في الأرشيف."}), 404))

        repos = Repos(data)
        code = str(found.get("code", ""))
        if repos.people.code_taken(category, code):
            raise AbortRequest((jsonify({"error": "يوجد شخص على القوة بنفس رقم الأقدمية."}), 409))

        # Keep the historical record intact and create a new active period.
        restored = dict(found)
        restored.update({
            "id": repos.people.new_id(category),
            "code": code,
            "join_date": date.today().isoformat(),
            "status": "active",
            "previous_archive_id": found.get("id"),
        })
        restored.pop("leave_date", None)
        restored.pop("leave_reason", None)
        repos.people.add_raw(category, restored)

        # الراحات القديمة **بتفضل على سجل الأرشيف** — هي جزء من فترة الخدمة
        # اللي خلصت. نقلها للسجل الجديد (اللي تاريخ انضمامه النهاردة) كان
        # بيخلّف راحات تاريخها قبل الانضمام، وبيفضّي تاريخ سجل الأرشيف
        # بالكامل. الصفحة أصلًا بتعرض أسماء المتأرشفين اللي ليهم راحات،
        # فالسجل القديم بيفضل ظاهر وكامل.
        return jsonify(restored), 201

    return with_data(mutate)


@bp.delete("/api/person/<person_id>")
def delete_archive_record(person_id):
    # Permanent delete is intentionally limited to archive records.
    def mutate(data):
        repos = Repos(data)
        raw, category, bucket = repos.people.locate(person_id)
        if raw is None or bucket != "archive":
            raise AbortRequest((jsonify({"error": "السجل غير موجود."}), 404))

        repos.people.remove(person_id)
        cascade_delete(repos, person_id, category)
        return jsonify({"ok": True})

    return with_data(mutate)


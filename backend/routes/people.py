"""القوة — إضافة/تعديل/إخراج/استعادة/حذف الضباط والأفراد."""
from datetime import date

from flask import Blueprint, jsonify

from ..constants import (
    COMMAND_ROLES, EDITABLE, GROUP_ROLES, OFFICER_ROLES, OFFICER_SECTIONS,
    PERSONNEL_FAMILIES,
)
from .. import changes, day_status, retro
from ..dated import command_on, record_command_change
from ..references import cascade_delete
from ..repo import Repos
from ..people import (
    HISTORY_FIELDS, PERSONNEL_HISTORY_FIELDS, cleanup_outside_window, record_change,
    effective, service_window_conflicts, valid_rest,
)
from ..store import AbortRequest, with_data
from ..utils import (
    MAX_LEN, canonical_day, category_for, check_lengths, json_payload, valid_phone,
)

bp = Blueprint("people", __name__)


def _require_active_officer(repos, officer_id):
    """ضابط موجود وعلى القوة — بيرمي 404/400 من غير ما يكمّل."""
    raw, category, bucket = repos.people.locate(officer_id)
    if raw is None or category != "officers":
        raise AbortRequest((jsonify({"error": "الضابط غير موجود."}), 404))
    if bucket != "active":
        raise AbortRequest((jsonify({"error": "الضابط ليس على القوة."}), 400))
    return raw


@bp.patch("/api/command")
def set_command():
    """تحديد ضابط لمنصب قيادي (مدير/وكيل الإدارة). المناصب ثابتة والضابط
    اللي شايلها هو اللي بيتغيّر مع حركة الضباط. ابعت null لتفريغ المنصب."""
    payload = json_payload()

    def mutate(data):
        repos = Repos(data)
        changed = {}
        current = command_on(data, day_status.today_iso())
        for role, officer_id in payload.items():
            if role not in COMMAND_ROLES:
                raise AbortRequest((jsonify({"error": f"منصب غير معروف: {role}"}), 400))
            officer_id = str(officer_id or "").strip() or None
            if officer_id:
                _require_active_officer(repos, officer_id)
                clash = next((r for r, oid in current.items() if oid == officer_id), None)
                if clash and clash != role:
                    raise AbortRequest((jsonify({
                        "error": f"يتولى هذا الضابط «{clash}» بالفعل."}), 409))
            current[role] = officer_id
            changed[role] = officer_id
        if changed:
            record_command_change(data, day_status.today_iso(), command=changed)
        repos.people.sort("officers")   # قيادة الإدارة أعلى اتنين في الترتيب
        return jsonify(repos.config.command())

    return with_data(mutate)


@bp.patch("/api/command-groups")
def set_command_groups():
    """أعضاء منصب جماعي في قيادة الإدارة (طبي/بحث) — عكس `/api/command`،
    أكتر من ضابط ممكن يشيل نفس المنصب، فالجسم `{role: [officer_id, ...]}`
    قايمة كاملة بتستبدل الأعضاء الحاليين، مش تعيين مفرد. ابعت قايمة فاضية
    لتفريغ المنصب بالكامل."""
    payload = json_payload()

    def mutate(data):
        repos = Repos(data)
        changed = {}
        for role, officer_ids in payload.items():
            if role not in GROUP_ROLES:
                raise AbortRequest((jsonify({"error": f"منصب غير معروف: {role}"}), 400))
            if not isinstance(officer_ids, list):
                raise AbortRequest((jsonify({"error": "يجب إرسال قائمة معرّفات."}), 400))
            clean_ids = []
            for raw_id in officer_ids:
                officer_id = str(raw_id or "").strip()
                if not officer_id or officer_id in clean_ids:
                    continue
                _require_active_officer(repos, officer_id)
                clean_ids.append(officer_id)
            changed[role] = clean_ids
        if changed:
            record_command_change(data, day_status.today_iso(), groups=changed)
        return jsonify(repos.config.groups())

    return with_data(mutate)


@bp.post("/api/person")
def add_person():
    payload = json_payload()
    required = ["name", "code", "phone", "join_date", "type"]
    if any(not str(payload.get(k, "")).strip() for k in required):
        return jsonify({"error": "يرجى إدخال جميع البيانات المطلوبة."}), 400

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
        return jsonify({"error": "رقم الهاتف غير صحيح."}), 400

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
            person["weapon_custody"] = str(payload.get("weapon_custody", "")).strip()
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

            # تأجيل تاريخ الانضمام ممكن يسيب راحات/فرق/تكليفات مسجّلة
            # قبل التاريخ الجديد — بتفضل معلّقة لشخص السيستم بيقول إنه
            # لسه مانضمش وقتها. بترفض بدل ما تعدّل وتسيبها معلّقة بصمت.
            current_leave = person.get("leave_date", "") if bucket == "archive" else ""
            conflicts = service_window_conflicts(data, person_id, category,
                                                 join_date, current_leave)
            if conflicts:
                raise AbortRequest((jsonify({
                    "error": "سيترك تعديل تاريخ الانضمام هذا بيانات مسجّلة قبله معلّقة.",
                    "conflicts": conflicts}), 400))
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
                                             "address", "leave_reason", "weapon_custody"))
        if bad_length:
            raise AbortRequest((jsonify({"error": bad_length}), 400))
        if "phone" in payload and not valid_phone(payload["phone"]):
            raise AbortRequest((jsonify({"error": "رقم الهاتف غير صحيح."}), 400))

        errors = []
        effective_from = canonical_day(
            str(payload.get("effective_from", "")).strip() or day_status.today_iso())
        current_for_rest = person
        if category == "officers" and effective_from:
            current_for_rest = {**person, **effective(person, effective_from)}
        valid_rest(payload, errors, current=current_for_rest)
        if errors:
            raise AbortRequest((jsonify({"error": errors[0]}), 400))

        # الرتبة/المنصب/القسم/جهة التشغيل بتتسجّل بتاريخ سريان بدل ما
        # تتكتب فوق الماضي — عشان إعادة توليد يوم قديم تطبع بياناته هو
        historic = {}
        history_fields = HISTORY_FIELDS if category == "officers" else PERSONNEL_HISTORY_FIELDS
        for key in history_fields:
            if key in payload:
                historic[key] = (bool(payload[key]) if key == "search_attached"
                                 else str(payload[key]).strip())
        if historic:
            if not effective_from:
                raise AbortRequest((jsonify({"error": "تاريخ السريان غير صحيح."}), 400))

            # سريان بتاريخ فات معناه أيام مقفولة بالفعل هتتطبع ببيانات
            # مختلفة من دلوقتي (`people.effective`) — رتبة/منصب/قسم
            # جديد على يوم كان معتمد فعلًا. مسموح، بس محتاج سبب.
            closed = retro.closed_days_in(data, effective_from, day_status.today_iso())
            reason = retro.require_reason(closed)

            before = {k: person.get(k) for k in historic}
            record_change(person, effective_from, historic, history_fields)
            if closed:
                retro.log_retro(data, "person", person_id, closed, reason,
                               before=before, after=dict(historic),
                               text=f"تعديل بأثر رجعي على بيانات {person.get('name', '')} "
                                    f"سارٍ من {effective_from} — يوم مغلق أو عدة أيام مغلقة: "
                                    f"{'، '.join(closed)}")

        for key in EDITABLE:
            if key in payload and not (historic and key in historic):
                person[key] = str(payload[key]).strip()

        if bucket == "archive" and "leave_date" in payload:
            leave_date = canonical_day(payload["leave_date"])
            if not leave_date:
                raise AbortRequest((jsonify({"error": "تاريخ الخروج غير صحيح."}), 400))
            if leave_date < person.get("join_date", ""):
                raise AbortRequest((jsonify({"error": "تاريخ الخروج لا يمكن أن يسبق تاريخ الانضمام."}), 400))

            # تقديم تاريخ الخروج ممكن يسيب راحات/فرق/تكليفات مسجّلة بعد
            # التاريخ الجديد معلّقة — نفس مبدأ فحص الانضمام فوق.
            conflicts = service_window_conflicts(data, person_id, category,
                                                 person.get("join_date", ""), leave_date,
                                                 check_missions=True)
            if conflicts:
                raise AbortRequest((jsonify({
                    "error": "سيترك تعديل تاريخ الخروج هذا بيانات مسجّلة بعده معلّقة.",
                    "conflicts": conflicts}), 400))
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
    cleanup = bool(payload.get("cleanup"))
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

        # فيه راحات/فرق/تكليفات مسجّلة بعد تاريخ الخروج ده (مجهّزة مقدّمًا)؟
        # لو مفيش تأكيد تنظيف من المشغّل، بترفض وتوريه اللي هيتأثر —
        # عشان الخروج ما يسيبهاش معلّقة لشخص السيستم بيقول إنه خرج.
        conflicts = service_window_conflicts(data, person_id, category,
                                             found.get("join_date", ""), leave_date,
                                             check_missions=True)
        if conflicts and not cleanup:
            raise AbortRequest((jsonify({
                "error": "توجد بيانات مسجّلة بعد تاريخ الخروج هذا — أكّد التنظيف للمتابعة.",
                "needs_confirm": True, "conflicts": conflicts}), 409))

        report = {}
        if conflicts:
            report = cleanup_outside_window(data, person_id, category,
                                            found.get("join_date", ""), leave_date)

        found["leave_date"] = leave_date
        found["leave_reason"] = reason
        found["status"] = "archived"

        Repos(data).people.move(person_id, "archive")

        # لو الضابط شايل منصب قيادي (فردي أو جماعي)، الإخراج من القوة
        # يفضّي المنصب/يشيله من العضوية — ميفضلش متعيّن لحد مش على القوة أصلًا.
        Repos(data).config.clear_command(person_id)
        Repos(data).config.remove_from_groups(person_id)

        if report:
            changes.record(data, "person", person_id, "cleanup_on_remove",
                           after=report,
                           text=f"تنظيف بيانات بعد إخراج {found.get('name', '')}: "
                                f"{'، '.join(report)}",
                           reason=reason)
        return jsonify({**found, "cleanup": report} if report else found)

    return with_data(mutate)


@bp.post("/api/person/<person_id>/restore")
def restore_person(person_id):
    payload = json_payload()

    def mutate(data):
        found, category, bucket = Repos(data).people.locate(person_id)
        if not found or bucket != "archive":
            raise AbortRequest((jsonify({"error": "السجل غير موجود في الأرشيف."}), 404))

        repos = Repos(data)
        code = str(found.get("code", ""))
        if repos.people.code_taken(category, code):
            raise AbortRequest((jsonify({"error": "يوجد شخص على القوة بنفس رقم الأقدمية."}), 409))

        raw_join = str(payload.get("join_date", "")).strip()
        join_date = canonical_day(raw_join) if raw_join else date.today().isoformat()
        if raw_join and not join_date:
            raise AbortRequest((jsonify({"error": "تاريخ الانضمام غير صحيح."}), 400))
        # لازم يكون بعد تاريخ خروجه القديم — وإلا نفس الشخص هيبقى على القوة
        # مرتين في نفس اليوم (سجل الأرشيف لسه شامل يوم الخروج، والسجل الجديد
        # هيبتدي منه أو قبله) وأصل القوة هيتحسب زيادة واحد في جدول الإجمالي.
        left = str(found.get("leave_date", "") or "")
        if left and join_date <= left:
            raise AbortRequest((jsonify({
                "error": f"يجب أن يكون تاريخ الانضمام الجديد بعد تاريخ الخروج ({left}) — "
                         "وإلا فسيُحتسب الشخص مرتين في اليوم نفسه.",
                "leave_date": left}), 400))

        # Keep the historical record intact and create a new active period.
        restored = dict(found)
        restored.update({
            "id": repos.people.new_id(category),
            "code": code,
            "join_date": join_date,
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

        # الحذف النهائي بيمسح تكليفات/حالات/راحات/التحاقات من أيام كتير،
        # ومنها أيام مقفولة من زمان — لازم يتحسبوا **قبل** الحذف عشان
        # بعده مفيش أثر يتحسب منه أصلًا.
        key = "officer_ids" if category == "officers" else "personnel_ids"
        closed = set(d for d in repos.days.assignment_days_of(person_id, (key,))
                    if day_status.is_closed(data, d))
        for lv in repos.leaves.of_person(person_id):
            closed |= set(retro.closed_days_in(data, lv.start, lv.end))
        if category == "officers":
            closed |= set(d for d in repos.days.officer_state_days_of(person_id)
                          if day_status.is_closed(data, d))
            for t in repos.terms.of_officer(person_id):
                closed |= set(retro.closed_days_in(data, t.start, t.end))
        closed = sorted(closed)
        reason = retro.require_reason(closed)

        repos.people.remove(person_id)
        report = cascade_delete(repos, person_id, category)
        changes.record(data, "person", person_id, "delete", before=raw, after=report,
                       reason=reason,
                       text=f"حذف نهائي لسجل {raw.get('name', '')} من الأرشيف"
                            + (f" — {'، '.join(f'{k}: {v}' for k, v in report.items())}"
                               if report else ""))
        if closed:
            retro.log_retro(data, "person", person_id, closed, reason,
                           before=raw, after=report,
                           text=f"حذف نهائي لسجل {raw.get('name', '')} يؤثر في يوم مغلق "
                                f"أو عدة أيام مغلقة: {'، '.join(closed)}")
        return jsonify({"ok": True})

    return with_data(mutate)

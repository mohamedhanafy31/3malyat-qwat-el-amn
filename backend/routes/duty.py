"""يومية تشغيل الضباط — العرض، وحالة الضابط اليومية.

التكليف بخدمة بقى من `/api/assignments/<day>` (نفس النقطة اللي اللوحة
بتستخدمها) — الصفحة دي بتعدّل **حالة** الضابط بس: تقصيرة، حالة خاصة،
وملاحظة، وتشغيل إضافي بيتضاف على خدمته التلقائية، وإضافته للعمل بالإدارة
في اللوحة. دي حقيقة مختلفة عن التكليف مش نسخة تانية منه.

«مرضي»/«غياب» بتبدأ من اليوم وتستمر لحد «إنهاء الحالة من هذا اليوم»، و«طارئة»
و«مأمورية» و«انتداب» لازم معاها ``status_end`` (حتى يوم، شامل) وبتنتهي
لوحدها — و«مأمورية»/«انتداب» كمان ``status_title`` و``status_details``. كله
سجل مدى في `status_periods.py` مش نسخة في كل ملف يوم. «إلغاء تسجيل الحالة
بالكامل» (`cancel-status`) بيمسح السجل كله لأنه كان تسجيل بالغلط، عكس الإنهاء
اللي بيحفظ اللي فات. «فرقة» مصدرها التحاق الفرق.
تشغيل «طبية» بقى منصب ثابت في قيادة الإدارة (`PATCH /api/command`) مش
حالة يومية هنا.
"""
from copy import deepcopy
from flask import Blueprint, jsonify, send_file

from .. import changes
from .. import day_status
from ..assignments import (assignments_of, is_legacy_status, officer_state, officer_statuses,
                           remember_officer_status, set_officer_state)
from ..clocktime import format_time, parse_time
from ..constants import ROLE_MEDICAL, ROLE_SEARCH
from ..dated import (MEDICAL_STATES, groups_on, medical_state_on,
                     record_medical_state_change)
from ..duty import operational_text, summarise
from ..duty_export import build_docx
from ..daily_view import build as build_daily_view
from ..day_open import needs_prepare, prepare
from ..people import officers_on
from ..store import AbortRequest, load_data, revision, stale_revision, with_data
from .. import retro
from ..status_periods import PERIOD_STATUSES, PeriodError, describe, is_bounded
from ..status_periods import active_on as persistent_status_on
from ..status_periods import cancel as cancel_persistent_status
from ..status_periods import start as start_persistent_status
from ..status_periods import stop as stop_persistent_status
from ..utils import MAX_LEN, around, canonical_day, json_payload

bp = Blueprint("duty", __name__)


def _state_text(name, day, before, after):
    """جملة السجل لتغيير حالة ضابط في يومية الضباط — إيه اللي اتغيّر بالظبط."""
    before, after = before or {}, after or {}
    parts = []
    if bool(before.get("taqseera")) != bool(after.get("taqseera")):
        parts.append("تقصيرة" if after.get("taqseera") else "إلغاء التقصيرة")
    if (before.get("status") or "") != (after.get("status") or ""):
        parts.append(f"الحالة: {before.get('status') or '—'} ← {after.get('status') or '—'}")
    if (before.get("note") or "") != (after.get("note") or ""):
        parts.append(f"الملاحظة: {after.get('note') or 'مُسحت'}")
    if (before.get("extra") or "") != (after.get("extra") or ""):
        parts.append(f"التشغيل الإضافي: {after.get('extra') or 'مُسح'}")
    if bool(before.get("admin_work")) != bool(after.get("admin_work")):
        parts.append("إضافته للعمل بالإدارة" if after.get("admin_work")
                     else "إلغاء إضافته للعمل بالإدارة")
    if (before.get("research_service") or "") != (after.get("research_service") or ""):
        parts.append(f"خدمة البحث: {after.get('research_service') or 'مُسحت'}")
    if (before.get("research_time") or "") != (after.get("research_time") or ""):
        parts.append(f"انتظام البحث: {after.get('research_time') or 'مُسح'}")
    return f"{name} في يومية {day}: " + "، ".join(parts or ["تعديل الحالة"])


def _period_text(name, day, period, before, closed):
    """جملة السجل لبدء/تعديل حالة ممتدة."""
    status = period.get("status", "")
    # «مأمورية»/«انتداب»: الاسم والتفاصيل جزء من نص السجل
    detail = describe(period) if describe(period) != status else ""
    suffix = f" ({detail})" if detail else ""
    if before and before.get("id") == period.get("id"):
        text = f"تعديل {status} لـ{name}: من {period.get('start')} حتى {period.get('end')}{suffix}"
    elif is_bounded(status):
        text = f"بدء {status} لـ{name} من {day} حتى {period.get('end')}{suffix}"
    elif period.get("end"):
        # حالة مستمرة اتقفلت تلقائيًا قبل حالة لاحقة مجدولة
        text = (f"بدء حالة {status} المستمرة لـ{name} من {day} "
                f"حتى {period['end']} (قبل حالة مسجلة لاحقًا)")
    else:
        text = f"بدء حالة {status} المستمرة لـ{name} من {day} حتى إنهائها"
    if closed and closed.get("id") != period.get("id"):
        text += f"، مع إنهاء حالة {closed.get('status', '')} السابقة"
    return text


@bp.get("/api/duty/<day>")
def get_duty(day):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    scope = around(day, -1, 0)
    data = load_data(scope)
    pending = needs_prepare(data, day)
    preview = deepcopy(data)
    if pending:
        prepare(preview, day)
    payload = summarise(preview, day)
    payload.update(revision=revision(data, [day]), preparation_pending=pending)
    return jsonify(payload)


@bp.get("/api/duty/<day>/export.docx")
def export_duty_docx(day):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    data = load_data(around(day, -1, 0))
    preview = deepcopy(data)
    if needs_prepare(data, day):
        prepare(preview, day)
    buf = build_docx(summarise(preview, day))
    return send_file(buf, as_attachment=True, download_name=f"يومية الضباط {day}.docx",
                     mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@bp.put("/api/duty/<day>/<person_id>")
def set_state(day, person_id):
    """حالة الضابط في يوم معيّن. التكليفات مش هنا — دي في /api/assignments."""
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    payload = json_payload()

    status = str(payload.get("status", "")).strip()
    note = str(payload.get("note", "")).strip()
    if len(note) > MAX_LEN["note"]:
        return jsonify({"error": f"الملاحظة أطول من الحد المسموح ({MAX_LEN['note']} حرف)."}), 400
    extra = str(payload.get("extra", "") or "").strip()
    if len(extra) > MAX_LEN["note"]:
        return jsonify({"error": f"التشغيل الإضافي أطول من الحد المسموح ({MAX_LEN['note']} حرف)."}), 400
    status_end = str(payload.get("status_end", "") or "").strip()
    if status_end and status not in PERIOD_STATUSES:
        return jsonify({"error": "يوم النهاية (حتى يوم) خاص بحالات «طارئة» و«مأمورية» و«انتداب»."}), 400
    status_title = str(payload.get("status_title", "") or "").strip()
    status_details = str(payload.get("status_details", "") or "").strip()
    # قفل الطول قبل التطبيع عشان نص طويل بمسافات مايعدّيش
    if len(status_title) > 4 * 120 or len(status_details) > 4 * 300:
        return jsonify({"error": "اسم أو تفاصيل الحالة أطول من الحد المسموح."}), 400
    research_service = str(payload.get("research_service", "") or "").strip()
    if len(research_service) > MAX_LEN["note"]:
        return jsonify({"error": f"اسم خدمة البحث أطول من الحد المسموح ({MAX_LEN['note']} حرف)."}), 400
    research_time = str(payload.get("research_time", "") or "").strip()
    if research_time:
        parsed = parse_time(research_time)
        if parsed is None:
            return jsonify({"error": "اختر معاد الانتظام من لوحة الساعة."}), 400
        research_time = format_time(parsed)
    medical_state = str(payload.get("medical_state", "") or "").strip()
    medical_text = str(payload.get("medical_deputation_text", "") or "").strip()
    if "medical_deputation_text" in payload and "medical_state" not in payload:
        return jsonify({"error": "اختر حالة الطبي مع نص الانتداب."}), 400
    if "medical_state" in payload and medical_state not in MEDICAL_STATES:
        return jsonify({"error": "حالة الطبي يجب أن تكون عمل أو راحة أو انتداب."}), 400
    if len(medical_text) > MAX_LEN["note"]:
        return jsonify({"error": f"نص انتداب الطبي أطول من الحد المسموح ({MAX_LEN['note']} حرف)."}), 400

    def mutate(data):
        stale = stale_revision(data, payload.get("revision"), [day])
        if stale:
            raise AbortRequest((jsonify({"code": "stale_revision", "revision": stale,
                                         "error": "البيانات تغيّرت؛ أعد تحميل اليوم."}), 409))
        prepare(data, day)
        ok, lock_err = day_status.check_open(data, day)
        if not ok:
            raise AbortRequest((jsonify({"error": lock_err}), 409))
        # الحالة بتتقاس على قوة اليوم نفسه، فالضابط المتأرشف ينفع يتعدّل
        # في يوم كان فيه بالقوة
        officer = next((o for o in officers_on(data, day) if o.get("id") == person_id), None)
        if not officer:
            raise AbortRequest((jsonify({"error": "الضابط لم يكن على القوة في هذا اليوم."}), 404))
        groups = groups_on(data, day)
        is_research = person_id in (groups.get(ROLE_SEARCH) or [])
        is_medical = person_id in (groups.get(ROLE_MEDICAL) or [])
        if ({"research_service", "research_time"} & payload.keys()) and not is_research:
            raise AbortRequest((jsonify({"error": "الضابط ليس ضمن مجموعة البحث في هذا اليوم."}), 400))
        if ({"medical_state", "medical_deputation_text"} & payload.keys()) and not is_medical:
            raise AbortRequest((jsonify({"error": "الضابط ليس ضمن مجموعة الطبي في هذا اليوم."}), 400))
        # الحقل اللي مش مبعوت في الطلب مابيتغيّرش. قبل كده كانت القيم
        # التلاتة بتتكتب دايمًا، فطلب فيه `taqseera` بس كان بيمسح الحالة
        # والملاحظة المسجّلين — الواجهة بتبعت التلاتة فما بانش، لكن أي
        # سكربت أو نداء خارجي كان بيفقد بيانات من غير ما يعرف.
        before = dict(officer_state(data, day, person_id))
        projected_research = (research_service if "research_service" in payload
                              else before.get("research_service", ""))
        saved_research_time = research_time if "research_time" in payload else None
        # مسح اسم الخدمة يمسح ميعادها معاه؛ ماينفعش نخزن انتظام بلا خدمة.
        if "research_service" in payload and not projected_research:
            saved_research_time = ""
        elif "research_time" in payload and research_time and not projected_research:
            raise AbortRequest((jsonify({"error": "اكتب اسم خدمة البحث قبل معاد الانتظام."}), 400))
        if payload.get("admin_work"):
            projected_note = note if "note" in payload else before.get("note", "")
            projected_extra = extra if "extra" in payload else before.get("extra", "")
            if not operational_text(assignments_of(data, day, person_id),
                                    projected_note, projected_extra):
                raise AbortRequest((jsonify({
                    "error": "اكتب النص التشغيلي قبل إضافة الضابط إلى عمل بالإدارة."
                }), 400))
        # «فرقة»/«راحة فرقة» قيم أرشيفية: صف قديم مكتوب فيه أي منهم بيتحفظ
        # زي ما هو (تعديل ملاحظته مثلًا)، لكن مفيش تسجيل جديد بيهم.
        keeps_legacy = ("status" in payload and is_legacy_status(status)
                        and status == (before.get("status") or ""))
        if "status" in payload and status not in PERIOD_STATUSES and not keeps_legacy:
            status_error = remember_officer_status(data, status)
            if status_error:
                raise AbortRequest((jsonify({"error": status_error}), 400))
        period_before = dict(persistent_status_on(data, person_id, day) or {})
        period_after = closed = None
        period_changed = False
        # سجل قديم مفتوح (انتداب/طارئة بلا نهاية) بيتحفظ زي ما هو لما الحفظ
        # مش بيبعت نهاية ولا اسم — مثلًا تعديل ملاحظة بس؛ ما يتفرضش عليه
        # اكتمال البيانات إلا لو المستخدم فعلًا بيعدّل الحالة نفسها.
        current = persistent_status_on(data, person_id, day)
        keeps_open_legacy = bool(
            current and current.get("status") == status and not current.get("end")
            and is_bounded(status) and not status_end and not status_title
            and not status_details)
        if "status" in payload and status in PERIOD_STATUSES and keeps_open_legacy:
            stored_status = ""
        elif "status" in payload and status in PERIOD_STATUSES:
            try:
                period, period_changed, closed = start_persistent_status(
                    data, person_id, status, day, end=status_end,
                    title=status_title, details=status_details)
            except PeriodError as error:
                raise AbortRequest((jsonify({"error": str(error)}), error.status))
            period_after = dict(period)
            # الحالة الممتدة مصدرها سجل المدى؛ لا نكررها في ملف اليوم.
            stored_status = ""
        else:
            stored_status = status
        after = set_officer_state(
            data, day, person_id,
            taqseera=bool(payload["taqseera"]) if "taqseera" in payload else None,
            status=stored_status if "status" in payload else None,
            note=note if "note" in payload else None,
            extra=extra if "extra" in payload else None,
            admin_work=bool(payload["admin_work"]) if "admin_work" in payload else None,
            research_service=research_service if "research_service" in payload else None,
            research_time=saved_research_time)
        # المقارنة على القيم الفعلية بس: حفظ حالة الطبي لوحدها كان بيسجّل
        # «تعديل الحالة» فاضي لأن السجل الراجع فيه false/"" بدل ما يكون فاضي.
        if ({k: v for k, v in before.items() if v}
                != {k: v for k, v in dict(after).items() if v}):
            changes.record(data, "officer_state", person_id, "update",
                           before=before, after=dict(after), reason=f"يوم {day}",
                           text=_state_text(officer.get("name", ""), day, before, after))
        if "medical_state" in payload:
            medical_before = medical_state_on(data, person_id, day)
            medical_after = record_medical_state_change(
                data, person_id, day, medical_state,
                medical_text if medical_state == "انتداب" else "")
            if medical_before != medical_after:
                changes.record(
                    data, "officer_medical_state", f"{person_id}:{day}", "update",
                    before=medical_before, after=medical_after, day=day,
                    text=(f"حالة الطبي لـ{officer.get('name', '')} من {day}: "
                          f"{medical_state}"
                          + (f" — {medical_text}" if medical_state == "انتداب" and medical_text else "")),
                )
        if period_changed:
            updated = period_before.get("id") == period_after["id"]
            changes.record(
                data, "officer_status_period", period_after["id"],
                "update" if updated else "create",
                before=period_before or None, after=period_after, day=day,
                text=_period_text(officer.get("name", ""), day, period_after,
                                  period_before, closed),
            )
        result = summarise(data, day)
        result["officer_statuses"] = officer_statuses(data)
        result["daily"] = build_daily_view(data, day)
        result["revision"] = result["daily"]["revision"]
        return jsonify(result)

    return with_data(mutate, around(day, -1, 0))


@bp.post("/api/duty/<day>/<person_id>/stop-status")
def stop_continuous_status(day, person_id):
    """إنهاء الحالة من هذا اليوم: اجعل ``day`` أول يوم عادي بعد حالة ممتدة فعالة.

    الاستخدام الأساسي إنهاء «مرضي»/«غياب» المفتوحة، وسجلات «طارئة»/«انتداب»
    القديمة اللي اتعملت من غير نهاية. الحالة بنهاية بتخلص لوحدها؛ لو اتنهت
    هنا بدري بتتقصّر لليوم السابق وبيتحفظ اللي فات. للتسجيل الغلط من
    الأساس استخدم ``cancel-status``."""
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400

    def mutate(data):
        ok, lock_err = day_status.check_open(data, day)
        if not ok:
            raise AbortRequest((jsonify({"error": lock_err}), 409))
        officer = next((o for o in officers_on(data, day) if o.get("id") == person_id), None)
        if not officer:
            raise AbortRequest((jsonify({"error": "الضابط لم يكن على القوة في هذا اليوم."}), 404))
        before, after = stop_persistent_status(data, person_id, day)
        if not before:
            raise AbortRequest((jsonify({"error": "لا توجد حالة ممتدة (مرضي/غياب/انتداب/طارئة/مأمورية) فعالة في هذا اليوم."}), 404))
        state = dict(officer_state(data, day, person_id))
        if state.get("status") == before.get("status"):
            set_officer_state(data, day, person_id, status="")
        name = officer.get("name", "")
        status = before.get("status", "")
        if after is None:
            text = (f"إنهاء حالة {status} لـ{name} من {day} — وهو أول يوم فيها، "
                    "فأُزيل السجل لعدم وجود أيام سابقة")
        else:
            text = f"إنهاء حالة {status} لـ{name} من {day} (آخر يوم فيها {after.get('end')})"
        changes.record(
            data, "officer_status_period", before["id"], "delete" if after is None else "update",
            before=before, after=after, day=day, text=text,
        )
        result = summarise(data, day)
        result["revision"] = revision(data, [day])
        return jsonify(result)

    return with_data(mutate, around(day, -1, 0))


@bp.post("/api/duty/<day>/<person_id>/cancel-status")
def cancel_status(day, person_id):
    """إلغاء تسجيل الحالة بالكامل: بيمسح سجل الحالة اللي بيغطي ``day`` من
    أوله لآخره (الماضي والمستقبل) — لتسجيل اتعمل بالغلط. للإنهاء مع حفظ
    اللي فات استخدم ``stop-status``.

    نفس سياسة الأيام المقفولة: اليوم المختار لازم يكون مفتوح، ولو السجل
    بيغطي أيام مقفولة تانية لازم سبب مكتوب (`X-Retro-Reason`) ويتسجّل بأثر رجعي."""
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400

    def scope(view):
        return sorted({*around(day, -1, 0), *retro.status_scope(view)})

    def mutate(data):
        ok, lock_err = day_status.check_open(data, day)
        if not ok:
            raise AbortRequest((jsonify({"error": lock_err}), 409))
        officer = next((o for o in officers_on(data, day) if o.get("id") == person_id), None)
        if not officer:
            raise AbortRequest((jsonify({"error": "الضابط لم يكن على القوة في هذا اليوم."}), 404))
        current = persistent_status_on(data, person_id, day)
        if not current:
            raise AbortRequest((jsonify({"error": "لا توجد حالة ممتدة (مرضي/غياب/انتداب/طارئة/مأمورية) فعالة في هذا اليوم."}), 404))
        closed = retro.closed_days_in(
            data, current.get("start", ""), current.get("end") or day_status.today_iso())
        closed = [d for d in closed if d != day]
        reason = retro.require_reason(closed)

        before = cancel_persistent_status(data, person_id, day)
        status = before.get("status", "")
        # نسخ يومية قديمة من نفس الحالة على أيام السجل — ما نسيبهاش معلّقة
        # (النسخة بتتشال من اليوم المختار بس؛ الحالات الممتدة مش بتتنسخ في الملفات)
        state = dict(officer_state(data, day, person_id))
        if state.get("status") == status:
            set_officer_state(data, day, person_id, status="")
        detail = describe(before)
        span = (f"من {before.get('start')} حتى {before.get('end')}" if before.get("end")
                else f"من {before.get('start')} (مفتوحة)")
        text = (f"إلغاء تسجيل حالة {status} لـ{officer.get('name', '')} بالكامل "
                f"({span}) من يوم {day}"
                + (f" — {detail}" if detail != status else ""))
        changes.record(data, "officer_status_period", before["id"], "delete",
                       before=before, day=day, text=text)
        if closed:
            retro.log_retro(data, "officer_status_period", before["id"], closed, reason,
                            before=before, text=f"{text} — يشمل أيامًا مغلقة: {'، '.join(closed)}")
        result = summarise(data, day)
        result["officer_statuses"] = officer_statuses(data)
        result["daily"] = build_daily_view(data, day)
        result["revision"] = result["daily"]["revision"]
        return jsonify(result)

    return with_data(mutate, scope)


@bp.delete("/api/duty/<day>/<person_id>")
def clear_state(day, person_id):
    """مسح حالة الضابط المكتوبة في اليوم ده (تقصيرة/ملاحظة/إضافي/حالة اليوم).

    ده **مش** إلغاء تسجيل: لو فيه حالة ممتدة بتغطي اليوم بتتنهي من اليوم ده
    (يوم المسح أول يوم عادي) وبيتحفظ اللي قبله، والرد بيقول كده صراحة في
    ``ended_status``. المسح الكامل للتسجيل الغلط له ``cancel-status``."""
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400

    def mutate(data):
        ok, lock_err = day_status.check_open(data, day)
        if not ok:
            raise AbortRequest((jsonify({"error": lock_err}), 409))
        officer = next((o for o in officers_on(data, day) if o.get("id") == person_id), None)
        if not officer:
            raise AbortRequest((jsonify({"error": "الضابط لم يكن على القوة في هذا اليوم."}), 404))
        before = dict(officer_state(data, day, person_id))
        set_officer_state(data, day, person_id, taqseera=False, status="", note="",
                          extra="", admin_work=False, research_service="", research_time="")
        if before:
            changes.record(data, "officer_state", person_id, "delete",
                           before=before, reason=f"يوم {day}",
                           text=f"مسح حالة {officer.get('name', '')} في يومية {day}")
        # مسح حالة اليوم = اليوم ده يرجع عادي، فالحالة الممتدة بتقف منه
        # (وتتلغي لو كانت بادئة فيه) — نفس «إيقاف الحالة» بالظبط.
        period_before, period_after = stop_persistent_status(data, person_id, day)
        if period_before:
            changes.record(
                data, "officer_status_period", period_before["id"],
                "delete" if period_after is None else "update",
                before=period_before, after=period_after, day=day,
                text=f"إنهاء حالة {period_before.get('status', '')} لـ"
                     f"{officer.get('name', '')} من {day} (مسح حالة اليوم — "
                     "ليس إلغاءً كاملًا للتسجيل)")
        result = {"ok": True, "daily": build_daily_view(data, day),
                  "ended_status": period_before.get("status") if period_before else None}
        result["revision"] = result["daily"]["revision"]
        return jsonify(result)

    return with_data(mutate, [day])

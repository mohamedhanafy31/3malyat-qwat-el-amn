"""يومية تشغيل الضباط — العرض، وحالة الضابط اليومية.

التكليف بخدمة بقى من `/api/assignments/<day>` (نفس النقطة اللي اللوحة
بتستخدمها) — الصفحة دي بتعدّل **حالة** الضابط بس: تقصيرة، انتداب/غياب/
مرضي/فرقة/طارئة، وملاحظة، وتشغيل إضافي بيتضاف على خدمته التلقائية،
وإضافته للعمل بالإدارة في اللوحة. دي حقيقة مختلفة عن التكليف مش نسخة تانية منه.
تشغيل «طبية» بقى منصب ثابت في قيادة الإدارة (`PATCH /api/command`) مش
حالة يومية هنا.
"""
from copy import deepcopy
from flask import Blueprint, jsonify, send_file

from .. import changes
from .. import day_status
from ..assignments import officer_state, officer_statuses, remember_officer_status, set_officer_state
from ..duty import summarise
from ..duty_export import build_docx
from ..daily_view import build as build_daily_view
from ..day_open import needs_prepare, prepare
from ..people import officers_on
from ..store import AbortRequest, load_data, revision, stale_revision, with_data
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
    return f"{name} في يومية {day}: " + "، ".join(parts or ["تعديل الحالة"])


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
        status_error = remember_officer_status(data, status) if "status" in payload else None
        if status_error:
            raise AbortRequest((jsonify({"error": status_error}), 400))
        # الحقل اللي مش مبعوت في الطلب مابيتغيّرش. قبل كده كانت القيم
        # التلاتة بتتكتب دايمًا، فطلب فيه `taqseera` بس كان بيمسح الحالة
        # والملاحظة المسجّلين — الواجهة بتبعت التلاتة فما بانش، لكن أي
        # سكربت أو نداء خارجي كان بيفقد بيانات من غير ما يعرف.
        before = dict(officer_state(data, day, person_id))
        after = set_officer_state(
            data, day, person_id,
            taqseera=bool(payload["taqseera"]) if "taqseera" in payload else None,
            status=status if "status" in payload else None,
            note=note if "note" in payload else None,
            extra=extra if "extra" in payload else None,
            admin_work=bool(payload["admin_work"]) if "admin_work" in payload else None)
        if before != dict(after):
            changes.record(data, "officer_state", person_id, "update",
                           before=before, after=dict(after), reason=f"يوم {day}",
                           text=_state_text(officer.get("name", ""), day, before, after))
        result = summarise(data, day)
        result["officer_statuses"] = officer_statuses(data)
        result["daily"] = build_daily_view(data, day)
        result["revision"] = result["daily"]["revision"]
        return jsonify(result)

    return with_data(mutate, around(day, -1, 0))


@bp.delete("/api/duty/<day>/<person_id>")
def clear_state(day, person_id):
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
                          extra="", admin_work=False)
        if before:
            changes.record(data, "officer_state", person_id, "delete",
                           before=before, reason=f"يوم {day}",
                           text=f"مسح حالة {officer.get('name', '')} في يومية {day}")
        result = {"ok": True, "daily": build_daily_view(data, day)}
        result["revision"] = result["daily"]["revision"]
        return jsonify(result)

    return with_data(mutate, [day])

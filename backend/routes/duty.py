"""يومية تشغيل الضباط — العرض، وحالة الضابط اليومية.

التكليف بخدمة بقى من `/api/assignments/<day>` (نفس النقطة اللي اللوحة
بتستخدمها) — الصفحة دي بتعدّل **حالة** الضابط بس: تقصيرة، انتداب/غياب/
مرضي/فرقة/طارئة، وملاحظة. دي حقيقة مختلفة عن التكليف مش نسخة تانية منه.
تشغيل «طبية» بقى منصب ثابت في قيادة الإدارة (`PATCH /api/command`) مش
حالة يومية هنا.
"""
from copy import deepcopy
from flask import Blueprint, jsonify, send_file

from .. import changes
from .. import day_status
from ..assignments import OFFICER_STATUSES, officer_state, set_officer_state
from ..duty import summarise
from ..duty_export import build_docx
from ..daily_view import build as build_daily_view
from ..day_open import needs_prepare, prepare
from ..people import officers_on
from ..store import AbortRequest, load_data, revision, stale_revision, with_data
from ..utils import MAX_LEN, around, canonical_day, json_payload

bp = Blueprint("duty", __name__)


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
    if status and status not in OFFICER_STATUSES:
        return jsonify({"error": "حالة غير صحيحة."}), 400
    note = str(payload.get("note", "")).strip()
    if len(note) > MAX_LEN["note"]:
        return jsonify({"error": f"الملاحظة أطول من الحد المسموح ({MAX_LEN['note']} حرف)."}), 400

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
        if not any(o.get("id") == person_id for o in officers_on(data, day)):
            raise AbortRequest((jsonify({"error": "الضابط لم يكن على القوة في هذا اليوم."}), 404))
        # الحقل اللي مش مبعوت في الطلب مابيتغيّرش. قبل كده كانت القيم
        # التلاتة بتتكتب دايمًا، فطلب فيه `taqseera` بس كان بيمسح الحالة
        # والملاحظة المسجّلين — الواجهة بتبعت التلاتة فما بانش، لكن أي
        # سكربت أو نداء خارجي كان بيفقد بيانات من غير ما يعرف.
        before = dict(officer_state(data, day, person_id))
        after = set_officer_state(
            data, day, person_id,
            taqseera=bool(payload["taqseera"]) if "taqseera" in payload else None,
            status=status if "status" in payload else None,
            note=note if "note" in payload else None)
        if before != dict(after):
            changes.record(data, "officer_state", person_id, "update",
                           before=before, after=dict(after), reason=f"يوم {day}")
        result = summarise(data, day)
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
        if not any(o.get("id") == person_id for o in officers_on(data, day)):
            raise AbortRequest((jsonify({"error": "الضابط لم يكن على القوة في هذا اليوم."}), 404))
        before = dict(officer_state(data, day, person_id))
        set_officer_state(data, day, person_id, taqseera=False, status="", note="")
        if before:
            changes.record(data, "officer_state", person_id, "delete",
                           before=before, reason=f"يوم {day}")
        result = {"ok": True, "daily": build_daily_view(data, day)}
        result["revision"] = result["daily"]["revision"]
        return jsonify(result)

    return with_data(mutate, [day])

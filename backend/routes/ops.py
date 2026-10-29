"""API لوحة تشغيل الخدمات."""
from copy import deepcopy
from datetime import date, timedelta

from flask import Blueprint, jsonify, send_file

from .. import day_status, ops_board
from .. import changes
from ..regularity import (build as build_regularity,
                           clear_inputs, default_inputs, effective_inputs,
                           saved_inputs, save_inputs)
from ..regularity_export import build_docx as build_regularity_docx
from ..auth import current_actor
from ..day_open import needs_prepare, prepare
from ..store import AbortRequest, load_data, revision, stale_revision, with_data
from ..people import effective, officers_on
from ..dated import command_on
from ..utils import MAX_LEN, canonical_day, json_payload

bp = Blueprint("ops", __name__)


def _scope(day):
    value = date.fromisoformat(day)
    return [(value - timedelta(days=i)).isoformat() for i in range(4)]


def _day(raw):
    return canonical_day(raw)


def _regularity_preview(data, day, inputs):
    payload = build_regularity(data, day, inputs)
    return {"officer_rows": payload["officer_rows"], "notes": payload["notes"],
            "signatories": payload["signatories"], "warnings": payload["warnings"],
            "service_rows": len(payload["service_rows"])}


def _regularity_response(data, day):
    inputs, inherited_from = effective_inputs(data, day)
    # المعاينة قراءة فقط؛ تجهيز اليوم هنا كان يضيف بذورًا تلقائية إلى الـcore
    # رغم أن الطلب GET. التصدير نفسه يجهّز نسخة في الذاكرة قبل بناء Word.
    preview = _regularity_preview(data, day, inputs)
    officers = []
    for officer in officers_on(data, day):
        dated = {**officer, **effective(officer, day)}
        officers.append({"id": officer["id"], "rank": dated.get("role", ""),
                         "name": dated.get("short_name") or dated.get("name", "")})
    return {"inputs": inputs, "inherited_from": inherited_from,
            "defaults": default_inputs(), "preview": preview,
            "officers": officers, "command": command_on(data, day),
            "revision": revision(data, _scope(day))}


def _validate_regularity_inputs(data, day, body):
    raw = body.get("inputs")
    if not isinstance(raw, dict):
        return None, "بيانات الانتظام غير صحيحة."
    on_force = {str(item.get("id")): item for item in officers_on(data, day)}
    command = command_on(data, day)
    allowed_extra = {str(ident) for ident in command.values() if ident}
    extra = raw.get("officer_extra") or {}
    if not isinstance(extra, dict) or not set(map(str, extra)) <= allowed_extra:
        return None, "نص المدير أو الوكيل مربوط بضابط غير موجود في قيادة اليوم."
    clean_extra = {}
    for ident, value in extra.items():
        text = str(value or "").strip()
        if len(text) > MAX_LEN["note"]:
            return None, f"نص الضابط أطول من الحد المسموح ({MAX_LEN['note']} حرف)."
        if text:
            clean_extra[str(ident)] = text
    supervisors = raw.get("big_column_supervisors") or {}
    if not isinstance(supervisors, dict) or set(supervisors) - {"am", "pm"}:
        return None, "اختيارات مشرف القول المكبر غير صحيحة."
    clean_supervisors = {}
    for shift, ident in supervisors.items():
        ident = str(ident or "").strip()
        if ident and ident not in on_force:
            return None, "مشرف القول المكبر يجب أن يكون ضابطًا على القوة في اليوم."
        if ident:
            clean_supervisors[shift] = ident
    notes = raw.get("notes")
    if not isinstance(notes, list) or len(notes) > 12:
        return None, "اكتب 12 ملاحظة أو أقل."
    clean_notes = []
    for value in notes:
        text = str(value or "").strip()
        if not text:
            return None, "الملاحظات لا يمكن أن تكون فارغة."
        if len(text) > MAX_LEN["note"]:
            return None, f"الملاحظة أطول من الحد المسموح ({MAX_LEN['note']} حرف)."
        clean_notes.append(text)
    chief = str(raw.get("operations_chief") or "").strip()
    if chief and chief not in on_force:
        return None, "رئيس قسم العمليات يجب أن يكون ضابطًا على القوة في اليوم."
    return {"officer_extra": clean_extra, "big_column_supervisors": clean_supervisors,
            "notes": clean_notes, "operations_chief": chief}, None


@bp.get("/api/ops/<day>")
def get_ops(day):
    day = _day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    data = load_data(_scope(day))
    result = ops_board.build_ops(data, day)
    result["revision"] = revision(data, _scope(day))
    return jsonify(result)


@bp.get("/api/ops/<day>/regularity.docx")
def export_regularity_docx(day):
    """يومية انتظام الخدمات الرسمية من نفس لقطة اليوم والبيانات السابقة."""
    day = _day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    data = load_data(_scope(day))
    # نفس معاينة اليومية التفصيلية: لو اليوم لسه ما اتجهزش (التفتيشات من
    # الجدول الأسبوعي…) نجهّزه على نسخة في الذاكرة من غير ما نكتب حاجة،
    # وإلا التصدير قبل فتح التفصيلية كان بيطلع من غير التفتيشات.
    if needs_prepare(data, day, include_inspections=True):
        data = deepcopy(data)
        prepare(data, day, include_inspections=True)
    inputs, _ = effective_inputs(data, day)
    payload = build_regularity(data, day, inputs)
    payload["day"] = day
    buf = build_regularity_docx(payload)
    day_number = str(date.fromisoformat(day).day)
    return send_file(buf, as_attachment=True, download_name=f"{day_number}..docx",
                     mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@bp.get("/api/ops/<day>/regularity")
def get_regularity(day):
    day = _day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    data = load_data(_scope(day))
    return jsonify(_regularity_response(data, day))


@bp.put("/api/ops/<day>/regularity")
def put_regularity(day):
    day = _day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    body = json_payload()
    scope = _scope(day)

    def mutate(data):
        stale = stale_revision(data, body.get("revision"), scope)
        if stale:
            raise AbortRequest((jsonify({"code": "stale_revision", "revision": stale,
                                         "error": "البيانات تغيّرت؛ أعد تحميل بيانات يومية الانتظام."}), 409))
        before = deepcopy(saved_inputs(data, day))
        if body.get("reset"):
            clear_inputs(data, day)
            after = None
            action = "reset"
        else:
            after, error = _validate_regularity_inputs(data, day, body)
            if error:
                raise AbortRequest((jsonify({"error": error}), 400))
            save_inputs(data, day, after)
            action = "update"
        changes.record(data, "regularity_inputs", day, action, before=before, after=after,
                       day=day, text=(f"تعديل بيانات يومية الانتظام ليوم {day}"
                                     if action == "update" else f"استرجاع توريث يومية الانتظام ليوم {day}"))
        return jsonify(_regularity_response(data, day))
    return with_data(mutate, scope)


def _mutate(day, body, fn, *, check_revision=True):
    scope = _scope(day)
    actor = current_actor()["display_name"]

    def mutate(data):
        if check_revision:
            stale = stale_revision(data, body.get("revision"), scope)
            if stale:
                raise AbortRequest((jsonify({"code": "stale_revision", "revision": stale,
                                             "error": "البيانات تغيّرت؛ أعد تحميل لوحة التشغيل."}), 409))
        try:
            fn(data, actor)
        except ValueError as exc:
            raise AbortRequest((jsonify({"error": str(exc)}), 409))
        result = ops_board.build_ops(data, day)
        result["revision"] = revision(data, scope)
        return jsonify(result)
    return with_data(mutate, scope)


@bp.post("/api/ops/<day>/depart")
def depart(day):
    day = _day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    body = json_payload()
    keys = body.get("keys")
    if not isinstance(keys, list) or not keys:
        return jsonify({"error": "اختر خدمة واحدة على الأقل."}), 400
    return _mutate(day, body, lambda data, actor: ops_board.depart(
        data, day, keys, actor, body.get("now")))


@bp.post("/api/ops/<day>/return")
def return_service(day):
    day = _day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    body = json_payload()
    keys = body.get("keys")
    if not isinstance(keys, list) or not keys:
        return jsonify({"error": "اختر خدمة واحدة على الأقل."}), 400
    return _mutate(day, body, lambda data, actor: ops_board.return_(
        data, day, keys, actor, body.get("now")))


@bp.post("/api/ops/<day>/undo")
def undo(day):
    day = _day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    body = json_payload()
    key = body.get("ref") or body.get("key")
    return _mutate(day, body, lambda data, actor: ops_board.undo(
        data, day, key, actor, body.get("now")), check_revision=False)


@bp.patch("/api/ops/<day>/time")
def edit_time(day):
    day = _day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    body = json_payload()
    return _mutate(day, body, lambda data, actor: ops_board.set_time(
        data, day, body.get("key", ""), str(body.get("time", "")),
        body.get("scope", "day"), actor))

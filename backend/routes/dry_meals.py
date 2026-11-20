"""مسارات معاينة وحفظ وتصدير «أمر صرف وجبات جافة»."""
from flask import Blueprint, jsonify, send_file

from .. import changes, day_status
from .. import dry_meals as lib
from ..dry_meals_export import build_docx
from ..store import AbortRequest, stale_revision, with_data
from ..utils import canonical_day, json_payload

bp = Blueprint("dry_meals", __name__)


def _day(value):
    return canonical_day(value)


def _int_field(item, key):
    value = item.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 999:
        raise ValueError(f"{key} يجب أن يكون عددًا صحيحًا من 0 إلى 999.")
    return value


def _rows(body, key, *, emergency=False):
    value = body.get(key)
    if value is None and emergency:
        value = []
    if not isinstance(value, list):
        raise ValueError("الخدمات يجب أن تكون قائمة.")
    limit = lib.MAX_EMERGENCY_ROWS if emergency else lib.MAX_FIXED_ROWS
    if len(value) > limit:
        raise ValueError(f"أقصى عدد للخدمات {'الطارئة' if emergency else 'الثابتة'} {limit} خدمة.")
    result = []
    seen = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("كل خدمة يجب أن تحتوي على اسم وأعداد.")
        name = lib._clean_name(item.get("name"))
        if not name:
            raise ValueError("اسم الخدمة مطلوب.")
        if len(name) > lib.MAX_NAME or any(char in name for char in "\r\n\t"):
            raise ValueError("اسم الخدمة بحد أقصى 80 حرفًا وفي سطر واحد.")
        notes = str(item.get("notes") or "").strip()
        if len(notes) > lib.MAX_NOTES or any(char in notes for char in "\r\n\t"):
            raise ValueError("الملاحظات بحد أقصى 120 حرفًا وفي سطر واحد.")
        row = {"name": name,
               "officers": _int_field(item, "officers"),
               "personnel": _int_field(item, "personnel"),
               "conscripts": _int_field(item, "conscripts"),
               "notes": notes}
        if emergency:
            source = str(item.get("source") or "").strip()
            if source not in lib.SOURCES:
                raise ValueError("مصدر خدمة الطوارئ غير صحيح.")
            row["source"] = source
            identity = lib.service_key(name) or lib.norm(name)
            if identity in seen:
                raise ValueError("لا يجوز اختيار خدمة الطوارئ نفسها أكثر من مرة.")
            seen.add(identity)
        result.append(row)
    if not emergency and not result:
        raise ValueError("أضف خدمة ثابتة واحدة على الأقل.")
    return result


def _body_config(data, day, body):
    if "fixed_rows" not in body:
        raise ValueError("الخدمات الثابتة مطلوبة.")
    fixed = _rows(body, "fixed_rows")
    emergency_enabled = body.get("emergency_enabled", False)
    if not isinstance(emergency_enabled, bool):
        raise ValueError("اختيار خدمات الطوارئ غير صحيح.")
    emergency = _rows(body, "emergency_rows", emergency=True)
    if not emergency_enabled:
        emergency = []
    signer_id = str(body.get("ops_signer_id") or "").strip()
    members = lib._operations_members(data, day)
    if signer_id and signer_id not in {item["id"] for item in members}:
        raise ValueError("اختيار توقيع قسم العمليات غير صحيح.")
    return {"fixed_rows": fixed, "emergency_enabled": emergency_enabled,
            "emergency_rows": emergency, "ops_signer_id": signer_id}


@bp.get("/api/dry-meals/<day>")
def get_dry_meals(day):
    day = _day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    data, _preview, payload = lib.prepare_view(day)
    payload["revision"] = lib.current_revision(day)
    payload["day_status"] = day_status.status_of(data, day)
    return jsonify(payload)


@bp.get("/api/dry-meals/<day>/export.docx")
def export_dry_meals(day):
    day = _day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    _data, _preview, payload = lib.prepare_view(day)
    return send_file(
        build_docx(payload), as_attachment=True,
        download_name="أمر صرف وجبات جافة.docx",
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@bp.put("/api/dry-meals/<day>")
def save_dry_meals(day):
    day = _day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    body = json_payload()

    def mutate(data):
        stale = stale_revision(data, body.get("revision"), [day])
        if stale:
            raise AbortRequest((jsonify({
                "code": "stale_revision", "revision": stale,
                "error": "تغيّرت بيانات اليوم؛ أعد تحميل أمر الوجبات قبل الحفظ.",
            }), 409))
        ok, error = day_status.check_open(data, day)
        if not ok:
            raise AbortRequest((jsonify({"error": error}), 409))
        try:
            after = _body_config(data, day, body)
        except ValueError as exc:
            raise AbortRequest((jsonify({"error": str(exc)}), 400))
        before, _saved = lib._stored_config(data, day)
        lib.store_config(data, day, after)
        changes.record(data, "day_dry_meals", day, "update", before=before, after=after,
                       day=day, text=f"أمر صرف وجبات جافة {day}")
        result = lib.view(data, day)
        result["day_status"] = day_status.status_of(data, day)
        return jsonify(result)

    return with_data(mutate, lib.scope(day))

from flask import Blueprint, jsonify, request

from .. import changes, roster_import
from ..store import ALL_DAYS, AbortRequest, load_data, revision, stale_revision, with_data

bp = Blueprint("roster_import", __name__)


def _upload(kind):
    if kind not in {"conscripts", "personnel"}:
        raise ValueError("نوع الكشف غير صحيح.")
    upload = request.files.get("file")
    if not upload or not upload.filename:
        raise ValueError("اختر ملف الكشف أولًا.")
    filename = upload.filename
    expected = ".docx" if kind == "conscripts" else ".doc"
    if not filename.lower().endswith(expected):
        raise ValueError(f"امتداد الملف المطلوب هو {expected}.")
    return upload.read(), filename


@bp.post("/api/roster-import/<kind>/preview")
def preview_import(kind):
    try:
        blob, filename = _upload(kind)
        data = load_data(ALL_DAYS)
        result = roster_import.preview(data, kind, blob, filename,
                                       request.form.get("effective_date", ""))
        result["revision"] = revision(data)
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.post("/api/roster-import/<kind>/apply")
def apply_import(kind):
    try:
        blob, filename = _upload(kind)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    expected_hash = request.form.get("source_hash", "")
    if expected_hash != roster_import.source_hash(blob):
        return jsonify({"error": "الملف تغيّر بعد المعاينة. أعد المعاينة قبل التطبيق.",
                        "code": "source_changed"}), 409

    def mutate(data):
        stale = stale_revision(data, request.form.get("revision"))
        if stale:
            raise AbortRequest((jsonify({"error": "تغيّرت البيانات بعد المعاينة. أعد المعاينة.",
                                         "code": "stale_revision", "revision": stale}), 409))
        try:
            result = roster_import.apply(data, kind, blob, filename,
                                         request.form.get("effective_date", ""))
        except ValueError as exc:
            raise AbortRequest((jsonify({"error": str(exc)}), 400))
        entity = "conscript_roster" if kind == "conscripts" else "personnel_roster"
        label = "المجندين السائقين" if kind == "conscripts" else "الأفراد"
        changes.record(data, entity, result["source_hash"][:12], "replace",
                       after=result, text=f"استبدال كشف {label}: {result['total']} سجل")
        result["revision"] = revision(data)
        return jsonify(result)

    return with_data(mutate, ALL_DAYS)

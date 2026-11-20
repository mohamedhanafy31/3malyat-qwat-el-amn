"""مسارات معاينة وحفظ وتصدير «يومية التعيينات»."""
from flask import Blueprint, jsonify, send_file

from .. import assignments_roster as lib
from .. import changes, day_status
from ..assignments_roster_export import build_docx
from ..store import AbortRequest, stale_revision, with_data
from ..utils import around, canonical_day, json_payload

bp = Blueprint("assignments_roster", __name__)


def _day(day):
    return canonical_day(day)


@bp.get("/api/assignments-roster/<day>")
def get_roster(day):
    day = _day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    data, _preview, payload = lib.prepare_view(day)
    payload["revision"] = lib.current_revision(day)
    payload["day_status"] = day_status.status_of(data, day)
    return jsonify(payload)


@bp.get("/api/assignments-roster/<day>/export.docx")
def export_roster(day):
    day = _day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    _data, _preview, payload = lib.prepare_view(day)
    return send_file(
        build_docx(payload),
        as_attachment=True,
        download_name="يومية تعيينات الضباط.docx",
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


def _count(body, key, default):
    value = body.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 999:
        raise ValueError(f"{key} يجب أن يكون عددًا صحيحًا من 0 إلى 999.")
    return value


def _footer_categories(body, fallback):
    """يقرأ القائمة الجديدة مع قبول شكل Delta 4 أثناء الترحيل."""
    if "footer_categories" not in body:
        if "central" not in body and "ports" not in body:
            return fallback
        return [
            {"label": "ضابط امن مركزي", "count": _count(body, "central", 4)},
            {"label": "ضابط امن مواني", "count": _count(body, "ports", 1)},
        ]
    value = body.get("footer_categories")
    if not isinstance(value, list):
        raise ValueError("تصنيفات الذيل يجب أن تكون قائمة.")
    if len(value) > 8:
        raise ValueError("أقصى عدد لتصنيفات الذيل 8 تصنيفات.")
    out = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("كل تصنيف ذيل يجب أن يحتوي الاسم والعدد.")
        label = item.get("label")
        if not isinstance(label, str):
            raise ValueError("اسم تصنيف الذيل يجب أن يكون نصًا.")
        label = label.strip()
        if not label or len(label) > 60 or any(char in label for char in "\r\n\t"):
            raise ValueError("اسم تصنيف الذيل مطلوب وبحد أقصى 60 حرفًا وفي سطر واحد.")
        count = item.get("count")
        if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 999:
            raise ValueError("عدد تصنيف الذيل يجب أن يكون عددًا صحيحًا من 0 إلى 999.")
        out.append({"label": label, "count": count})
    return out


def _excluded_ids(body):
    provided = "excluded_officer_ids" in body or "excluded_ids" in body
    value = body.get("excluded_officer_ids", body.get("excluded_ids"))
    if not provided:
        return None
    if not isinstance(value, list) or any(
        isinstance(item, bool) or not isinstance(item, str) or not item.strip()
        for item in value
    ):
        raise ValueError("اختيارات الضباط يجب أن تكون قائمة معرّفات صحيحة.")
    cleaned = list(dict.fromkeys(item.strip() for item in value))
    return cleaned


@bp.put("/api/assignments-roster/<day>")
def save_roster(day):
    day = _day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    body = json_payload()
    try:
        excluded = _excluded_ids(body)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if "footer_categories" in body or "central" in body or "ports" in body:
        try:
            _footer_categories(body, lib.DEFAULT_FOOTER_CATEGORIES)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
    signer_id = str(body.get("ops_signer_id") or "").strip()

    def mutate(data):
        stale = stale_revision(data, body.get("revision"), [day])
        if stale:
            raise AbortRequest((jsonify({
                "code": "stale_revision", "revision": stale,
                "error": "تغيّرت بيانات اليوم؛ أعد تحميل الكشف قبل الحفظ.",
            }), 409))
        ok, error = day_status.check_open(data, day)
        if not ok:
            raise AbortRequest((jsonify({"error": error}), 409))
        before = lib._stored_config(data, day)
        try:
            categories = _footer_categories(body, before["footer_categories"])
        except ValueError as exc:
            raise AbortRequest((jsonify({"error": str(exc)}), 400))
        members = lib._operations_members(data, day)
        if signer_id and signer_id not in {item["id"] for item in members}:
            raise AbortRequest((jsonify({"error": "اختيار توقيع قسم العمليات غير صحيح."}), 400))
        if excluded is None:
            excluded_value = before["excluded_officer_ids"]
        else:
            # يستمر استبعاد الضابط المحفوظ حتى لو تغيّرت حالته لاحقًا إلى
            # «راحة»/حالة أخرى؛ لذلك نتحقق من القوة الحالية في D، لا من
            # قائمة «عمل» التي تتغير مع الحالة اليومية.
            allowed = set(lib._current_officer_ids(data, day))
            invalid = [item for item in excluded if item not in allowed]
            if invalid:
                raise AbortRequest((jsonify({
                    "error": "اختيار الضباط يحتوي على ضابط غير متاح في هذا اليوم.",
                }), 400))
            excluded_value = excluded
        central = next((item["count"] for item in categories
                        if item["label"] == "ضابط امن مركزي"), 0)
        ports = next((item["count"] for item in categories
                      if item["label"] == "ضابط امن مواني"), 0)
        after = {"footer_categories": categories, "central": central, "ports": ports,
                 "ops_signer_id": signer_id,
                 "excluded_officer_ids": excluded_value}
        lib.store_config(data, day, after)
        changes.record(
            data, "day_roster", day, "update", before=before, after=after, day=day,
            text=f"يومية التعيينات {day}: أعداد الأمن المركزي/المواني وتوقيع قسم العمليات",
        )
        result = lib.view(data, day)
        result["day_status"] = day_status.status_of(data, day)
        return jsonify(result)

    return with_data(mutate, around(day, -1, 0))

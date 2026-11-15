"""سجل التغييرات — عرض وتصفية بالكيان أو بسجل بعينه."""
from flask import Blueprint, jsonify, request
from io import BytesIO
from datetime import date
from flask import send_file

from .. import changes
from ..store import load_data
from ..utils import canonical_day
from ..register_export import build_register_docx, register_file_name

_ENTITY_LABELS = {"duty_move": "حركة ضابط/فرد", "assignment": "خدمة", "day_confirm": "تأكيد يومية",
    "day_lock": "قفل يوم", "officer_state": "حالة ضابط", "leave": "راحة", "mission": "مأمورية",
    "rest_suspension": "وقف الراحات", "import": "استيراد الأرشيف"}
_ACTION_LABELS = {"create": "إضافة", "update": "تعديل", "delete": "حذف", "assign": "تكليف",
    "unassign": "رفع تكليف", "confirm": "تأكيد", "close": "قفل يوم", "reopen": "فتح استثنائي",
    "stop": "إيقاف راحة", "cancel": "إلغاء راحة", "suspend": "وقف الراحات", "lift": "فتح الراحات",
    "restore": "رجوع راحة", "retro": "بأثر رجعي"}
_MONTHS = ("يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
           "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر")


def _date_label(value):
    try:
        parsed = date.fromisoformat(value)
        return f"{parsed.day} {_MONTHS[parsed.month - 1]} {parsed.year}"
    except (TypeError, ValueError):
        return value or "—"


def _stamp(value):
    if not value:
        return "—"
    day, _, clock = value.partition("T")
    return f"{_date_label(day)}\n{clock[:5]}"

bp = Blueprint("changes", __name__)


@bp.get("/api/changes")
def get_changes():
    data = load_data(())
    try:
        limit = min(int(request.args.get("limit", 200) or 200), 1000)
    except ValueError:
        limit = 200
    entity = request.args.get("entity", "").strip() or None
    entity_id = request.args.get("entity_id", "").strip() or None
    day = canonical_day(request.args.get("day", "").strip()) or None
    from_day = canonical_day(request.args.get("from_day", "").strip()) or None
    to_day = canonical_day(request.args.get("to_day", "").strip()) or None
    return jsonify({"entries": changes.recent(data, limit=limit, entity=entity,
                                              entity_id=entity_id, day=day,
                                              from_day=from_day, to_day=to_day)})


@bp.get("/api/changes/export.docx")
def export_changes():
    data = load_data(())
    entity = request.args.get("entity", "").strip() or None
    entity_id = request.args.get("entity_id", "").strip() or None
    day = canonical_day(request.args.get("day", "").strip()) or None
    from_day = canonical_day(request.args.get("from_day", "").strip()) or None
    to_day = canonical_day(request.args.get("to_day", "").strip()) or None
    entries = changes.recent(data, limit=3001, entity=entity, entity_id=entity_id,
        day=day, from_day=from_day, to_day=to_day)
    capped = len(entries) > 3000
    entries = entries[:3000]
    rows = [[_stamp(e.get("ts", "")), _date_label(e.get("day")) if e.get("day") else "—",
        _ENTITY_LABELS.get(e.get("entity"), e.get("entity") or "—"),
        _ACTION_LABELS.get(e.get("action"), e.get("action") or "—"),
        e.get("text") or (f'{_ACTION_LABELS.get(e.get("action"), e.get("action", ""))} {e.get("entity_id", "")}'
                           if e.get("entity") == "day_lock" else "—"),
        e.get("edited_by") or "—"] for e in entries]
    filters = []
    if entity: filters.append(f'النوع: {_ENTITY_LABELS.get(entity, entity)}')
    if from_day: filters.append(f'من {_date_label(from_day)}')
    if to_day: filters.append(f'إلى {_date_label(to_day)}')
    if day: filters.append(f'اليومية: {_date_label(day)}')
    if entity_id: filters.append(f'السجل: {entity_id}')
    content = build_register_docx("سجل التغييرات", [("وقت التأكيد", 1.2), ("اليومية", .9),
        ("النوع", 1), ("العملية", .8), ("التغيير", 2.4), ("المُعدِّل", 1)], rows,
        subtitle=" — ".join(filters) or "كل سجلات النظام",
        footer_note="تم عرض أحدث 3000 سجل فقط." if capped else "")
    return send_file(BytesIO(content), as_attachment=True, download_name=register_file_name("سجل التغييرات"),
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

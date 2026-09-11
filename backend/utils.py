"""أدوات عامة صغيرة مستخدمة في أكتر من مكان."""
from datetime import date

from flask import request

from .constants import COMMAND_ROLES, RANK_ORDER


def json_payload():
    """جسم الطلب كـ dict دايمًا — لو العميل بعت array أو نص أو JSON غير صحيح
    برضو بترجع {} بدل ما ترمي 500 من أول payload.get(...) بعدها."""
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


def parse_date(value):
    try:
        return date.fromisoformat(str(value).strip())
    except (ValueError, TypeError):
        return None


def canonical_day(value):
    """التاريخ في صورته المعيارية YYYY-MM-DD، أو None لو مش تاريخ صالح.

    `date.fromisoformat` في بايثون 3.11+ بيقبل صور تانية كمان («20260605»
    و«2026-W23-1»)، والمسار القديم كان بيتحقق بيها وبعدين **يستخدم النص
    الخام زي ما جه** كمفتاح تخزين لليوم أو كقيمة join_date. النتيجة إن نفس
    اليوم بيتخزّن في مفتاحين مختلفين، والمقارنات النصية («20260101» >
    «2026-06-01») بتطلع بالعكس. أي تاريخ داخل السيستم لازم يعدّي من هنا.
    """
    parsed = parse_date(value)
    return parsed.isoformat() if parsed else None


# حدود طول الحقول الحرة — مش قواعد تشغيلية، دي حماية من الإدخال الغلط
# (لصق صفحة كاملة في خانة الاسم) ومن تضخيم ملف البيانات.
MAX_LEN = {"name": 120, "code": 40, "phone": 30, "post": 200,
           "address": 200, "note": 500, "reason": 200}


def too_long(payload, field):
    """-> رسالة خطأ لو الحقل موجود في الطلب وأطول من حده، وإلا None."""
    limit = MAX_LEN.get(field)
    if limit is None or field not in payload:
        return None
    if len(str(payload[field] or "").strip()) > limit:
        return f"الحقل «{field}» أطول من الحد المسموح ({limit} حرف)."
    return None


def check_lengths(payload, fields):
    """أول خطأ طول في الحقول دي — أو None."""
    for field in fields:
        error = too_long(payload, field)
        if error:
            return error
    return None


# أرقام وفواصل الترقيم اللي بتتكتب فعلًا في التليفونات (+20، 010-123، 010 123)
_PHONE_OK = set("0123456789 +-/()")


def valid_phone(value):
    """رقم تليفون معقول — أرقام وفواصل بس، وفيه رقم واحد على الأقل.

    مش تحقق من صحة الرقم نفسه (الأرقام في الملف بصور مختلفة)، بس بيمنع
    نص عشوائي أو صفحة ملزوقة من إنها تتخزّن كتليفون.
    """
    raw = str(value or "").strip()
    if not raw or len(raw) > MAX_LEN["phone"]:
        return False
    if not any(ch.isdigit() for ch in raw):
        return False
    return all(ch in _PHONE_OK for ch in raw)


def category_for(person_type):
    return "officers" if person_type == "officer" else "personnel"


def command_priority_map(data):
    """{officer_id: ترتيبه بين مناصب القيادة} — مدير الإدارة أولًا ثم وكيله."""
    priority = {}
    command = (data or {}).get("command") or {}
    for i, role in enumerate(COMMAND_ROLES):
        officer_id = command.get(role)
        if officer_id:
            priority[officer_id] = i
    return priority


def rank_key(person, command_priority=None):
    """مدير/وكيل الإدارة دايمًا أعلى اتنين في أي قايمة ضباط، بغض النظر عن
    الرتبة العسكرية — هم الأعلى تنظيميًا في الإدارة. باقي الضباط بعدهم
    بالرتبة العسكرية العادية زي ما كان."""
    top = (command_priority or {}).get(person.get("id"), len(COMMAND_ROLES))
    r = (person.get("role") or "").strip()
    idx = RANK_ORDER.index(r) if r in RANK_ORDER else len(RANK_ORDER)
    return (top, idx, person.get("name", ""), person.get("code", ""))


def sort_active(data, category):
    """قوائم الضباط دايمًا بالرتبة (وقيادة الإدارة أولًا)؛ الأفراد بالاسم
    زي ما هو معمول من الأول."""
    if category == "officers":
        priority = command_priority_map(data)
        data[category]["active"].sort(key=lambda p: rank_key(p, priority))
    else:
        data[category]["active"].sort(key=lambda p: (p.get("name", ""), p.get("code", "")))


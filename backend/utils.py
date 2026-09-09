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


"""أدوات عامة صغيرة مستخدمة في أكتر من مكان."""
from datetime import date

from flask import request

from .constants import RANK_ORDER


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


def rank_key(person):
    r = (person.get("role") or "").strip()
    idx = RANK_ORDER.index(r) if r in RANK_ORDER else len(RANK_ORDER)
    return (idx, person.get("name", ""), person.get("code", ""))

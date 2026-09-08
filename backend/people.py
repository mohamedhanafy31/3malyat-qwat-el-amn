"""إدارة القوة — البحث عن شخص، ترتيبها، وقواعد الراحة الأساسية."""
from .constants import REST_SYSTEMS, WEEKDAYS
from .utils import command_priority_map, rank_key


def find_person(data, person_id):
    """-> (person, category, bucket) or (None, None, None)"""
    for cat in ("officers", "personnel"):
        for bucket in ("active", "archive"):
            for p in data[cat][bucket]:
                if p.get("id") == person_id:
                    return p, cat, bucket
    return None, None, None


def sort_active(data, category):
    """قوائم الضباط دايمًا بالرتبة (وقيادة الإدارة أولًا)؛ الأفراد بالاسم
    زي ما هو معمول من الأول."""
    if category == "officers":
        priority = command_priority_map(data)
        data[category]["active"].sort(key=lambda p: rank_key(p, priority))
    else:
        data[category]["active"].sort(key=lambda p: (p.get("name", ""), p.get("code", "")))


def valid_rest(payload, errors):
    """Validate and normalise the rest fields in place."""
    system = str(payload.get("rest_system", "")).strip()
    if system and system not in REST_SYSTEMS:
        errors.append("نظام الراحة غير صحيح.")
    day = str(payload.get("rest_day", "")).strip()
    if day and day not in WEEKDAYS:
        errors.append("يوم الراحة غير صحيح.")
    if system and system != "أسبوعية":
        payload["rest_day"] = ""       # only weekly rest is tied to a weekday


def officers_on(data, day):
    """الضباط اللي كانوا على القوة في اليوم ده — مش الحاليين.

    الضابط محسوب لو انضم في اليوم ده أو قبله، ولسه ما خرجش (أو خرج بعده).
    """
    out = []
    for bucket in ("active", "archive"):
        for o in data["officers"][bucket]:
            join = o.get("join_date", "")
            if join and join > day:
                continue
            left = o.get("leave_date", "")
            if left and day > left:
                continue
            out.append(o)
    priority = command_priority_map(data)
    out.sort(key=lambda o: rank_key(o, priority))
    return out

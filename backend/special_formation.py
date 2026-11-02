"""خط تشكيل الخدمات الخاصة (مباراة، انتشار، عيد…) — ملف لكل مناسبة.

المناسبة = قسم مخصّص على اللوحة (أي قسم غير الأقسام الثابتة). كل خدمة جواه
خانة في الخط: اسمها، والقائم بها، وخانة مرقّمة لكل مجند بتسليحها — نفس
«خط تشكيل مباراة» في الأرشيف.
"""
import re

from .assignments import peek_day
from .board import ASSIGNMENT_SECTIONS, _people_index, _row
from .constants import SECTION_PRISON, canonical_section_name
from .formation import _slot_weapons, slot_count
from .labels import officer_label, personnel_label
from .text import norm

# أقسام مخصّصة مش مناسبات: التفتيشات ليها ملفها، و«فرد + مج» تقسيمة استيراد قديمة.
_NOT_EVENTS = re.compile(r"^(?:[\d\s]*(?:فرد|مج|مجند)[\s+()]*)+(?:\(?\s*(?:خارجي|داخلي)\s*\)?)?$")
_EXCLUDED = {norm("تفتيشات")}


def _section(assignment):
    return canonical_section_name(assignment.get("section") or "")


def is_event(section):
    section = " ".join(str(section or "").split())
    if not section or section in ASSIGNMENT_SECTIONS or section == SECTION_PRISON:
        return False
    return norm(section) not in _EXCLUDED and not _NOT_EVENTS.match(section)


def _head(row):
    labels = [officer_label(person) for person in row.get("officers") or [] if person.get("name")]
    labels += [personnel_label(person) for person in row.get("personnel") or [] if person.get("name")]
    return " + ".join(labels)


def sections(data, day):
    """المناسبات المسجّلة في اليوم بترتيب ظهورها، بعدد خدماتها ومجنديها."""
    found = {}
    for assignment in peek_day(data, day):
        section = _section(assignment)
        if not is_event(section):
            continue
        item = found.setdefault(section, {"name": section, "posts": 0, "conscripts": 0})
        item["posts"] += 1
        item["conscripts"] += slot_count(assignment)
    return list(found.values())


def build(data, day, section):
    """DTO نقي لخط تشكيل مناسبة واحدة. ``LookupError`` لو المناسبة مش في اليوم."""
    section = " ".join(str(section or "").split())
    people = _people_index(data)
    posts, warnings = [], []
    for assignment in peek_day(data, day):
        if _section(assignment) != section or not is_event(section):
            continue
        row = _row(assignment, people, day)
        count = slot_count(assignment)
        name = row.get("name") or ""
        head = _head(row)
        if not head:
            warnings.append(f"الخدمة «{name}» من غير قائم بها.")
        if not int(assignment.get("conscript_count") or 0):
            warnings.append(f"الخدمة «{name}» عدد مجنديها مش مكتوب؛ اتحطت خانة فاضية.")
        posts.append({"name": name, "head": head, "count": count,
                      "weapons": _slot_weapons(assignment.get("weapon"), count),
                      "time": assignment.get("time") or "", "party": assignment.get("party") or ""})
    if not posts:
        raise LookupError(section)
    return {"day": day, "section": section, "posts": posts, "warnings": warnings,
            "totals": {"posts": len(posts), "conscripts": sum(post["count"] for post in posts)}}


def file_name(section):
    safe = re.sub(r'[\\/:*?"<>|]+', " ", section)
    return f"خط تشكيل {' '.join(safe.split())}.docx"

"""تصنيف أقسام الخدمات التي تظهر في كتل التصدير."""

from .constants import (
    SECTION_ADMIN_WORK, SECTION_BASIC, SECTION_GREAT, SECTION_INSPECTIONS,
    SECTION_NET, SECTION_OCCASIONAL, SECTION_OUTSIDERS, SECTION_PRISON,
    SECTION_RESTS, SECTION_SECURITY, SECTION_SUBCAMP, SECTION_TAQSEERA,
    SECTION_TARGETS,
)
from .text import norm


_STRUCTURAL = {
    SECTION_BASIC, SECTION_OCCASIONAL, SECTION_TARGETS, SECTION_PRISON,
    SECTION_SUBCAMP, SECTION_GREAT, SECTION_SECURITY, SECTION_ADMIN_WORK,
    SECTION_NET, SECTION_RESTS, SECTION_TAQSEERA, SECTION_OUTSIDERS,
    SECTION_INSPECTIONS,
}
_NORMAL_LABELS = {
    norm(value) for value in (
        "فرد + مج", "مج + فرد", "فرد", "مج", "فرد + مج (داخلي)",
        "فرد + مج (خارجي)", "مج + فرد (خارجي)", "تفتيشات",
        "سجن قوات الأمن", "سجن قوات الامن", "خدمات سجن قوات الأمن",
        "خدمات سجن قوات الامن",
    )
}


def is_special(section_name):
    """هل الاسم قسم مخصّص يستحق كتلة مستقلة في التصدير؟"""
    name = str(section_name or "").strip()
    return bool(name) and not is_structural(name) and norm(name) not in _NORMAL_LABELS


def is_structural(section_name):
    """هل الاسم قسم ثابت/محسوب لا يتعامل معه التصديران كقسم مخصّص؟"""
    return norm(str(section_name or "").strip()) in {norm(value) for value in _STRUCTURAL}


def block_title(section_name):
    name = str(section_name or "").strip()
    if name.startswith(("خدمات", "الخدمات")):
        return name
    return f"خدمات {name}"


def split_custom_sections(custom_sections, time_key):
    """يرجع (الأقسام العادية، الأقسام الخاصة) مع ترتيب ثابت داخل كل قسم."""
    ordinary = []
    special = []
    for section in custom_sections or []:
        rows = list(section.get("rows") or [])
        if is_special(section.get("name")):
            special.append({"name": section.get("name", ""),
                            "rows": sorted(enumerate(rows), key=lambda item: (time_key(item[1].get("time")), item[0]))})
        else:
            ordinary.extend(rows)
    return ordinary, [{"name": item["name"], "rows": [row for _index, row in item["rows"]]}
                      for item in special]

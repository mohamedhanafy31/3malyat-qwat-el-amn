"""أسماء الأشخاص في الملفات اليومية — نقطة تنسيق واحدة لكل المصدّرات."""
import re

from .constants import PERSONNEL_FAMILIES
from .text import norm


RANK_SHORT = {"ملازم أول": "م.اول", "ملازم": "ملازم"}


def first_words(name, n):
    """أول `n` كلمات، مع تجاهل التطويل والفراغات الزائدة."""
    cleaned = re.sub(r"ـ", "", str(name or ""))
    return " ".join(cleaned.split()[:n])


def personnel_rank_abbr(role):
    """اختصار رتبة الفرد حسب عائلة الرتبة."""
    normalized = norm(role)
    family = next((fam for fam in PERSONNEL_FAMILIES
                   if normalized.startswith(norm(fam))), "")
    return "م.ش" if family == "معاون" else "ا.ش"


def personnel_label(person):
    name = first_words(person.get("name"), 3)
    role = str(person.get("role") or "").strip()
    return f"{personnel_rank_abbr(role)}/ {name}" if role else name


def officer_label(officer, full=False):
    role = str(officer.get("role") or "").strip()
    rank = RANK_SHORT.get(role, role)
    name = officer.get("name") if full else (officer.get("short_name") or first_words(officer.get("name"), 2))
    name = re.sub(r"ـ", "", str(name or "")); name = " ".join(name.split())
    return f"{rank}/ {name}" if rank else name


def person_label(person, category):
    return officer_label(person) if category == "officers" else personnel_label(person)

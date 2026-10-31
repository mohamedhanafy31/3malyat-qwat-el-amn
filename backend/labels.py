"""أسماء الأشخاص في الملفات اليومية — نقطة تنسيق واحدة لكل المصدّرات."""
import re

from .constants import PERSONNEL_FAMILIES
from .text import norm


RANK_SHORT = {"ملازم أول": "م.اول", "ملازم": "ملازم"}


def _name_units(name, glue=True):
    """كلمات الاسم بعد ضم «عبد» لما بعدها (عبد العزيز اسم واحد): الأرشيف
    بيعد «محمد عبد العزيز» اسمين مش تلاتة (555 اسم ضابط في اللوحات)."""
    cleaned = re.sub(r"ـ", "", str(name or ""))
    words, units, i = cleaned.split(), [], 0
    while i < len(words):
        if glue and words[i] == "عبد" and i + 1 < len(words):
            units.append(f"{words[i]} {words[i + 1]}"); i += 2
        else:
            units.append(words[i]); i += 1
    return units


def first_words(name, n, glue=False):
    """أول `n` كلمات، مع تجاهل التطويل والفراغات الزائدة. `glue=True` بيعد
    «عبد X» اسم واحد (للضباط)؛ الأفراد بنفس العد القديم لأن الضم ماحسّنش
    مطابقتهم (26.6% بدون ضم و26.2% معاه على 8,523 اسم)."""
    return " ".join(_name_units(name, glue)[:n])


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
    name = officer.get("name") if full else (officer.get("short_name") or first_words(officer.get("name"), 2, glue=True))
    name = re.sub(r"ـ", "", str(name or "")); name = " ".join(name.split())
    return f"{rank}/ {name}" if rank else name


def person_label(person, category):
    return officer_label(person) if category == "officers" else personnel_label(person)

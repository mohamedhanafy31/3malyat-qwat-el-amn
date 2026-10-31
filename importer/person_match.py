"""حل أسماء الأرشيف لهويات القوة بأفضل محاولة محافظة."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from backend.text import norm_name

from .normalize import normalize_phones, normalize_rank
from .textnorm import clean_text

_RANK_PREFIX = re.compile(
    r"^\s*(?P<rank>لواء|عميد|عقيد|مقدم|رائد|رايد|نقيب|ملازم(?:\s+أ?ول)?|م\s*\.?\s*أ?ول|"
    r"م\s*\.?\s*ش|ا\s*\.?\s*ش|أ\s*\.?\s*ش|أمين(?:\s+شرطة)?|امين(?:\s+شرطه)?|"
    r"مساعد|معاون|رقيب|مندوب|عريف|شرطي|مجند|فرد)\s*[/\\.:-]*\s*",
    re.I,
)
_PHONE = re.compile(r"(?<!\d)0\s*1(?:[\s\-'\"“”«»()]|\d){9,18}(?!\d)")
_NOISE = {"سائق", "السائق", "قايم", "قائم", "بالخدمه", "بالخدمة"}


@dataclass(frozen=True)
class PersonMatch:
    person_id: str | None
    kind: str | None
    name: str
    confidence: str
    score: float
    margin: float
    reason: str
    candidates: tuple[str, ...] = ()


_RANK_ABBREV = {"اش": "أمين شرطة", "أش": "أمين شرطة", "مش": "مساعد شرطة",
                "امين": "أمين شرطة", "أمين": "أمين شرطة", "امينشرطه": "أمين شرطة",
                "أمينشرطة": "أمين شرطة", "مساعد": "مساعد شرطة", "معاون": "معاون شرطة"}


def _canonical_rank(raw: str) -> str:
    """الاختصار (ا.ش / م.ش) بيرجع لاسم الفئة؛ الفئة بتغطي درجاتها (ثان/ثالث/ممتاز…)."""
    compact = re.sub(r"[\s.]", "", raw or "")
    return _RANK_ABBREV.get(compact) or normalize_rank(raw)["value"]


def _rank_and_name(raw: str) -> tuple[str, str, tuple[str, ...]]:
    text = clean_text(raw)
    phones = tuple(normalize_phones(text)["value"])
    text = _PHONE.sub(" ", text)
    hit = _RANK_PREFIX.match(text)
    rank = _canonical_rank(hit.group("rank")) if hit else ""
    if hit:
        text = text[hit.end():]
    tokens = [token for token in norm_name(text).split() if token not in _NOISE and not token.isdigit()]
    return rank, " ".join(tokens), phones


def _person_tokens(value: str) -> list[str]:
    return norm_name(value).split()


def _on_force(person: dict[str, Any], day: str) -> bool:
    return not ((person.get("join_date") or "") > day
                or ((person.get("leave_date") or "") and day > person["leave_date"]))


def _people(data: dict[str, Any], role: str) -> Iterable[tuple[str, dict[str, Any]]]:
    if role == "officer":
        groups = (("officer", data.get("officers") or []),)
    elif role == "personnel":
        groups = (("personnel", data.get("personnel") or []),)
    else:
        groups = (("personnel", data.get("personnel") or []),
                  ("conscript", data.get("conscripts") or []))
    for kind, items in groups:
        for person in items:
            if isinstance(person, dict) and person.get("id") and person.get("name"):
                yield kind, person


# أسماء مؤكدة من المالك يدويًا (الاسم المكتوب في الأرشيف بعد التطبيع -> هوية).
# أي إضافة هنا لازم تكون بتأكيد صريح من المالك؛ الاسم بيتطابق كامل مش جزئي.
MANUAL_ALIASES: dict[str, str] = {
    norm_name("محمد فرنسا"): "IND-087",
}


def _is_subsequence(wanted: list[str], have: list[str]) -> bool:
    """كل كلمة مطلوبة موجودة كاملة وبنفس الترتيب في الاسم (تخطّي كلمات مسموح)."""
    position = 0
    for token in wanted:
        try:
            position = have.index(token, position) + 1
        except ValueError:
            return False
    return True


def _none(reason: str, candidates: tuple[str, ...] = (), score: float = 0.0) -> PersonMatch:
    return PersonMatch(None, None, "", "none", score, 0.0, reason, candidates)


def resolve_person(data: dict[str, Any], raw: str, day: str, *, role: str = "personnel",
                   service: str = "", neighbouring_ids: Iterable[str] = ()) -> PersonMatch:
    """ربط محافظ: تليفون مطابق، أو اسم مؤكد يدويًا، أو كل كلمات الاسم كاملة
    وبنفس الترتيب وأول كلمة هي الاسم الأول ومرشح واحد بس. أي شك -> فاضي.

    الاستمرارية (نفس الخدمة في يوم مجاور) والتشابه التقريبي والكنية مش بتربط.
    ``neighbouring_ids`` و``service`` بيتقبلوا للتوافق بس ومابيأثروش.
    """
    rank, wanted_name, phones = _rank_and_name(raw)
    wanted = _person_tokens(wanted_name)
    if not wanted and not phones:
        return _none("مفيش اسم أو تليفون صالح")
    pool = [(kind, person) for kind, person in _people(data, role) if _on_force(person, day)]
    if phones:
        hits = []
        for kind, person in pool:
            values = normalize_phones(" ".join([str(person.get("phone", "")),
                                                *map(str, person.get("other_phones") or [])]))["value"]
            if set(phones) & set(values):
                hits.append((kind, person))
        if len(hits) == 1:
            kind, person = hits[0]
            return PersonMatch(person["id"], kind, person["name"], "high", 1.0, 1.0, "تليفون مطابق بالظبط")
        if len(hits) > 1:
            return _none("تعادل: التليفون عند أكتر من شخص",
                         tuple(f"{p['id']} {p['name']}" for _, p in hits[:4]), 0.9)
    if not wanted:
        return _none("مفيش اسم صالح")
    alias_id = MANUAL_ALIASES.get(" ".join(wanted))
    if alias_id:
        for kind, person in pool:
            if person["id"] == alias_id:
                return PersonMatch(person["id"], kind, person["name"], "high", 1.0, 1.0,
                                   "اسم مؤكد يدويًا من المالك")
    if len(wanted) < 2:
        return _none("الاسم أقل من كلمتين")
    hits = []
    for kind, person in pool:
        have = _person_tokens(person["name"])
        if have and have[0] == wanted[0] and _is_subsequence(wanted, have):
            hits.append((kind, person))
    if len(hits) == 1:
        kind, person = hits[0]
        return PersonMatch(person["id"], kind, person["name"], "high", 1.0, 1.0,
                           "كل كلمات الاسم كاملة وبنفس الترتيب والاسم الأول مطابق ومرشح وحيد")
    if len(hits) > 1:
        return _none("تعادل: أكتر من شخص بنفس الاسم",
                     tuple(f"{p['id']} {p['name']}" for _, p in hits[:4]), 0.9)
    return _none("مفيش اسم مطابق بكلمات كاملة")

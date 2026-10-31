"""حل أسماء الأرشيف لهويات القوة بأفضل محاولة محافظة."""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Iterable

from backend.people import effective
from backend.text import norm, norm_name

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


def _rank_compatible(person_rank: str, wanted: str) -> bool:
    have, want = norm(normalize_rank(person_rank)["value"]), norm(wanted)
    return have == want or have.startswith(want + " ")


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


def _ordered_overlap(wanted: list[str], have: list[str]) -> tuple[float, float]:
    if not wanted or not have:
        return 0.0, 0.0
    used: set[int] = set()
    similarities: list[float] = []
    last = -1
    ordered = 0
    for token in wanted:
        choices = [(SequenceMatcher(None, token, other).ratio(), index)
                   for index, other in enumerate(have) if index not in used]
        score, index = max(choices, default=(0.0, -1))
        if score >= 0.55:
            used.add(index)
            similarities.append(score)
            if index > last:
                ordered += 1
                last = index
    overlap = len(similarities) / len(wanted)
    fuzzy = sum(similarities) / len(wanted) if similarities else 0.0
    order = ordered / len(wanted)
    return overlap * 0.55 + fuzzy * 0.3 + order * 0.15, fuzzy


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


def resolve_person(data: dict[str, Any], raw: str, day: str, *, role: str = "personnel",
                   service: str = "", neighbouring_ids: Iterable[str] = ()) -> PersonMatch:
    """يرجّع هوية لو فيه متصدر واضح، ويسيب التعادل الحقيقي فاضي."""
    rank, wanted_name, phones = _rank_and_name(raw)
    wanted = _person_tokens(wanted_name)
    if not wanted and not phones:
        return PersonMatch(None, None, "", "none", 0.0, 0.0, "مفيش اسم أو تليفون صالح")
    neighbours = set(neighbouring_ids)
    if len(wanted) < 2 and not phones and not neighbours:
        return PersonMatch(None, None, "", "none", 0.0, 0.0, "الاسم أقل من كلمتين")
    scored: list[tuple[float, str, str, dict[str, Any], list[str]]] = []
    for kind, person in _people(data, role):
        candidate_names = [person.get("name", ""), person.get("short_name", ""),
                           person.get("nickname", "")]
        candidate_names = [name for name in candidate_names if name]
        phone_values = normalize_phones(" ".join([str(person.get("phone", "")),
                                                   *map(str, person.get("other_phones") or [])]))["value"]
        if phones and set(phones) & set(phone_values):
            return PersonMatch(person["id"], kind, person["name"], "high", 1.0, 1.0,
                               "تليفون مطابق بالظبط")
        best_name, best_pair = "", (0.0, 0.0)
        for name in candidate_names:
            pair = _ordered_overlap(wanted, _person_tokens(name))
            if pair > best_pair:
                best_name, best_pair = name, pair
        name_score, fuzzy = best_pair
        reasons = [f"الاسم {name_score:.2f}"]
        score = name_score * 0.72
        if any(norm_name(name) == wanted_name for name in candidate_names):
            score += 0.18
            reasons.append("الاسم المسجل مطابق بالظبط")
        person_rank = person.get("role", "")
        if kind == "officer":
            try:
                person_rank = effective(person, day).get("role") or person_rank
            except (TypeError, ValueError):
                pass
        if rank:
            compatible = _rank_compatible(person_rank, rank)
            score += 0.14 if compatible else -0.10
            reasons.append("الرتبة مطابقة" if compatible else "الرتبة مختلفة")
        if _on_force(person, day):
            score += 0.07
            reasons.append("على القوة")
        if person["id"] in neighbours:
            score += 0.13
            reasons.append("نفس الخدمة في يوم مجاور")
        if best_name and best_name != person.get("name"):
            reasons.append("الاسم المختصر")
        scored.append((score, person["id"], kind, person, reasons))
    scored.sort(key=lambda item: (-item[0], item[1]))
    if not scored:
        return PersonMatch(None, None, "", "none", 0.0, 0.0, "مفيش مرشحين في الفئة")
    top = scored[0]
    runner = scored[1][0] if len(scored) > 1 else 0.0
    margin = top[0] - runner
    needed = 0.05 if rank and "الرتبة مختلفة" in top[4] else 0.015
    tied = len(scored) > 1 and margin < needed
    # المالك سمح بالتخمين، فالحد متواضع؛ التعادل بعد كل الإشارات فقط هو الممنوع.
    accepted = top[0] >= 0.55 and not tied
    candidates = tuple(f"{item[1]} {item[3]['name']} ({item[0]:.2f})" for item in scored[:4])
    if not accepted:
        reason = "تعادل بعد كل الإشارات" if tied else f"الأول مش متفوق بوضوح (الفارق {margin:.2f})"
        return PersonMatch(None, None, "", "none", top[0], margin, reason, candidates)
    confidence = "high" if top[0] >= 0.84 and margin >= 0.10 else "medium"
    reason = "، ".join(top[4]) + f"؛ الفارق {margin:.2f}"
    return PersonMatch(top[1], top[2], top[3]["name"], confidence, top[0], margin, reason, candidates)

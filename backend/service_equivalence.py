"""مفتاح مشترك لمقارنة أسماء الخدمات المكتوبة بصور مختلفة.

المفتاح للمطابقة فقط، ومابيغيّرش الاسم المخزّن أو المعروض.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .text import norm

_CLOCK = re.compile(r"(?:^|\s)\d{1,2}(?::\d{1,2})?\s*(?:ص|ظ|م|ليل)(?=\s|$)")
_COUNTER = re.compile(r"(?:^|\s)\d+(?=\s|$)")
_ALIASES = {
    "ميك": "مايك", "مايك": "مايك",
    "وطنى": "وطني", "وطني": "وطني",
    "قول": "قول", "القول": "قول",
}
# إضافة البند دي لا تغيّر هوية اللوري المركب.
_KNOWN_OPTIONAL_PREFIX_PARTS = {"افطار"}


def _word(word: str) -> str:
    word = _ALIASES.get(word, word)
    return word[2:] if word.startswith("ال") and len(word) > 4 else word


def service_parts(value: object) -> tuple[str, ...]:
    """الأجزاء المطبّعة، مرتبة داخليًا عشان ``+`` مجموعة مش ترتيب."""
    raw_parts = re.split(r"\s*\+\s*", str(value or ""))
    parts: list[str] = []
    for raw in raw_parts:
        text = _CLOCK.sub(" ", norm(raw))
        text = _COUNTER.sub(" ", text)
        words = [_word(word) for word in text.split()]
        key = " ".join(word for word in words if word)
        if key:
            parts.append(key)
    return tuple(sorted(set(parts)))


def service_key(value: object) -> str:
    return " + ".join(service_parts(value))


@dataclass(frozen=True)
class ServiceEquivalence:
    equivalent: bool
    relation: str
    left_key: str
    right_key: str
    extra_parts: tuple[str, ...] = ()


def compare_service_names(left: object, right: object) -> ServiceEquivalence:
    a, b = set(service_parts(left)), set(service_parts(right))
    left_key, right_key = service_key(left), service_key(right)
    if not a or not b:
        return ServiceEquivalence(False, "empty", left_key, right_key)
    if a == b:
        return ServiceEquivalence(True, "exact", left_key, right_key)
    small, large = (a, b) if len(a) < len(b) else (b, a)
    if small < large:
        extra = tuple(sorted(large - small))
        if set(extra) <= _KNOWN_OPTIONAL_PREFIX_PARTS:
            return ServiceEquivalence(True, "known-superset", left_key, right_key, extra)
        return ServiceEquivalence(False, "uncertain-superset", left_key, right_key, extra)
    return ServiceEquivalence(False, "different", left_key, right_key)


def services_equivalent(left: object, right: object) -> bool:
    return compare_service_names(left, right).equivalent

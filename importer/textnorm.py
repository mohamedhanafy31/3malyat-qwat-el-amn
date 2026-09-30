"""أدوات النص والتاريخ المشتركة مع مراحل الاستيراد."""

from __future__ import annotations

import datetime as dt
import re

from backend.text import norm, norm_name


_FORMAT_MARKS = dict.fromkeys(
    map(ord, "\u061c\u200b\u200c\u200d\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\ufeff"),
    None,
)
_DATE_RE = re.compile(
    r"(?<!\d)(\d{1,2})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{4})(?:\s*م)?(?!\d)"
)
WEEKDAYS = {
    "الاثنين": 0,
    "الإثنين": 0,
    "الثلاثاء": 1,
    "الأربعاء": 2,
    "الاربعاء": 2,
    "الخميس": 3,
    "الجمعة": 4,
    "السبت": 5,
    "الأحد": 6,
    "الاحد": 6,
}


def strip_format_marks(value: str | None) -> str:
    """إزالة علامات الاتجاه والتطويل مع إبقاء النص صالحًا للعرض."""
    return (value or "").translate(_FORMAT_MARKS).replace("ـ", "")


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", strip_format_marks(value)).strip()


def dates_in_text(value: str | None) -> list[dt.date]:
    found: list[dt.date] = []
    for match in _DATE_RE.finditer(strip_format_marks(value)):
        day, month, year = map(int, match.groups())
        try:
            parsed = dt.date(year, month, day)
        except ValueError:
            continue
        if parsed not in found:
            found.append(parsed)
    return found


def parse_date(value: str | None) -> dt.date | None:
    """قراءة D-M-YYYY وD/M/YYYY مع المسافات ولاحقة «م»."""
    dates = dates_in_text(value)
    return dates[0] if dates else None


def weekday_in_text(value: str | None) -> str | None:
    text = strip_format_marks(value)
    for name in WEEKDAYS:
        if name in text:
            return name
    return None


def weekday_matches(value: str | None, day: dt.date) -> bool | None:
    name = weekday_in_text(value)
    return None if name is None else WEEKDAYS[name] == day.weekday()


__all__ = [
    "WEEKDAYS", "clean_text", "dates_in_text", "norm", "norm_name",
    "parse_date", "strip_format_marks", "weekday_in_text", "weekday_matches",
]


"""بناء DTO مرتّب لورقة ملء خط التشكيل."""
from datetime import date
import re

from .afraad import basic_rows, occasional_rows
from .clocktime import format_time, parse_time
from .counts import build as build_counts
from .service_equivalence import services_equivalent
from .utils import weekday_name


def _date_title(day, shift):
    d = date.fromisoformat(day)
    label = "صباحي" if shift == "morning" else "ليلي"
    return f"خط تشكيل {label} عن يوم {weekday_name(day)} الموافق {d.day}/{d.month}/{d.year}م"


def _find_count(rows, name, block=None):
    for row in rows:
        if block is not None and row.get("block") != block:
            continue
        if services_equivalent(name, row.get("name")):
            return row
    return None


def _weapon_parts(value):
    """يفك سطر التسليح من غير ما يخترع نوع سلاح جديد."""
    text = " ".join(str(value or "").split())
    if not text:
        return []
    parts = re.split(r"\s*[+،]\s*|\s+و\s+", text)
    result = []
    for part in parts:
        part = " ".join(part.split())
        if part in {"الي", "الى"}:
            part = "آلي"
        if part:
            result.append(part)
    return result


def _slot_weapons(value, count):
    parts = _weapon_parts(value)
    if not parts or count <= 0:
        return [""] * max(0, count)
    return [parts[min(index, len(parts) - 1)] for index in range(count)]


def _block(name, count, weapon, kind, time=""):
    count = max(0, int(count or 0))
    return {"name": name or "", "title": name or "", "count": count,
            "weapons": _slot_weapons(weapon, count), "kind": kind, "time": time or ""}


def _basic_blocks(data, day, shift, counts_payload):
    source = counts_payload["basic_am" if shift == "morning" else "basic_pm"]
    enriched = basic_rows(data, day)
    blocks = []
    for count_row in source:
        match = next((row for row in enriched
                      if services_equivalent(count_row.get("name"), row.get("name"))), None)
        weapon = (match or {}).get("weapon") or count_row.get("weapon", "")
        blocks.append(_block(count_row.get("name", ""), count_row.get("count", 0),
                             weapon, "basic"))
    return blocks


def build(data, day, shift):
    """يرجع بيانات ورقة الملء من غير أي تعديل على ``data``."""
    if shift not in {"morning", "night"}:
        raise ValueError("الفترة لازم تكون morning أو night")
    counts_payload = build_counts(data, day)
    blocks = _basic_blocks(data, day, shift, counts_payload)
    warnings = []
    if shift == "morning":
        basic_names = [block["name"] for block in blocks]
        official = counts_payload.get("recurring") or []
        emergency = []
        for order, row in enumerate(occasional_rows(data, day)):
            if any(services_equivalent(row.get("name"), name) for name in basic_names):
                continue
            parsed = parse_time(row.get("time"))
            minutes = None
            if parsed is None:
                time = "بدون ميعاد"
                warnings.append(f"الخدمة «{row.get('name', '')}» بدون ميعاد؛ اتضافت في مجموعة بدون ميعاد.")
            else:
                minutes = int(parsed[:2]) * 60 + int(parsed[3:])
                if minutes >= 12 * 60:
                    continue
                time = format_time(parsed).replace(" ", "")
            count_row = _find_count(official, row.get("name"), "طوارئ")
            count = int((count_row or {}).get("count") if count_row else row.get("conscript_count") or 0)
            live_count = int(row.get("conscript_count") or 0)
            if count_row and live_count not in {0, count}:
                warnings.append(f"اختلاف عدد «{row.get('name', '')}»: اتاخد العدد الرسمي {count}.")
            emergency.append((minutes if minutes is not None else 9999, order,
                              _block(row.get("name", ""), count, row.get("weapon", ""),
                                     "emergency", time)))
        blocks.extend(block for _minutes, _order, block in sorted(emergency, key=lambda item: item[:2]))
    return {"title": _date_title(day, shift), "shift": shift, "day": day,
            "blocks": blocks,
            "totals": {"services": len(blocks),
                       "conscripts": sum(block["count"] for block in blocks)},
            "warnings": warnings}

"""بناء DTO مرتّب لورقة ملء خط التشكيل."""
from datetime import date
import re

from .afraad import occasional_rows
from .clocktime import format_time, parse_time
from .counts import build as build_counts
from .service_equivalence import services_equivalent
from .service_lines import line_for_service
from .service_links import service_for_counts_entry
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


def slot_count(row):
    """عدد خانات المجندين = خانة «عدد المجندين» في الخدمة. لو فاضية بنحط خانة
    فاضية واحدة عشان كل خدمة يبقى ليها مكان مجند في الخط."""
    return max(1, int(row.get("conscript_count") or 0))


def _block(name, count, weapon, kind, time=""):
    count = max(0, int(count or 0))
    return {"name": name or "", "title": name or "", "count": count,
            "weapons": _slot_weapons(weapon, count), "kind": kind, "time": time or ""}


def _lorry_of(data, count_row):
    """لوري الخدمة الأساسية = لوري خط السير اللي الخدمة عضو فيه ("" لو مفيش)."""
    service_id = service_for_counts_entry(data, count_row)
    line = line_for_service(data, service_id) if service_id else None
    return str((line or {}).get("lorry_id") or "")


def group_by_lorry(blocks):
    """يرصّ الخدمات اللي على نفس اللوري ورا بعض. كل لوري بيقعد مكان أول خدمة ليه
    في الترتيب الأصلي (والخدمات جواه بترتيبها الأصلي)، والخدمات من غير لوري
    بتفضل في مكانها. آخر صف في كل مجموعة لوري عليه ``lorry_end`` عشان الحد السميك."""
    order, groups = [], {}
    for block in blocks:
        lorry = block.get("lorry_id") or ""
        if not lorry:
            order.append([block])
        elif lorry in groups:
            groups[lorry].append(block)
        else:
            groups[lorry] = [block]
            order.append(groups[lorry])
    result = []
    for index, group in enumerate(order):
        lorry = group[0].get("lorry_id") or ""
        nxt = order[index + 1][0].get("lorry_id") if index + 1 < len(order) else None
        for position, block in enumerate(group):
            last = position == len(group) - 1
            # حد سميك بعد كل مجموعة لوري، وبعد الخدمة العادية اللي قبل مجموعة لوري.
            block["group_end"] = last and index + 1 < len(order) and bool(lorry or nxt)
            result.append(block)
    return result


def _basic_blocks(data, shift, counts_payload):
    """الخدمات الأساسية وعددها وتسليحها من «اعداد الخدمات» بس، كل فترة بصفها."""
    source = counts_payload["basic_am" if shift == "morning" else "basic_pm"]
    blocks = []
    for count_row in source:
        block = _block(count_row.get("name", ""), count_row.get("count", 0),
                       count_row.get("weapon", ""), "basic")
        block["lorry_id"] = _lorry_of(data, count_row)
        blocks.append(block)
    return group_by_lorry(blocks)


def build(data, day, shift):
    """يرجع بيانات ورقة الملء من غير أي تعديل على ``data``."""
    if shift not in {"morning", "night"}:
        raise ValueError("الفترة لازم تكون morning أو night")
    counts_payload = build_counts(data, day)
    blocks = _basic_blocks(data, shift, counts_payload)
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
                # الصبح من 4ص لحد قبل 12ظ؛ مواعيد الليل (12 ليل، 2ل…) مش من خط الصبح.
                if minutes >= 12 * 60 or minutes < 4 * 60:
                    continue
                time = format_time(parsed).replace(" ", "")
            count_row = _find_count(official, row.get("name"), "طوارئ")
            count = int((count_row or {}).get("count") or 0) if count_row else int(row.get("conscript_count") or 0)
            if count <= 0:
                warnings.append(f"الخدمة «{row.get('name', '')}» عدد مجنديها مش مكتوب؛ اتحطت خانة فاضية.")
                count = 1
            live_count = int(row.get("conscript_count") or 0)
            if count_row and live_count not in {0, count}:
                warnings.append(f"اختلاف عدد «{row.get('name', '')}»: اتاخد العدد الرسمي {count}.")
            emergency.append((minutes if minutes is not None else 9999, order,
                              _block(row.get("name", ""), count, row.get("weapon", ""),
                                     "emergency", time)))
        emergency_blocks = [block for _minutes, _order, block in sorted(emergency, key=lambda item: item[:2])]
        if emergency_blocks and blocks and blocks[-1].get("lorry_id"):
            blocks[-1]["group_end"] = True
        blocks.extend(emergency_blocks)
    return {"title": _date_title(day, shift), "shift": shift, "day": day,
            "blocks": blocks,
            "totals": {"services": len(blocks),
                       "conscripts": sum(block["count"] for block in blocks)},
            "warnings": warnings}

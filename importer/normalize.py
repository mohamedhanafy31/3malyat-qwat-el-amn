"""تطبيع حقول الأرشيف مع الإبقاء على النص المصدري."""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from backend.assignments import OFFICER_STATUSES
from backend.constants import LEAVE_TYPES, PERSONNEL_FAMILIES, RANK_ORDER, WEEKDAYS
from backend.utils import valid_phone

from .ledger import Ledger, atomic_write_jsonl
from .textnorm import clean_text, norm, norm_name


VERSION = "2"
_DASHES = {"", "-", "--", "---", "—", "ـ", "ــ", "ـــ"}
_RANKS = sorted(RANK_ORDER, key=len, reverse=True)
_GRADE_MARKER = re.compile(
    r"(?P<grade>(?:م\s*\.\s*[ِ]?\s*ش|م\s+ش|مش|ا\s*\.\s*ش|أ\s*\.\s*ش|ا\s+ش|اش|"
    r"أمين(?:\s+شرطة)?(?:\s+أول|ثان)?|امين(?:\s+شرطه)?(?:\s+اول|ثان)?|"
    r"معاون(?:\s+شرطة)?|مساعد(?:\s+شرطة)?|رقيب|مراقب|مندوب|عريف|شرطي))\s*[/\\-]",
    re.I,
)
_RANK_MARKER = re.compile(
    r"(?P<rank>لواء|عميد|عقيد|مقدم(?:\s+(?:طبيب|صيدلي))?|رائد|رايد|نقيب|"
    r"م\s*\.\s*أ?ول|م\s+اول|ملازم\s+أ?ول|ملازم)\s*[/\\-]",
    re.I,
)
_PHONE_CANDIDATE = re.compile(r"(?<!\d)0\s*1(?:[\s\-'\"“”«»()]|\d){9,18}(?!\d)")
_DATE = re.compile(r"(?<!\d)(\d{1,2})\s*/\s*(\d{1,2})(?:\s*/\s*(\d{2,4}))?(?!\d)")


def _value(raw: str | None, value: Any, **extra: Any) -> dict[str, Any]:
    return {"raw": raw or "", "value": value, **extra}


def normalize_rank(raw: str | None) -> dict[str, Any]:
    text = clean_text(raw)
    flat = norm(text).replace(" ", "")
    qualifier = ""
    if "طبيب" in norm(text):
        qualifier = "طبيب"
    elif "صيدلي" in norm(text):
        qualifier = "صيدلي"
    aliases = {
        "م.اول": "ملازم أول", "ماول": "ملازم أول", "ملازماول": "ملازم أول",
        "رايد": "رائد",
    }
    base = re.sub(r"(?:طبيب|صيدلي)", "", norm(text)).strip()
    compact = base.replace(" ", "")
    canonical = aliases.get(compact)
    if canonical is None:
        canonical = next((rank for rank in _RANKS if norm(rank) == base), clean_text(base))
    valid = canonical in RANK_ORDER
    return _value(text, canonical, qualifier=qualifier, valid=valid,
                  flags=[] if valid or not text else ["unknown_rank"])


def normalize_grade(raw: str | None) -> dict[str, Any]:
    text = clean_text(raw)
    flat = norm(text)
    compact = flat.replace(" ", "").replace(".", "")
    if re.match(r"^م[ِ]?ش", compact):
        canonical = "م.ش"
    elif re.match(r"^اش", compact):
        canonical = "ا.ش"
    else:
        canonical = next((family for family in PERSONNEL_FAMILIES
                          if flat.startswith(norm(family))), text)
    family = next((family for family in PERSONNEL_FAMILIES
                   if norm(canonical).startswith(norm(family))), "")
    # الاختصاران عائلتان معتمدتان في الأرشيف ولا يجوز تخمين توسعتهما.
    valid = bool(family or canonical in {"م.ش", "ا.ش"})
    return _value(text, canonical, family=family or canonical, valid=valid,
                  flags=[] if valid or not text else ["unknown_grade"])


def normalize_name(raw: str | None) -> dict[str, Any]:
    display = clean_text(raw)
    return _value(raw or "", display, key=norm_name(display))


def normalize_phones(raw: str | None) -> dict[str, Any]:
    text = raw or ""
    found: list[str] = []
    for match in _PHONE_CANDIDATE.finditer(text):
        phone = re.sub(r"\D", "", match.group())
        if re.fullmatch(r"01\d{9}", phone) and valid_phone(phone) and phone not in found:
            found.append(phone)
    return _value(text, found, flags=[] if found or not re.search(r"(?<!\d)0\s*1", text) else ["invalid_phone"])


def normalize_seniority(raw: str | None) -> dict[str, Any]:
    text = clean_text(raw)
    digits = re.findall(r"\d+", text)
    qualifier = ""
    if len(digits) >= 2:
        left, right = digits[0], digits[1]
        if len(left) == 4 and 1900 <= int(left) <= 2100 and not (len(right) == 4 and 1900 <= int(right) <= 2100):
            left, right = right, left
        canonical = f"{int(left)}/{right}"
        if len(digits) > 2:
            qualifier = "/" + "/".join(digits[2:])
    else:
        canonical = digits[0] if digits else ""
    return _value(text, canonical, qualifier=qualifier,
                  flags=[] if canonical or not text else ["invalid_seniority"])


def normalize_shift(raw: str | None) -> dict[str, Any]:
    text = clean_text(raw)
    flat = norm(text)
    values: list[str] = []
    if re.search(r"(?:^|\s)(?:ص|صبح)(?:\s|$)", flat) or "صباح" in flat:
        values.append("صباحية")
    if re.search(r"(?:^|\s)(?:ل|ليل)(?:\s|$)", flat) or "ليلي" in flat or "مساي" in flat:
        values.append("ليلية")
    return _value(text, values)


def normalize_time(raw: str | None) -> dict[str, Any]:
    text = clean_text(raw)
    values: list[str] = []
    for hour, minute, suffix in re.findall(r"(?<!\d)(\d{1,2})(?:\s*[:.]\s*(\d{1,2}))?\s*([صمظ])(?!\w)", text):
        value = f"{int(hour)}{':' + minute.zfill(2) if minute else ''}{suffix}"
        if value not in values:
            values.append(value)
    return _value(text, values)


def normalize_party(raw: str | None) -> dict[str, Any]:
    text = clean_text(raw)
    quoted = re.findall(r"[\"“”«]([^\"“”»«]+)[\"“”»]", text)
    values = [clean_text(value) for value in quoted if clean_text(value)]
    if not values:
        match = re.search(r"(?:ب|إلى|الى)\s*(استاد\s+[^+/,]+)", text)
        if match:
            values.append(clean_text(match.group(1)))
    return _value(text, values)


_CONSCRIPT_CLASSES = {
    "مجند": "مج", "مج": "مج", "وحده فض": "وحدة فض", "وحدة فض": "وحدة فض",
    "وحده": "وحدة", "وحدة": "وحدة", "خفيفه": "خفيفة", "خفيفة": "خفيفة",
    "طلبه": "طلبة", "طلبة": "طلبة", "حفظ نظام": "حفظ نظام", "رياضي": "رياضي",
    "فض": "فض", "سايق": "سائق", "فرد": "فرد",
}


def normalize_conscripts(raw: str | None) -> dict[str, Any]:
    text = clean_text(raw)
    flat = norm(text)
    entries: list[dict[str, Any]] = []
    flags: list[str] = []
    pattern = re.compile(r"(?:(\d+)\s*)?(وحده\s+فض|وحدة\s+فض|حفظ\s+نظام|مجند|مج|وحده|وحدة|خفيفه|خفيفة|طلبه|طلبة|رياضي|فض|سايق|فرد)")
    for count, kind in pattern.findall(flat):
        entries.append({"class": _CONSCRIPT_CLASSES[kind], "count": int(count or 1)})
    # العدد الكلي الصريح داخل القوسين أو مع كلمة مجند أولى من جمع الفئات.
    total_match = re.search(r"\(\s*(\d+)\s*مجند", flat)
    total = int(total_match.group(1)) if total_match else sum(item["count"] for item in entries)
    residue = pattern.sub(" ", flat)
    residue = re.sub(r"(?:الي|الى|خرطوش|في?درال|دونك|كلبش|بريتا|مايك\s*فض)", " ", residue)
    residue = re.sub(r"[\d+()\-/\sصبحلي]+", " ", residue).strip()
    if residue and any(ch.isalpha() for ch in residue) and (entries or re.search(r"\d", flat)):
        flags.append("unknown_conscript_class")
    return _value(text, entries, conscript_count=total, unknown_text=residue, flags=flags)


def normalize_weapons(raw: str | None) -> dict[str, Any]:
    text = clean_text(raw)
    flat = norm(text)
    aliases = [
        (r"(?:الي|الى)", "آلي"), (r"خرطوش", "خرطوش"),
        (r"في?\s*درال|فدرال", "فيدرال"), (r"دونك", "دونك"),
        (r"كلبش", "كلبش"), (r"مايك\s*فض", "مايك فض"),
        (r"بريتا", "بريتا"), (r"رياضي", "رياضي"), (r"(?<!مايك )فض", "فض"),
    ]
    hits: list[tuple[int, str]] = []
    covered = flat
    for pattern, canonical in aliases:
        for match in re.finditer(pattern, flat):
            hits.append((match.start(), canonical))
        covered = re.sub(pattern, " ", covered)
    tokens: list[str] = []
    for _, token in sorted(hits):
        if token not in tokens:
            tokens.append(token)
    residue = re.sub(r"[\d+()/\-,.\sعددقطعهو]", " ", covered).strip()
    flags = ["unknown_weapon"] if residue and any(ch.isalpha() for ch in residue) else []
    return _value(text, " + ".join(tokens), tokens=tokens, unknown_text=residue, flags=flags)


def _year_date(day: int, month: int, year: int | None, on_day: dt.date) -> dt.date | None:
    target_year = year or on_day.year
    if year is not None and year < 100:
        target_year += 2000
    try:
        result = dt.date(target_year, month, day)
    except ValueError:
        return None
    if year is None and on_day.month == 12 and month == 1:
        result = result.replace(year=on_day.year + 1)
    elif year is None and on_day.month == 1 and month == 12:
        result = result.replace(year=on_day.year - 1)
    return result


def _leave_type(text: str) -> str | None:
    flat = norm(text)
    rules = (("مصيف", "إجازة مصيف"), ("طاري", "إجازة طارئة"),
             ("مرضي", "مرضي"), ("مجمعه", "مجمعة"), ("فرقه", "راحة فرقة"),
             ("نصف شهر", "نصف شهرية"), ("شهري", "شهرية"), ("اسبوعي", "أسبوعية"))
    for needle, kind in rules:
        if needle in flat:
            return kind
    # «اجازة زواج/دورية/عيد» مالهاش نوع خاص في النظام: النوع العام «راحة» والنص الأصلي بيتحفظ في source
    return "راحة" if "راح" in flat or "اجاز" in flat else None


# «راحة خدمة» = راحة بعد خدمة ليلية، مش راحة من سجل الراحات — الوورد بيعدها تقصيرة في جدول الإجمالي
_SERVICE_REST_RE = re.compile(r"راحه\s*(?:بعد\s*)?(?:ال)?خدمه")


def parse_leave(raw: str | None, on_day: dt.date) -> dict[str, Any] | None:
    text = clean_text(raw)
    if _SERVICE_REST_RE.search(norm(text)):
        return None
    kind = _leave_type(text)
    if not kind or kind not in LEAVE_TYPES:
        return None
    counter = None
    match_counter = re.search(r"\(\s*(\d+)\s*/\s*(\d+)\s*\)", text)
    if match_counter:
        counter = {"current": int(match_counter.group(1)), "total": int(match_counter.group(2))}
    # «(4/7)» عدّاد (اليوم 4 من 7) مش تاريخ 4 يوليو — بيتشال قبل قراءة التواريخ
    date_text = text.replace(match_counter.group(0), " ") if match_counter else text
    dates = [_year_date(int(d), int(m), int(y) if y else None, on_day)
             for d, m, y in _DATE.findall(date_text)]
    dates = [value for value in dates if value]
    if not dates and counter and 1 <= counter["current"] <= counter["total"] <= 120:
        start = on_day - dt.timedelta(days=counter["current"] - 1)
        end = start + dt.timedelta(days=counter["total"] - 1)
        return {"raw": text, "type": kind, "start": start.isoformat(), "end": end.isoformat(),
                "return_date": (end + dt.timedelta(days=1)).isoformat(), "counter": counter}
    start = dates[0] if dates else on_day
    second = dates[1] if len(dates) > 1 else None
    flat = norm(text)
    if second and second < start:
        second = second.replace(year=second.year + 1)
    if second and "عوده" in flat:
        end, return_date = second - dt.timedelta(days=1), second
    elif second:
        end, return_date = second, second + dt.timedelta(days=1)
    else:
        end, return_date = start, start + dt.timedelta(days=1)
    return {"raw": text, "type": kind, "start": start.isoformat(), "end": max(start, end).isoformat(),
            "return_date": return_date.isoformat(), "counter": counter}


def normalize_officer_daily(raw: str | None, on_day: dt.date, post: str = "") -> dict[str, Any]:
    text = clean_text(raw)
    parts = [clean_text(part) for part in re.split(r"\+", text) if clean_text(part)]
    flat = norm(text)
    status = ""
    status_rules = (("غياب", "غياب"), ("انتداب", "انتداب"), ("مرضي", "مرضي"),
                    ("فرقه", "فرقة"), ("دوره", "فرقة"), ("طاري", "طارئة"))
    for needle, candidate in status_rules:
        if needle in flat:
            status = candidate
            break
    if status not in OFFICER_STATUSES:
        status = ""
    leaves = [leave for part in parts if (leave := parse_leave(part, on_day))]
    if "تقصير" not in flat:
        # «راحة خدمة» لوحدها الوورد بيعدها راحة؛ مع «+ تقصيرة» بيعدها تقصيرة (فمفيش راحة)
        for part in parts:
            if _SERVICE_REST_RE.search(norm(part)):
                leaves.append({"raw": part, "type": "راحة", "start": on_day.isoformat(), "end": on_day.isoformat(),
                               "return_date": (on_day + dt.timedelta(days=1)).isoformat(), "counter": None})
    leave_parts = {leave["raw"] for leave in leaves}
    service_parts = [part for part in parts if part not in leave_parts and "تقصير" not in norm(part)
                     and not _SERVICE_REST_RE.search(norm(part))
                     and not any(norm(key) in norm(part) for key in OFFICER_STATUSES)]
    return _value(text, text, parts=parts, taqseera="تقصير" in flat, status=status,
                  leaves=leaves, services=service_parts)


def normalize_rest(raw: str | None) -> dict[str, Any]:
    text = clean_text(raw)
    flat = norm(text)
    if text in _DASHES or not text:
        return _value(text, {"rest_system": "—", "rest_day": ""})
    for weekday in WEEKDAYS:
        if norm(weekday) == flat or (weekday == "الاثنين" and flat == "الاتنين"):
            return _value(text, {"rest_system": "أسبوعية", "rest_day": weekday})
    if "نصف شهر" in flat:
        system = "نصف شهرية"
    elif "شهري" in flat:
        system = "شهرية"
    elif "اسبوعي" in flat:
        system = "أسبوعية"
    else:
        system = "—"
    return _value(text, {"rest_system": system, "rest_day": ""},
                  flags=[] if system != "—" else ["unknown_rest_system"])


def name_compatible(left: str, right: str) -> bool:
    a, b = norm_name(left).split(), norm_name(right).split()
    if len(a) < 2 or len(b) < 2 or a[:2] != b[:2]:
        return False
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    index = 0
    for token in long:
        if index < len(short) and short[index] == token:
            index += 1
    return index == len(short)


def _person_chunks(text: str) -> list[dict[str, Any]]:
    markers = [(match.start(), match.end(), "officer", match.group("rank")) for match in _RANK_MARKER.finditer(text)]
    markers += [(match.start(), match.end(), "personnel", match.group("grade")) for match in _GRADE_MARKER.finditer(text)]
    markers.sort()
    result: list[dict[str, Any]] = []
    for index, (_, end, kind, marker) in enumerate(markers):
        stop = markers[index + 1][0] if index + 1 < len(markers) else len(text)
        chunk = text[end:stop]
        chunk = _PHONE_CANDIDATE.sub(" ", chunk)
        chunk = re.split(r"[+;\n]|\b(?:ومعه|برئاسة|مسلح)\b|\d+\s*(?:مج|مجند|فرد)", chunk, maxsplit=1)[0]
        # ما بعد هذه الكلمات وصف للخدمة أو للوقت وليس جزءًا من الاسم.
        chunk = re.split(r"[\"«»:]|\b(?:من|حتى|حتي|لحين|عقب|بعد|الساعة|الساعه|عند|رئاسة|رياضي)\b", chunk, maxsplit=1)[0]
        name = clean_text(chunk.strip(" /\\-:,.()\"'«»"))
        if not name or not re.search(r"[ء-ي]", name):
            continue
        item = {"kind": kind, "name": normalize_name(name)}
        item["rank" if kind == "officer" else "grade"] = normalize_rank(marker) if kind == "officer" else normalize_grade(marker)
        result.append(item)
    return result


def _normalized_record(record: dict[str, Any]) -> dict[str, Any]:
    result = dict(record)
    day = dt.date.fromisoformat(record["date"])
    normalized: dict[str, Any] = {}
    flags: list[str] = []
    kind, role = record["record_type"], record["role"]
    fields = record.get("fields", {})
    if kind in {"roster_row", "section"} and role == "roster":
        if fields:
            rank, name = fields.get("الرتبة", ""), fields.get("الاسم", "")
            code, post = fields.get("رقم الأقدمية", ""), fields.get("العمل المسند إليه", "")
            duty, rest = fields.get("التشغيل اليومي", ""), fields.get("الراحات", "")
        else:
            cells = record.get("raw_cells", [])
            rank, name = (cells + ["", "", ""])[1:3]
            code, post, duty, rest = "", (cells + [""] * 5)[3], (cells + [""] * 5)[4], ""
        normalized["officer"] = {"name": normalize_name(name), "rank": normalize_rank(rank),
                                 "seniority": normalize_seniority(code), "post": _value(post, clean_text(post)),
                                 "daily": normalize_officer_daily(duty, day, post), "rest": normalize_rest(rest)}
    elif kind == "ref_officers_row":
        normalized["officer"] = {"name": normalize_name(fields.get("الاسم", "")),
                                 "rank": normalize_rank(fields.get("الرتبة", "")),
                                 "seniority": normalize_seniority(fields.get("رقم الأقدمية", "")),
                                 "post": _value(fields.get("العمل المسند إليه", ""), clean_text(fields.get("العمل المسند إليه", ""))),
                                 "phones": normalize_phones(fields.get("رقم التلفون", "") or fields.get("رقم الهاتف", ""))}
    if kind in {"board_row", "old_officer_row", "duty_officer_row", "afraad_emergency_row"}:
        source = record.get("manning") or "\n".join(record.get("raw_cells", []))
        normalized["people"] = _person_chunks(source)
        normalized["phones"] = normalize_phones(source)
        if re.search(r"(?:مج|مجند|فرد|وحدة|وحده|خفيف|طلبة|طلبه|حفظ|رياضي|فض|سائق)", norm(source)):
            normalized["conscripts"] = normalize_conscripts(source)
        if kind == "afraad_emergency_row":
            normalized["weapons"] = normalize_weapons(record.get("fields", {}).get("weapon", ""))
    if kind == "afraad_basic_row":
        aligned = record.get("aligned", {})
        people: list[dict[str, Any]] = []
        for shift_key, shift in (("الخدمة الصباحية", "صباحية"), ("الخدمة الليلية", "ليلية")):
            cell = aligned.get(shift_key, "")
            phones = normalize_phones(cell)["value"]
            parsed = _person_chunks(cell)
            personnel = [item for item in parsed if item["kind"] == "personnel"]
            for index, item in enumerate(personnel):
                item["phones"] = _value(cell, phones[index:index + 1] if len(phones) == len(personnel) else phones)
                item["shift"] = shift
            people.extend(parsed)
        normalized.update({"people": people, "phones": normalize_phones("\n".join(aligned.values())),
                           "conscripts": normalize_conscripts(aligned.get("قوام الخدمة", "")),
                           "weapons": normalize_weapons(aligned.get("التسليح", "")),
                           "time": normalize_time(aligned.get("الانتظام", ""))})
    elif kind == "ref_personnel_row":
        cells = record.get("raw_cells", [])
        if len(cells) >= 3:
            grade = normalize_grade(cells[1])
            if grade["valid"]:
                normalized["people"] = [{"kind": "personnel", "grade": grade,
                                         "name": normalize_name(cells[2]),
                                         "phones": normalize_phones(" ".join(cells[3:]))}]
    text = record.get("label") or record.get("raw_text") or " ".join(record.get("raw_cells", []))
    normalized.setdefault("phones", normalize_phones(text))
    normalized.setdefault("shift", normalize_shift(text))
    normalized.setdefault("time", normalize_time(text))
    normalized.setdefault("party", normalize_party(text))
    for value in normalized.values():
        if isinstance(value, dict):
            flags.extend(value.get("flags", []))
    result["normalized"] = normalized
    result["flags"] = sorted(set(flags))
    return result


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def run_normalize(ledger: Ledger, state: dict[str, Any], start: dt.date | None = None,
                  end: dt.date | None = None, *, resume: bool = False) -> dict[str, Any]:
    output = ledger.staging_path("normalize")
    prior = state.get("stages", {}).get("normalize", {})
    if resume and prior.get("status") == "complete" and output.exists():
        return prior.get("checkpoint", {})
    source = ledger.staging_path("extract")
    if not source.exists():
        raise FileNotFoundError("يجب تشغيل extract للدفعة أولًا")
    ledger.mark_stage(state, "normalize", "running")
    records = _load_jsonl(source)
    if start:
        records = [record for record in records if record["date"] >= start.isoformat()]
    if end:
        records = [record for record in records if record["date"] <= end.isoformat()]
    normalized = [_normalized_record(record) for record in records]
    atomic_write_jsonl(output, normalized)
    flagged = sum(bool(record["flags"]) for record in normalized)
    checkpoint = {"records": len(normalized), "flagged_records": flagged, "version": VERSION}
    ledger.mark_stage(state, "normalize", "complete", checkpoint)
    return checkpoint


__all__ = [
    "VERSION", "name_compatible", "normalize_conscripts", "normalize_grade", "normalize_name",
    "normalize_officer_daily", "normalize_party", "normalize_phones", "normalize_rank",
    "normalize_rest", "normalize_seniority", "normalize_shift", "normalize_time",
    "normalize_weapons", "parse_leave", "run_normalize",
]

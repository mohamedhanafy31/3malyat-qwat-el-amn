"""مرحلة «فجوات الأرشيف»: بيانات الأرشيف اللي المستورد التاريخي ما التقطهاش.

التلات حاجات (كلها dry-run افتراضيًا، والكتابة في `migrations/023_import_archive_gaps.py`):

1. مدخلات «يومية انتظام الخدمات» (`<D>..docx`) -> `regularity_inputs[day]` في core:
   نص المدير/الوكيل الإضافي، مشرفي القول المكبر (صباحي/ليلي)، والملاحظات الحرة.
   اليوم بيتاخد من عنوان الملف «… الموافق D/M/YYYY» مش من اسم الفولدر/الملف
   (`10/22/21..docx` هو يوم 21، و`9/9/8..docx` نسخة مكررة من يوم 8).
2. نص «عمل بالإدارة» الحر لكل ضابط من اللوحة التفصيلية (`<D>.docx`) -> حالة الضابط
   `day_officers[day][id]["admin_work_text"]` (وبينقل `note` لو نفس النص).
3. تقسيم تغطية الهدف بالوقت (`مقدم / فلان حتى 4م + ت` ثم `مقدم / علان من 4م`) ->
   `periods` + `officer_ids` على صف الهدف في اليوم.

القواعد:
* واعي بالتعارض: أي حقل ليه قيمة مخزّنة مختلفة (دخلها مستخدم أو استيراد سابق)
  **مابيتلمسش** ويتطبع كتعارض. الحقول الفاضية بس هي اللي بتتملى.
* ممنوع التخمين: اسم ضابط مش بيتحل بشكل مؤكد / صف مش مفهوم -> قايمة `unresolved`.
* `apply=True` بيكتب على نسخة `data` في الذاكرة؛ الكتابة على القرص مسؤولية الهجرة.
"""

from __future__ import annotations

import datetime as dt
import re
import zipfile
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from backend.assignments import (MAX_PERIODS, clean_periods, officer_state, peek_day,
                                 set_periods, valid_periods)
from backend.clocktime import format_time, parse_time
from backend.constants import ROLE_DEPUTY, ROLE_DIRECTOR, SECTION_TARGETS
from backend.dated import command_on, targets_on
from backend.people import effective
from backend.repo import PeopleRepo
from backend.utils import MAX_LEN
from backend.service_equivalence import services_equivalent

from .extract import _extract_board, read_docx_raw
from .normalize import name_compatible, normalize_rank
from .textnorm import clean_text, dates_in_text, norm, norm_name
from .person_match import resolve_person

VERSION = "1"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
CATEGORIES = ("regularity", "admin_work", "split_target")
CATEGORY_LABELS = {"regularity": "مدخلات الانتظام", "admin_work": "عمل بالإدارة (نص حر)",
                   "split_target": "تقسيم الهدف بالوقت", "day_import": "استيراد يوم كامل"}
RANK_PREFIX = re.compile(r"^\s*(?P<rank>(?:ال)?(?:عقيد|مقدم|رائد|نقيب|عميد|لواء|م\s*\.?\s*[أا]ول|ملازم\s*[أا]ول))\s+")
STAT_LABELS = {"assignments": "تكليفات اليوم", "officer_states": "حالات ضباط", "officers_extended": "ضباط اتمد تاريخهم",
               "personnel_extended": "أفراد اتمد تاريخهم", "leaves_added": "راحات اتضافت في core",
               "leaves_skipped": "راحات موجودة بالفعل", "command_versions": "نسخ قيادة في command_history",
               "reference_versions": "نسخ قوايم مرجعية (الأهداف)"}
PHONE = re.compile(r"(?<!\d)(01\d{9})(?!\d)")
NOTE_MAX = MAX_LEN["note"]
MAX_NOTES = 12
DEFAULT_START = "2026-08-01"


# ───────────────────────── أدوات نص صغيرة ─────────────────────────

def collapse(value: Any) -> str:
    """مسافات متتالية/أسطر -> مسافة واحدة، من غير ما نغيّر الحروف."""
    return re.sub(r"\s+", " ", clean_text(str(value or ""))).strip()


def same_text(left: Any, right: Any) -> bool:
    """مقارنة نصين بعد التطبيع (همزات/تاء مربوطة/علامات ترقيم)."""
    return norm(str(left or "")) == norm(str(right or ""))


def _paragraphs(xml: bytes) -> list[str]:
    root = ET.fromstring(xml)
    return ["".join(t.text or "" for t in p.iter(W + "t")) for p in root.iter(W + "p")]


def _unique_cells(row) -> list[str]:
    """خلايا الصف المنطقية مرة واحدة (الدمج الأفقي بيكرر الخلية في python-docx)."""
    seen, out = set(), []
    for cell in row.cells:
        if cell._tc not in seen:
            seen.add(cell._tc)
            out.append(collapse(cell.text))
    return out


def _blank(value: str) -> bool:
    return not value or not re.search(r"[\w؀-ۿ]", value)


# ───────────────────────── اكتشاف الملفات ─────────────────────────

REG_NAME = re.compile(r"(\d+)\.\.docx")
BOARD_NAME = re.compile(r"(\d+)\.docx")


def header_day(path: Path) -> str | None:
    """اليوم من عنوان الملف «… الموافق D/M/YYYY» (header ثم أول فقرات الجسم)."""
    try:
        with zipfile.ZipFile(path) as package:
            lines: list[str] = []
            for name in sorted(package.namelist()):
                if name.startswith("word/header"):
                    lines += _paragraphs(package.read(name))
            lines += _paragraphs(package.read("word/document.xml"))[:6]
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError):
        return None
    text = " ".join(lines)
    hit = re.search(r"الموافق\s*(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4})", text)
    candidates = ([dt.date(int(hit[3]), int(hit[2]), int(hit[1]))] if hit else dates_in_text(text))
    for found in candidates:
        return found.isoformat()
    return None


def discover_regularity(archive_root: Path, start: str = DEFAULT_START,
                        end: str | None = None) -> tuple[dict[str, Path], list[dict[str, Any]]]:
    """-> (ملف الانتظام لكل يوم، ملاحظات: مكرر / من غير تاريخ في العنوان).

    اليوم من العنوان. لو نفس اليوم في ملفين، نسخة فولدرها هو يومها (شهر/يوم) أولى."""
    found: dict[str, list[Path]] = defaultdict(list)
    notes: list[dict[str, Any]] = []
    for path in sorted(archive_root.glob("*/*/*..docx")):
        if path.name.startswith("~") or not REG_NAME.fullmatch(path.name):
            continue
        day = header_day(path)
        if not day:
            try:                         # ملف من غير تاريخ في العنوان: نبلّغ بس لو فولدره جوه النطاق
                folder = dt.date(2026, int(path.parent.parent.name), int(path.parent.name)).isoformat()
            except ValueError:
                folder = ""
            if folder and folder >= start and not (end and folder > end):
                notes.append({"path": str(path), "reason": "no-header-date"})
            continue
        if day < start or (end and day > end):
            continue
        found[day].append(path)
    chosen: dict[str, Path] = {}
    for day, paths in sorted(found.items()):
        want = (str(int(day[5:7])), str(int(day[8:])))

        def rank(path: Path) -> tuple[int, str]:
            own = (path.parent.parent.name, path.parent.name) == want
            return (0 if own else 1, str(path))
        ordered = sorted(paths, key=rank)
        chosen[day] = ordered[0]
        for duplicate in ordered[1:]:
            notes.append({"path": str(duplicate), "reason": "duplicate", "day": day, "chosen": str(ordered[0])})
    return chosen, notes


def discover_boards(archive_root: Path, start: str = DEFAULT_START,
                    end: str | None = None) -> dict[str, Path]:
    """اللوحة التفصيلية `<D>.docx` لكل يوم (الشهر من الفولدر، واليوم من رقم الملف)."""
    chosen: dict[str, Path] = {}
    for path in sorted(archive_root.glob("*/*/*.docx")):
        if path.name.startswith("~") or not BOARD_NAME.fullmatch(path.name):
            continue
        try:
            day = dt.date(int(archive_root.name) if archive_root.name.isdigit() else 2026,
                          int(path.parent.parent.name), int(path.stem)).isoformat()
        except ValueError:
            continue
        if day < start or (end and day > end):
            continue
        better = day not in chosen or (path.parent.name == path.stem and chosen[day].parent.name != path.stem)
        if better:
            chosen[day] = path
    return dict(sorted(chosen.items()))


# ───────────────────────── استخراج يومية الانتظام ─────────────────────────

def split_person(text: str) -> tuple[str, str, str]:
    """«رائد / محمد ميهوب (0111…)» -> (الرتبة، الاسم، التليفون)."""
    text = collapse(text)
    phone = PHONE.search(text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")))
    phone_text = phone.group(1) if phone else ""
    text = PHONE.sub(" ", text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")))
    text = re.sub(r"\(\s*\)", " ", text)
    rank = ""
    if "/" in text and len(text.split("/", 1)[0].split()) <= 3:
        rank, text = (part.strip() for part in text.split("/", 1))
    # الرتبة ساعات بتيجي بعد الشرطة («/ مقدم طاهر سلطان») أو من غير شرطة خالص
    lead = RANK_PREFIX.match(text)
    if lead and (not rank or lead.group("rank")):
        rank = rank or lead.group("rank")
        text = text[lead.end():]
    return rank, collapse(text.strip(" ()-:،")), phone_text


def extract_regularity(path: Path) -> dict[str, Any]:
    """صفوف الضباط والملاحظات من جدول يومية الانتظام الثاني (خام، من غير بيانات النظام)."""
    from docx import Document

    try:
        document = Document(path)
    except Exception as exc:  # ملف تالف بيعزل نفسه
        return {"path": str(path), "error": f"{type(exc).__name__}: {exc}", "officers": [], "notes": []}
    table = None
    for candidate in document.tables:
        head = norm(" ".join(_unique_cells(candidate.rows[0]))) if candidate.rows else ""
        if "رتب" in head and "خدم" in head and "قايم" not in head:
            table = candidate
            break
    if table is None:
        return {"path": str(path), "error": "no-officers-table", "officers": [], "notes": []}
    officers, notes = [], []
    for index, row in enumerate(table.rows[1:], 1):
        parts = _unique_cells(row)
        body = parts[1:] if len(parts) > 1 else []
        filled = [part for part in body if not _blank(part)]
        if not filled:
            continue
        if len(filled) == 1:
            notes.append(filled[0])
        elif len(body) >= 3 and not any(_blank(part) for part in body[:3]):
            rank, name, phone = split_person(body[1])
            officers.append({"row": index, "rank": collapse(body[0]), "name": name or collapse(body[1]),
                             "phone": phone, "service": collapse(body[2]),
                             "raw_name": collapse(body[1])})
        else:
            notes.append(collapse(" ".join(filled)))     # صف مش بالشكل المعتاد: ملاحظة بنصه
    return {"path": str(path), "error": None, "officers": officers, "notes": notes}


# ───────────────────────── مطابقة الضباط ─────────────────────────

class OfficerIndex:
    """ضباط القوة في اليوم، بمطابقة الاسم المختصر (أول اسمين) وبالرتبة لفك التعادل."""

    def __init__(self, data: dict[str, Any], day: str) -> None:
        self.data, self.day = data, day
        self.items: list[dict[str, Any]] = []
        for raw in PeopleRepo(data).raw_on_force(day, "officers"):
            eff = {**raw, **effective(raw, day)}
            self.items.append({
                "id": raw["id"], "name": raw.get("name", ""),
                "short": norm_name(raw.get("short_name") or "").split(),
                "full": norm_name(raw.get("name") or "").split(),
                "rank": normalize_rank(eff.get("role", ""))["value"],
                "label": f"{eff.get('role', '')} / {raw.get('short_name') or raw.get('name', '')}"})

    def resolve(self, name: str, rank: str = "", only: set[str] | None = None) -> dict[str, Any]:
        """-> {status: ok|none|ambiguous, id?, label?}."""
        tokens = norm_name(name).split()
        if len(tokens) < 2:
            return {"status": "none"}
        hits = []
        for item in self.items:
            if only is not None and item["id"] not in only:
                continue
            if item["short"] and item["short"] == tokens:
                hits.append(item)
            elif item["full"][:len(tokens)] == tokens or name_compatible(" ".join(tokens), " ".join(item["full"])):
                hits.append(item)
        if len(hits) > 1 and rank:
            wanted = normalize_rank(rank)["value"]
            narrowed = [item for item in hits if item["rank"] == wanted]
            hits = narrowed or hits
        if len(hits) > 1:
            exact = [item for item in hits if item["short"] == tokens]
            hits = exact or hits
        if not hits:
            return {"status": "none"}
        if len(hits) > 1:
            return {"status": "ambiguous", "candidates": [item["id"] for item in hits]}
        return {"status": "ok", "id": hits[0]["id"], "label": hits[0]["label"]}

    def label(self, officer_id: str) -> str:
        return next((item["label"] for item in self.items if item["id"] == officer_id), officer_id)


# ───────────────────────── خطة اليوم ─────────────────────────

@dataclass
class Op:
    """حقل واحد: الفئة + اليوم + مفتاح (ضابط/هدف) + القيمة المقترحة وحالتها."""
    category: str
    day: str
    key: str
    label: str
    value: Any
    archive: str = ""
    status: str = ""             # add | same | conflict
    current: Any = None
    detail: str = ""
    overrides_inherited: bool = False


@dataclass
class DayGaps:
    day: str
    sources: dict[str, str] = field(default_factory=dict)
    origin: str = ""                         # imported:<batch> | system | missing
    ops: list[Op] = field(default_factory=list)
    unresolved: list[dict[str, Any]] = field(default_factory=list)
    user_touched: list[str] = field(default_factory=list)
    skipped_basic: int = 0

    def unresolve(self, category: str, row: str, reason: str, **extra: Any) -> None:
        self.unresolved.append({"category": category, "row": row, "reason": reason, **extra})

    def by(self, category: str, status: str) -> list[Op]:
        return [op for op in self.ops if op.category == category and op.status == status]


def day_origin(data: dict[str, Any], day: str) -> str:
    marker = (data.get("day_import") or {}).get(day)
    if marker:
        return f"imported:{marker.get('batch', '')}"
    has = any((data.get(key) or {}).get(day) for key in ("day_assignments", "day_officers"))
    return "system" if has else "missing"


def user_entries(data: dict[str, Any], day: str, entities: tuple[str, ...],
                 entity_id: str | None = None) -> list[dict[str, Any]]:
    """سطور change_log اللي تخص اليوم ده وطالعة من مستخدم (مش من استيراد النظام)."""
    out = []
    for entry in data.get("change_log") or []:
        entity = str(entry.get("entity") or "")
        if entity == "import" or entity not in entities:
            continue
        if entity_id is not None and entry.get("entity_id") not in (entity_id, day):
            continue
        reason, text = str(entry.get("reason") or ""), str(entry.get("text") or "")
        if entry.get("day") == day or entry.get("entity_id") == day or day in reason or day in text:
            out.append(entry)
    return out


def _entry_label(entry: dict[str, Any]) -> str:
    return f"{entry.get('id')} {entry.get('ts')} {entry.get('edited_by') or ''}".strip()


def _field_cleared_by_user(entries: list[dict[str, Any]], key: str) -> bool:
    """آخر تعديل مستخدم فضّى الحقل ده عن قصد (before فيه قيمة وafter فاضي)؟"""
    for entry in reversed(entries):
        before, after = entry.get("before"), entry.get("after")
        if isinstance(after, dict) and key in after:
            return not after.get(key) and isinstance(before, dict) and bool(before.get(key))
    return False


# ───────────────────────── 1) مدخلات الانتظام ─────────────────────────

SUPERVISION = re.compile(
    r"^\s*المتابعة\s+(?:ال[اأإ]شرافية)(?:\s+الميدانية)?(?:\s+(?:على|علي))?(?:\s+جميع)?(?:\s+خدمات)?"
    r"(?:\s+(?:[اأإ]دارة\s+)?قوات\s+(?:ال[اأ]من))?")
BASIC_TEXT = re.compile(r"فترة\s+(?:صباحية|ليلية|مسائية)|ارتكاز|تدخل\s+سريع|كنترول")
BIG_COLUMN = re.compile(r"مشرف\s+القول\s+المكبر")


def _supervision_extra(text: str) -> str | None:
    """نص المتابعة الإشرافية -> الإضافي بعد «+»؛ None لو الصف مش متابعة إشرافية."""
    hit = SUPERVISION.match(text)
    if not hit:
        return None
    return collapse(re.sub(r"^[\s+/\-:]+", "", text[hit.end():]))


def _same_supervisor(current: Any, new: dict[str, str]) -> bool:
    return (isinstance(current, dict) and same_text(current.get("name"), new["name"])
            and same_text(current.get("rank"), new["rank"])
            and re.sub(r"\D", "", str(current.get("phone") or "")) == re.sub(r"\D", "", new["phone"]))


def plan_regularity(data: dict[str, Any], day: str, sheet: dict[str, Any], apply: bool = False,
                    baseline: dict[str, Any] | None = None) -> DayGaps:
    """يحوّل صفوف ملف الانتظام لمدخلات `regularity_inputs[day]` ويصنّفها add/same/conflict."""
    gaps = DayGaps(day, {"regularity": sheet.get("path", "")}, day_origin(data, day))
    index = OfficerIndex(data, day)
    command = command_on(data, day)
    command_ids = {role: ident for role, ident in command.items() if ident}
    wanted_extra: dict[str, tuple[str, str]] = {}
    wanted_big: dict[str, dict[str, str]] = {}
    for item in sheet.get("officers") or []:
        service, row = item["service"], f"{item['rank']} / {item['name']}"
        found = index.resolve(item["name"], item["rank"], only=set(command_ids.values()) or None)
        command_hit = found["id"] if found["status"] == "ok" else None
        big = BIG_COLUMN.search(service)
        if big:
            shift = "pm" if re.search(r"ليلية|مسائية", service) else "am" if "صباحية" in service else None
            if shift is None:
                gaps.unresolve("regularity", row, "مشرف القول المكبر من غير فترة واضحة", archive=service)
                continue
            if shift in wanted_big:
                gaps.unresolve("regularity", row, f"مشرف قول مكبر مكرر لنفس الفترة ({shift})", archive=service)
                continue
            person = {"rank": item["rank"], "name": item["name"], "phone": item["phone"]}
            if (len(person["name"]) > MAX_LEN["name"] or len(person["phone"]) > MAX_LEN["phone"]
                    or not person["name"]):
                gaps.unresolve("regularity", row, "بيانات مشرف القول المكبر مش صالحة (فاضي/أطول من الحد)")
                continue
            wanted_big[shift] = person
            continue
        extra = _supervision_extra(service)
        if command_hit:
            text = extra if extra is not None else (None if BASIC_TEXT.search(service) else service)
            if text is None:
                gaps.skipped_basic += 1
                continue
            if not text:
                continue
            if len(text) > NOTE_MAX:
                gaps.unresolve("regularity", row, f"نص الضابط أطول من {NOTE_MAX} حرف", archive=service)
                continue
            if command_hit in wanted_extra:
                gaps.unresolve("regularity", row, "أكتر من صف لنفس المدير/الوكيل", archive=service)
                continue
            wanted_extra[command_hit] = (text, service)
            continue
        if extra is not None:
            reason = ("المتابعة الإشرافية لضابط مش مدير/وكيل اليوم" if found["status"] == "none"
                      else "اسم ضابط المتابعة الإشرافية غامض")
            gaps.unresolve("regularity", row, reason, archive=service)
        elif BASIC_TEXT.search(service):
            gaps.skipped_basic += 1          # صف مشتق من اللوحة، مش مدخل
        else:
            gaps.unresolve("regularity", row, "صف ضابط مش مدير/وكيل ولا مشرف قول مكبر ولا خدمة أساسية", archive=service)

    notes = []
    for text in sheet.get("notes") or []:
        text = collapse(text)
        if text:
            notes.append(text)
    notes_ok = True
    if len(notes) > MAX_NOTES:
        gaps.unresolve("regularity", "الملاحظات", f"{len(notes)} ملاحظة (الحد {MAX_NOTES})")
        notes_ok = False
    if any(len(text) > NOTE_MAX for text in notes):
        gaps.unresolve("regularity", "الملاحظات", f"ملاحظة أطول من {NOTE_MAX} حرف")
        notes_ok = False

    # `baseline` = المخزّن قبل أي كتابة من التشغيل ده، عشان الوراثة تتقاس على الحقيقي مش على اللي لسه بنضيفه
    entries = baseline if baseline is not None else (data.get("regularity_inputs") or {})
    own = (data.get("regularity_inputs") or {}).get(day)
    own = own if isinstance(own, dict) else None
    touched = user_entries(data, day, ("regularity_inputs",), day)
    gaps.user_touched = [_entry_label(entry) for entry in touched]
    reset = bool(touched) and touched[-1].get("action") == "reset"
    previous = max((key for key, value in entries.items() if isinstance(value, dict) and key < day), default=None)
    inherited = entries.get(previous) if previous else None

    def add(key: str, label: str, value: Any, archive: str, current: Any, same: bool, inherited_value: Any) -> None:
        op = Op("regularity", day, key, label, value, archive, current=current)
        if current in (None, "", {}, []):
            op.status = "add"
            op.overrides_inherited = bool(inherited_value not in (None, "", {}, []) and inherited_value != value)
            if reset:
                op.status, op.detail = "conflict", "المستخدم استرجع التوريث لليوم ده (reset في change_log)"
        else:
            op.status = "same" if same else "conflict"
        gaps.ops.append(op)

    own = own or {}
    inh = inherited or {}
    for officer_id, (text, archive) in sorted(wanted_extra.items()):
        current = (own.get("officer_extra") or {}).get(officer_id)
        add(f"officer_extra:{officer_id}", index.label(officer_id), text, archive, current,
            same_text(current, text), (inh.get("officer_extra") or {}).get(officer_id))
    for shift, person in sorted(wanted_big.items()):
        current = (own.get("big_column_supervisors") or {}).get(shift)
        shown = " ".join(filter(None, [person["rank"], person["name"], person["phone"]]))
        add(f"big_column:{shift}", "مشرف القول المكبر " + ("صباحي" if shift == "am" else "ليلي"), person, shown,
            current, _same_supervisor(current, person), (inh.get("big_column_supervisors") or {}).get(shift))
    if notes and notes_ok:
        current = own.get("notes")
        add("notes", "الملاحظات", notes, " ؛ ".join(notes), current,
            [norm(n) for n in (current or [])] == [norm(n) for n in notes], inh.get("notes"))

    if apply:
        additions = [op for op in gaps.ops if op.status == "add"]
        if additions:
            entry = data.setdefault("regularity_inputs", {}).setdefault(day, {})
            entry.setdefault("officer_extra", {})
            entry.setdefault("big_column_supervisors", {})
            for op in additions:
                kind, _, key = op.key.partition(":")
                if kind == "officer_extra":
                    entry["officer_extra"][key] = op.value
                elif kind == "big_column":
                    entry["big_column_supervisors"][key] = dict(op.value)
                else:
                    entry["notes"] = list(op.value)
    return gaps


# ───────────────────────── استخراج اللوحة التفصيلية ─────────────────────────

BOARD_SECTIONS = {
    "الخدمات الاساسيه": "basic", "خدمات الاساسيه": "basic",
    "الخدمات الطاريه": "emergency", "الطواري": "emergency",
    "الاهداف": "targets", "معسكر فرعي": "subcamp",
    "المعسكر الفرعي": "subcamp", "ضابط عظيم وامن المعسكر الفرعي": "subcamp",
    "ضابط عظيم الاداره": "great", "ضابط الامن بالاداره": "security",
    "ضابط الامن": "security", "خدمات سجن قوات الامن": "prison",
    "خدمات السجن": "prison", "عمل بالاداره": "admin_work",
    "الخوارج": "outsiders", "الراحات": "rests", "تقصيره": "rests",
}
RANK_WORDS = re.compile(r"(?:^| )(?:عقيد|مقدم|رايد|نقيب|عميد|لواء|م\s*(?:اول)|ملازم|م\s*ش|ا\s*ش|رقيب|مساعد|مندوب)(?: |$)")


def _section_of(label: str) -> str | None:
    key = norm(label)
    for heading, section in BOARD_SECTIONS.items():
        if norm(heading) in key:
            return section
    return None


def looks_person(value: str) -> bool:
    return bool(RANK_WORDS.search(norm(value)))


def extract_board_sections(path: Path) -> dict[str, list[dict[str, Any]]]:
    """أقسام اللوحة التفصيلية -> صفوف {service, value, type, row_index, half} (نفس منطق
    `tools/compare_dailies._board_rows`: نصفي الشبكة منفصلين، والسطر المنفرد باسم ضابط
    تحت هدف = تغطية تانية لنفس الهدف)."""
    records = _extract_board({"date": "", "role": "board", "path": "memory"}, read_docx_raw(path))
    sections: dict[str, list[dict[str, Any]]] = defaultdict(list)
    current = {0: "basic", 1: "emergency"}
    previous_service: dict[int, str] = {}
    header = next((r for r in records if r.get("record_type") == "header"), {})
    for half, label in enumerate(header.get("half_labels") or []):
        current[half] = _section_of(label) or current.get(half, "emergency")
    for record in records:
        kind = record.get("record_type")
        if kind not in {"board_row", "board_label"}:
            continue
        half = int(record.get("half") or 0)
        label, value = collapse(record.get("label")), collapse(record.get("manning"))
        extras = [collapse(x) for x in record.get("extra_cells") or [] if collapse(x)]
        heading = _section_of(label)
        if heading and not value:
            current[half] = heading
            previous_service.pop(half, None)
            continue
        section = current.get(half, "basic" if half == 0 else "emergency")
        if section == "targets":
            if kind == "board_label" and looks_person(label) and previous_service.get(half):
                sections[section].append({"service": previous_service[half], "value": label, "type": kind,
                                          "row_index": record.get("row_index"), "half": half, "cont": True})
                continue
            if label and kind == "board_row":
                previous_service[half] = label
                sections[section].append({"service": label, "value": value, "type": kind,
                                          "row_index": record.get("row_index"), "half": half})
            continue
        if section == "admin_work":
            if not (looks_person(label) or "/" in label):
                if value and not heading:
                    sections[section].append({"service": label, "value": value, "type": kind, "orphan": True,
                                              "row_index": record.get("row_index"), "half": half})
                continue
            text = " ".join(part for part in [value, *extras] if part)
            sections[section].append({"service": label, "value": text, "type": kind,
                                      "row_index": record.get("row_index"), "half": half})
    return dict(sections)


# ───────────────────────── 2) عمل بالإدارة ─────────────────────────

AUTOMATIC_LABELS = {norm(ROLE_DIRECTOR), norm(ROLE_DEPUTY), norm("مدير الادارة"), norm("وكيل الادارة")}


def plan_admin_work(data: dict[str, Any], day: str, sections: dict[str, list[dict[str, Any]]],
                    source: str = "", apply: bool = False) -> DayGaps:
    gaps = DayGaps(day, {"board": source}, day_origin(data, day))
    if not peek_day(data, day) and sections.get("admin_work"):
        gaps.unresolve("admin_work", "اليوم كله", "اليوم من غير تكليفات لوحة مخزّنة — مرشّح للاستيراد الكامل مش لإضافة نص")
        return gaps
    index = OfficerIndex(data, day)
    command_ids = {ident for ident in command_on(data, day).values() if ident}
    states = (data.get("day_officers") or {}).get(day) or {}
    seen: dict[str, str] = {}
    for item in sections.get("admin_work") or []:
        if item.get("orphan"):
            gaps.unresolve("admin_work", item["service"], "نص عمل بالإدارة من غير ضابط محدد", archive=item["value"])
            continue
        rank, name, _phone = split_person(item["service"])
        text = collapse(item["value"])
        if not text:
            continue
        found = index.resolve(name, rank)
        row = f"{rank} / {name}"
        if found["status"] != "ok":
            gaps.unresolve("admin_work", row, "ضابط مش على القوة أو الاسم غامض" if found["status"] == "none"
                           else "اسم الضابط مطابق لأكتر من ضابط", archive=text)
            continue
        officer_id = found["id"]
        if officer_id in command_ids and norm(text) in AUTOMATIC_LABELS:
            continue                      # نص المنصب التلقائي، مفيش حاجة تتضاف
        if len(text) > NOTE_MAX:
            gaps.unresolve("admin_work", row, f"النص أطول من {NOTE_MAX} حرف", archive=text)
            continue
        if officer_id in seen:
            gaps.unresolve("admin_work", row, "الضابط ظاهر مرتين في عمل بالإدارة", archive=text)
            continue
        seen[officer_id] = text
        state = states.get(officer_id) or {}
        current = state.get("admin_work_text") or ""
        op = Op("admin_work", day, officer_id, found["label"], text, text, current=current)
        touched = user_entries(data, day, ("officer_state",), officer_id)
        if current:
            op.status = "same" if same_text(current, text) else "conflict"
            if op.status == "same":
                holder = next((k for k in ("note", "extra") if same_text(state.get(k), text)), None)
                if holder:
                    op.status, op.detail, op.current = "add", f"نقل المكرر من {holder}", current
                    op.current = current
        elif touched and _field_cleared_by_user(touched, "admin_work_text"):
            op.status, op.detail = "conflict", "المستخدم فضّى النص عن قصد (change_log)"
        else:
            op.status = "add"
            holder = next((k for k in ("note", "extra") if same_text(state.get(k), text)), None)
            if holder:
                op.detail = f"نقل من {holder} (نفس النص)"
        if touched:
            gaps.user_touched += [f"{officer_id}: {_entry_label(e)}" for e in touched[-2:]]
        gaps.ops.append(op)
        if apply and op.status == "add":
            apply_admin_text(data, day, officer_id, text)
    return gaps


def apply_admin_text(data: dict[str, Any], day: str, officer_id: str, text: str) -> None:
    """يكتب `admin_work_text` وينقل `note`/`extra` لو نفس النص (من غير تكرار)."""
    states = data.setdefault("day_officers", {}).setdefault(day, {})
    entry = states.setdefault(officer_id, {})
    entry["admin_work_text"] = text
    for key in ("note", "extra"):
        if same_text(entry.get(key), text):
            entry.pop(key, None)


# ───────────────────────── 3) تقسيم الهدف بالوقت ─────────────────────────

TIME_WORD = re.compile(r"(?:^|\s)(حتى|حتي|من)\s*(?:الساعة|الساعه)?\s*(\d{1,2}(?:\s*:\s*\d{2})?\s*[صظمل]?)")
NAME_STOP = re.compile(r"\s*(?:\+|\(|(?:حتى|حتي|من)\s*(?:الساعة|الساعه)?\s*\d)")
TARGET_ALIASES = {norm("السخنة"): norm("كهرباء السخنة")}


def person_and_time(value: str) -> dict[str, Any]:
    """«مقدم / السعيد عبده حتى 4م + ت» -> {rank, name, kind: until|from, time: HH:MM}."""
    text = collapse(value)
    hit = TIME_WORD.search(text)
    clock = parse_time(hit.group(2)) if hit else None
    head = NAME_STOP.split(text, maxsplit=1)[0]
    rank, name, _ = split_person(head)
    return {"rank": rank, "name": name, "kind": None if not hit else ("until" if hit.group(1) in ("حتى", "حتي") else "from"),
            "time": clock, "taqseera": "ت" in re.split(r"\s", re.sub(r"[+\"“”]", " ", text))}


def canonical_target(data: dict[str, Any], day: str, service: str) -> str | None:
    names = targets_on(data, day)
    key = norm(service)
    key = TARGET_ALIASES.get(key, key)
    exact = [n for n in names if norm(n) == key]
    if exact:
        return exact[0]
    equivalent = [n for n in names if services_equivalent(n, service)]
    if len(equivalent) == 1:
        return equivalent[0]
    loose = [n for n in names if key and (key in norm(n) or norm(n) in key)]
    return loose[0] if len(loose) == 1 else None


def _by_service(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        groups.setdefault(norm(item["service"]), []).append(item)
    return groups


def plan_split_targets(data: dict[str, Any], day: str, sections: dict[str, list[dict[str, Any]]],
                       source: str = "", apply: bool = False) -> DayGaps:
    gaps = DayGaps(day, {"board": source}, day_origin(data, day))
    if not peek_day(data, day):
        if any(len(g) > 1 for g in _by_service(sections.get("targets") or []).values()):
            gaps.unresolve("split_target", "اليوم كله", "اليوم من غير تكليفات لوحة مخزّنة — مرشّح للاستيراد الكامل")
        return gaps
    index = OfficerIndex(data, day)
    groups: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for item in sections.get("targets") or []:
        key = norm(item["service"])
        if key not in groups:
            order.append(key)
        groups.setdefault(key, []).append(item)
    for key in order:
        items = groups[key]
        if len(items) < 2:
            continue
        service = items[0]["service"]
        parsed = [person_and_time(item["value"]) for item in items]
        if not any(p["kind"] for p in parsed):
            gaps.unresolve("split_target", service, "أكتر من ضابط على الهدف من غير حدود زمنية",
                           archive=" ؛ ".join(i["value"] for i in items))
            continue
        archive = " ؛ ".join(i["value"] for i in items)
        if len(items) != MAX_PERIODS:
            gaps.unresolve("split_target", service, f"{len(items)} ضباط على الهدف (التقسيم لضابطين بس)", archive=archive)
            continue
        first, second = parsed
        if first["kind"] != "until" or second["kind"] != "from" or not first["time"] or first["time"] != second["time"]:
            gaps.unresolve("split_target", service, "الفترتان مش «حتى T» ثم «من T» بنفس الوقت", archive=archive)
            continue
        target = canonical_target(data, day, service)
        if target is None:
            gaps.unresolve("split_target", service, "اسم الهدف مش من قايمة أهداف اليوم", archive=archive)
            continue
        found = [index.resolve(p["name"], p["rank"]) for p in parsed]
        bad = [p for p, f in zip(parsed, found) if f["status"] != "ok"]
        if bad:
            gaps.unresolve("split_target", service, "اسم ضابط مش محلول: " + "، ".join(p["name"] for p in bad),
                           archive=archive)
            continue
        ids = [found[0]["id"], found[1]["id"]]
        if ids[0] == ids[1]:
            gaps.unresolve("split_target", service, "نفس الضابط في الفترتين", archive=archive)
            continue
        periods = [{"officer_id": ids[0], "until": first["time"]}, {"officer_id": ids[1], "from": second["time"]}]
        row = next((r for r in peek_day(data, day)
                    if r.get("section") == SECTION_TARGETS and r.get("name") == target), None)
        label = f"{target} ({format_time(first['time'])})"
        if row is None:
            gaps.unresolve("split_target", target, "مفيش صف للهدف ده في تكليفات اليوم", archive=archive)
            continue
        op = Op("split_target", day, row["id"], label, {"periods": periods, "officer_ids": ids}, archive,
                current={"periods": row.get("periods") or [], "officer_ids": list(row.get("officer_ids") or [])})
        current_ids = list(row.get("officer_ids") or [])
        touched = user_entries(data, day, ("assignment",), row["id"])
        if valid_periods(row):
            op.status = "same" if valid_periods(row) == periods else "conflict"
        elif row.get("periods"):
            op.status, op.detail = "conflict", "فترات مخزّنة مش متسقة مع الضباط"
        elif set(current_ids) - set(ids):
            op.status, op.detail = "conflict", "ضابط تاني مسجّل على الهدف"
        elif touched and set(current_ids) != set(ids):
            op.status, op.detail = "conflict", "الصف اتعدّل من مستخدم (change_log)"
        else:
            _, _, error, _ = clean_periods(data, day, periods)
            if error:
                gaps.unresolve("split_target", service, error, archive=archive)
                continue
            op.status = "add"
        if touched:
            gaps.user_touched += [f"{row['id']}: {_entry_label(e)}" for e in touched[-2:]]
        gaps.ops.append(op)
        if apply and op.status == "add":
            row["officer_ids"] = ids
            set_periods(row, periods)
    return gaps


# ───────────────────────── تشغيل كامل ─────────────────────────

def merge_gaps(target: dict[str, DayGaps], gaps: DayGaps) -> None:
    mine = target.setdefault(gaps.day, DayGaps(gaps.day, origin=gaps.origin))
    mine.sources.update(gaps.sources)
    mine.ops += gaps.ops
    mine.unresolved += gaps.unresolved
    mine.skipped_basic += gaps.skipped_basic
    mine.user_touched += [x for x in gaps.user_touched if x not in mine.user_touched]


def run_import(data: dict[str, Any], archive_root: Path, start: str = DEFAULT_START, end: str | None = None,
               apply: bool = True, categories: tuple[str, ...] = CATEGORIES) -> dict[str, Any]:
    """يمر على الأيام بالترتيب ويرجّع تقرير مفصّل (وبيكتب على `data` في الذاكرة لو apply)."""
    days: dict[str, DayGaps] = {}
    errors: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []
    files = {"regularity": 0, "board": 0}
    if "regularity" in categories:
        chosen, notes = discover_regularity(archive_root, start, end)
        files["regularity"] = len(chosen)
        baseline = deepcopy(data.get("regularity_inputs") or {})
        for day, path in chosen.items():
            sheet = extract_regularity(path)
            if sheet.get("error"):
                errors.append({"day": day, "path": str(path), "error": sheet["error"]})
                continue
            merge_gaps(days, plan_regularity(data, day, sheet, apply=apply, baseline=baseline))
    if {"admin_work", "split_target"} & set(categories):
        boards = discover_boards(archive_root, start, end)
        files["board"] = len(boards)
        for day, path in boards.items():
            try:
                sections = extract_board_sections(path)
            except Exception as exc:  # ملف تالف بيتعزل ومابيوقفش الباقي
                errors.append({"day": day, "path": str(path), "error": f"{type(exc).__name__}: {exc}"})
                continue
            if "admin_work" in categories:
                merge_gaps(days, plan_admin_work(data, day, sections, str(path), apply=apply))
            if "split_target" in categories:
                merge_gaps(days, plan_split_targets(data, day, sections, str(path), apply=apply))
    # أيام مخزّنة بعد آخر يومية انتظام مستوردة (مفيش ملف ليها): هترث مدخلات آخر يوم لو ما اتحفظلهاش مدخلات
    saved = sorted(k for k, v in (data.get("regularity_inputs") or {}).items() if isinstance(v, dict))
    inheriting = [d for d in sorted(data.get("day_assignments") or {})
                  if saved and d > saved[-1] and d not in saved] if "regularity" in categories else []
    return {"days": dict(sorted(days.items())), "errors": errors, "notes": notes, "files": files,
            "range": (min(days), max(days)) if days else None, "inheriting_days": inheriting,
            "last_regularity_day": saved[-1] if saved else None}


def run_all(data: dict[str, Any], archive_root: Path, start: str = DEFAULT_START, end: str | None = None,
            apply: bool = True, batch: str = "archive-gaps-023", decisions: Path | None = None,
            import_days: bool = True, categories: tuple[str, ...] = CATEGORIES) -> dict[str, Any]:
    """الأيام الناقصة بالكامل الأول (عشان نصوصها تتملي)، وبعدها فجوات كل الأيام."""
    from . import single_day

    day_imports = []
    if import_days:
        for day in single_day.missing_days(data, archive_root, start, end):
            day_imports.append(single_day.import_day(data, day, archive_root, batch, decisions, apply=True))
    report = run_import(data, archive_root, start, end, apply=apply, categories=categories)
    report["day_imports"] = day_imports
    return report


def totals(report: dict[str, Any], day_imports: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"days": len(report["days"]), "add": 0, "same": 0, "conflict": 0, "unresolved": 0,
                           "days_with_adds": 0, "overrides_inherited": 0, "user_touched_days": 0,
                           "skipped_basic": 0}
    for category in CATEGORIES:
        out[category] = {"add": 0, "same": 0, "conflict": 0, "unresolved": 0, "days_add": set()}
    for day, gaps in report["days"].items():
        out["days_with_adds"] += any(op.status == "add" for op in gaps.ops)
        out["user_touched_days"] += bool(gaps.user_touched)
        out["skipped_basic"] += gaps.skipped_basic
        for op in gaps.ops:
            bucket = out[op.category]
            bucket[op.status] += 1
            out[op.status] += 1
            if op.status == "add":
                bucket["days_add"].add(day)
                out["overrides_inherited"] += op.overrides_inherited
        for item in gaps.unresolved:
            out[item["category"]]["unresolved"] += 1
            out["unresolved"] += 1
    for category in CATEGORIES:
        out[category]["days_add"] = len(out[category]["days_add"])
    imports = day_imports or []
    out["day_imports"] = {"days": len([x for x in imports if x["status"] == "import"]),
                          "skipped": len([x for x in imports if x["status"] != "import"]),
                          "unresolved": sum(len(x.get("unresolved") or []) for x in imports)}
    out["add"] += out["day_imports"]["days"]
    out["unresolved"] += out["day_imports"]["unresolved"]
    return out


# ───────────────────────── تقرير المعاينة (عربي) ─────────────────────────

def _cell(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _show(op: Op, current: bool = False) -> str:
    value = op.current if current else op.value
    if op.category == "regularity":
        if isinstance(value, dict):
            return " ".join(filter(None, [value.get("rank"), value.get("name"), value.get("phone")]))
        if isinstance(value, list):
            return " ؛ ".join(map(str, value))
    if op.category == "split_target":
        periods = value.get("periods") if isinstance(value, dict) else None
        ids = value.get("officer_ids") if isinstance(value, dict) else None
        if periods:
            return "، ".join(f"{p['officer_id']} {'حتى ' + format_time(p['until']) if p.get('until') else 'من ' + format_time(p['from'])}"
                             for p in periods)
        return "، ".join(ids or []) or "—"
    return str(value if value not in (None, "") else "—")


def render_preview(report: dict[str, Any], data: dict[str, Any], mode: str = "dry-run",
                   day_imports: list[dict[str, Any]] | None = None,
                   after_rates: dict[str, str] | None = None) -> str:
    t = totals(report, day_imports)
    rng = report["range"]
    lines = ["# معاينة استيراد فجوات الأرشيف", "",
             f"النطاق: {rng[0] if rng else '—'} إلى {rng[1] if rng else '—'} — {t['days']} يوم "
             f"(ملفات انتظام {report['files']['regularity']}، لوحات تفصيلية {report['files']['board']}). "
             f"الوضع: **{mode}** — المعاينة دي ما كتبتش على أي بيانات حقيقية.", "",
             "## الإجماليات", "",
             "| الفئة | هتتضاف | مطابقة بالفعل | تعارض (اتسابت) | غير محلول | أيام فيها إضافات |",
             "|---|---|---|---|---|---|"]
    for category in CATEGORIES:
        b = t[category]
        lines.append(f"| {CATEGORY_LABELS[category]} | {b['add']} | {b['same']} | {b['conflict']} | "
                     f"{b['unresolved']} | {b['days_add']} |")
    d = t["day_imports"]
    lines.append(f"| {CATEGORY_LABELS['day_import']} | {d['days']} يوم | — | {d['skipped']} يوم اتسابت | {d['unresolved']} | — |")
    lines += ["", f"- إجمالي الحقول اللي هتتضاف: {t['add']} (منها {t['overrides_inherited']} بتغيّر قيمة موروثة).",
              f"- التعارضات: {t['conflict']} — اتسابت من غير لمس. غير المحلول: {t['unresolved']}.",
              f"- أيام عليها تعديلات مستخدم مسجلة في change_log: {t['user_touched_days']}.",
              f"- صفوف ضباط في الانتظام مشتقة من اللوحة (مش مدخل) وتم تخطيها: {t['skipped_basic']}."]
    if report.get("inheriting_days"):
        lines += ["", f"- تنبيه وراثة: آخر يومية انتظام محفوظة بعد الاستيراد هي {report['last_regularity_day']}؛ الأيام "
                      f"{'، '.join(report['inheriting_days'])} (من غير ملف أرشيف) هترث مدخلاتها (مشرفي القول المكبر + الملاحظات + "
                      "نص المدير/الوكيل) بدل الافتراضي، وده تصميم الوراثة الحالي في `regularity.effective_inputs`."]
    if after_rates:
        lines += ["", "نسب التطابق بعد الاستيراد (على نسخة مؤقتة): " + "، ".join(f"{k} {v}" for k, v in after_rates.items())]
    for item in day_imports or []:
        lines += ["", f"## استيراد يوم كامل — {item['day']}", "", f"- الحالة: **{item['status']}** — {item.get('reason', '')}"]
        if item.get("sources"):
            lines.append("- الملفات المستخدمة: " + "، ".join(f"`{x}`" for x in item["sources"]))
        if item.get("stats"):
            lines.append("- الأثر: " + "، ".join(f"{STAT_LABELS.get(k, k)} {v}" for k, v in item["stats"].items()))
        for entry in item.get("unresolved") or []:
            lines.append(f"- غير محلول: {entry}")
    if report["notes"]:
        lines += ["", "## ملفات مكررة / من غير تاريخ في العنوان", ""]
        for note in report["notes"]:
            lines.append(f"- {note['reason']}: `{Path(note['path']).relative_to(Path(note['path']).parents[2]) if len(Path(note['path']).parents) > 2 else note['path']}`"
                         + (f" ← المعتمد `{Path(note['chosen']).name}` من {Path(note['chosen']).parent.name}" if note.get("chosen") else ""))
    if report["errors"]:
        lines += ["", "## ملفات اتعذرت قراءتها", ""]
        lines += [f"- {e['day']}: {e['error']} ({e['path']})" for e in report["errors"]]

    for category in CATEGORIES:
        lines += ["", f"## {CATEGORY_LABELS[category]} — حسب اليوم", ""]
        for day, gaps in report["days"].items():
            ops = [op for op in gaps.ops if op.category == category]
            unresolved = [u for u in gaps.unresolved if u["category"] == category]
            if not ops and not unresolved:
                continue
            adds = [op for op in ops if op.status == "add"]
            conflicts = [op for op in ops if op.status == "conflict"]
            lines += [f"### {day}", "",
                      f"- المصدر: `{Path(gaps.sources.get('regularity' if category == 'regularity' else 'board', '')).name}` | أصل اليوم: {gaps.origin} | "
                      f"هتتضاف {len(adds)} | مطابقة {sum(op.status == 'same' for op in ops)} | "
                      f"تعارض {len(conflicts)} | غير محلول {len(unresolved)}"]
            if gaps.user_touched:
                lines.append(f"- تعديلات مستخدم مسجلة: {'، '.join(gaps.user_touched[:4])}")
            if adds:
                lines += ["", "| الحقل | القيمة اللي هتتضاف | ملاحظة |", "|---|---|---|"]
                for op in adds:
                    note = " ".join(filter(None, [op.detail, "بتغيّر موروث" if op.overrides_inherited else ""]))
                    lines.append(f"| {_cell(op.label)} | {_cell(_show(op))} | {_cell(note)} |")
            if conflicts:
                lines += ["", "تعارضات (اتسابت):", "", "| الحقل | الأرشيف | الحالي في النظام | سبب |", "|---|---|---|---|"]
                for op in conflicts:
                    lines.append(f"| {_cell(op.label)} | {_cell(_show(op))} | {_cell(_show(op, True))} | {_cell(op.detail)} |")
            if unresolved:
                lines += ["", "غير محلول:", ""]
                for u in unresolved:
                    lines.append(f"- {_cell(u['row'])} — {u['reason']}" + (f" [{_cell(u['archive'])}]" if u.get("archive") else ""))
            lines.append("")
    return "\n".join(lines) + "\n"

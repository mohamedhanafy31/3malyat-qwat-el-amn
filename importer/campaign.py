"""مرحلة «يومية الحملة»: استخراج + حل + خطة دمج، من غير ما تكتب أي حاجة.

المستورد التاريخي بيصنّف ملفات «يومية الحملة» out_of_scope (discover.py)، فالمرحلة
دي مستقلة عنه: بتقرا ملف الأرشيف لكل يوم، وتحوّله لخطة حقول على موديل
`day_campaign` (نفس الأشكال اللي `backend/campaign.py` بيقراها وبيكتبها)، وتطبّقها
على نسخة `data` في الذاكرة بس لو اتطلب منها. الكتابة على القرص مسؤولية
`migrations/022_import_campaign.py` (dry-run افتراضيًا).

القواعد:
* الخريطة العكسية لـ`backend/campaign_export.py`: جدول واحد، الارتكازات فوق خط
  «خطوط سير توصيل الخدمات»، وتحته صفوف التوصيل (لوريات/مواعيد/خدمات/أقوال يومية)،
  وآخر الجدول سجل اللوحات.
* ممنوع التخمين الصامت: أي صف/لوحة/سائق مش بيتحل بشكل مؤكد بيروح لقايمة
  `unresolved` بسببه، ومش بنكتب بدله حاجة (السائق النصي استثناء: النص الأصلي
  نفسه هو القيمة، وبيتعد في التقرير برضه).
* واعي بالتعارض: الحقل اللي ليه قيمة مخزّنة فعلًا في اليوم (مش موروثة) وتختلف
  عن الأرشيف **مابيتلمسش** ويتسجل conflict. الحقول الفاضية أو الموروثة بس هي اللي
  بتتملى.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from copy import deepcopy
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from backend import fleet
from backend.afraad import occasional_rows
from backend.campaign import _assignment, _assignment_people
from backend.constants import APPOINTMENT_LORRIES, CAMPAIGN_LORRIES
from backend.dated import afraad_basic_on, campaign_daily_on, campaign_posts_on
from backend.repo import ConscriptRepo, PeopleRepo, VehicleRepo
from backend.text import core_service_name, norm, norm_name

from .textnorm import clean_text, dates_in_text

VERSION = "1"
DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
DIVIDER_WORD = "خطوط"
FILE_PREFIX = "يومية الحملة"
RANKS = re.compile(r"^(?:م\s*\.?\s*ش|ا\s*\.?\s*ش|اش|مش|رقيب|مندوب|عريف|شرطي|مجند|فرد)\s*[/\\.:]?\s+|"
                   r"^(?:م\s*\.?\s*ش|ا\s*\.?\s*ش)\s*[/\\.:]\s*")
PLACEHOLDER = re.compile(r"^[\s\-_ـ‐‑‒–—―.\/،؛:]*$")
TIME = re.compile(r"\d{1,2}\s*(?:[صظملح]+)(?![ء-ي])")
QUOTED = re.compile(r'["“”«»].*?["“”«»]')
SERVICE_MIN_SCORE = 0.8
DAILY_MIN_SCORE = 0.9

# أسماء الأقوال اليومية في الأرشيف -> الاسم القانوني اللي في قايمة اليوم.
DAILY_ALIASES = {"بورتوفيق": "سائق بورتوفيق", "قول مكبر": "القول المكبر"}


# ───────────────────────── الاستخراج (من غير بيانات النظام) ─────────────────────────

def cells(row) -> list[str]:
    """خلايا الصف المنطقية مرة واحدة (الدمج الأفقي بيكرر الخلية في python-docx)."""
    seen, out = set(), []
    for cell in row.cells:
        if cell._tc not in seen:
            seen.add(cell._tc)
            out.append(clean_text(cell.text))
    return out


def _blank(value: str) -> bool:
    return not value or bool(PLACEHOLDER.fullmatch(value))


def plate_like(value: str) -> bool:
    """خلية في سجل اللوحات: «ب15/5217» أو «5217» بس، من غير أي كلام تاني."""
    text = value.translate(DIGITS).replace(" ", "")
    return bool(re.fullmatch(r"[ء-ي]{1,3}\d{1,2}[/\\\-]+\d{3,5}|\d{1,2}[/\\]\d{3,5}|\d{3,5}|"
                             r"\d{3,5}[ء-ي]{1,3}\d{1,2}", text))


def extract_file(path: Path) -> dict[str, Any]:
    """يستخرج ملف يومية حملة واحد: ارتكازات، صفوف توصيل، سجل لوحات (نصوص خام نضيفة)."""
    from docx import Document

    document = Document(path)
    if not document.tables:
        return {"path": str(path), "error": "no-table", "posts": [], "delivery": [], "plates": []}
    rows = [cells(row) for row in document.tables[0].rows]
    divider = next((i for i, parts in enumerate(rows)
                    if len(parts) == 1 and DIVIDER_WORD in parts[0]), None)
    header = next((i for i, parts in enumerate(rows)
                   if parts and parts[0].strip(". ") == "م" and "ارتكازات" in norm(" ".join(parts))), None)
    if divider is None or header is None:
        return {"path": str(path), "error": "layout-not-recognised",
                "posts": [], "delivery": [], "plates": []}
    posts = []
    for parts in rows[header + 1:divider]:
        if len(parts) >= 2 and not _blank(parts[1]):
            parts = parts + [""] * (5 - len(parts))
            posts.append({"number": parts[0], "name": parts[1], "driver": "" if _blank(parts[2]) else parts[2],
                          "plate": parts[3], "type": parts[4]})
    delivery, plates = [], []
    for parts in rows[divider + 1:]:
        if len(parts) >= 2 and parts[0] in ("م", "م.") and parts[1].startswith("الخدمة"):
            continue                                    # رأس جدول التوصيل
        filled = [part for part in parts if not _blank(part)]
        if not filled:
            continue
        if len(parts) >= 3 and not _blank(parts[1]) and not plate_like(parts[1]):
            parts = parts + [""] * (5 - len(parts))
            delivery.append({"name": parts[1], "driver": "" if _blank(parts[2]) else parts[2],
                             "plate": "" if _blank(parts[3]) else parts[3],
                             "type": "" if _blank(parts[4]) else parts[4]})
        elif all(plate_like(part) for part in filled):
            plates.append(filled)
    return {"path": str(path), "error": None, "posts": posts, "delivery": delivery, "plates": plates,
            "sha1": hashlib.sha1(path.read_bytes()).hexdigest()}


def file_day(path: Path) -> str | None:
    found = dates_in_text(path.name.translate(DIGITS))
    return found[0].isoformat() if found else None


def discover_files(archive_root: Path, start: str = "2026-08-01", end: str | None = None) -> dict[str, Path]:
    """ملف يومية الحملة لكل يوم (اليوم المطبوع في الاسم). النسخة اللي فولدرها هو رقم اليومها أولى."""
    chosen: dict[str, Path] = {}
    for path in sorted(archive_root.glob(f"*/*/{FILE_PREFIX}*.docx")):
        if path.name.startswith("~$") or "ارتكازات" in path.name:
            continue
        day = file_day(path)
        if not day or day < start or (end and day > end):
            continue
        better = day not in chosen or (path.parent.name == str(int(day[8:]))
                                       and chosen[day].parent.name != str(int(day[8:])))
        if better:
            chosen[day] = path
    return dict(sorted(chosen.items()))


# ───────────────────────── اللوحات ─────────────────────────

def parse_plate(text: Any) -> dict[str, str] | None:
    """«ب14/9556» | «9556» | «14/9556» | «3279ب13» | «4222 ب15» -> {series, number, form}."""
    raw = str(text or "").translate(DIGITS)
    raw = re.sub(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069ـ]", "", raw)
    flat = re.sub(r"\s+", "", raw)
    hit = re.search(r"([ء-ي]{1,3})(\d{1,2})[/\\\-]+(\d{3,5})(?!\d)", flat)
    if hit:
        return {"series": hit[1] + hit[2], "number": hit[3], "form": "series/number"}
    hit = re.search(r"(?<!\d)(\d{3,5})([ء-ي]{1,3})(\d{1,2})(?!\d)", flat)
    if hit:
        return {"series": hit[2] + hit[3], "number": hit[1], "form": "number-series"}
    hit = re.search(r"(?<!\d)(\d{1,2})[/\\]+(\d{3,5})(?!\d)", flat)
    if hit:
        return {"series": "#" + hit[1], "number": hit[2], "form": "digits/number"}
    hit = re.search(r"(?<!\d)(\d{3,5})(?!\d)", flat)
    if hit:
        return {"series": "", "number": hit[1], "form": "number"}
    return None


class FleetIndex:
    """فهرس مركبات السجل بالرقم، مع مطابقة السلسلة لما الأرشيف يذكرها."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.by_number: dict[str, list[Any]] = {}
        for vehicle in VehicleRepo(data).all():
            self.by_number.setdefault(re.sub(r"\D", "", vehicle.plate_number.translate(DIGITS)), []).append(vehicle)

    @staticmethod
    def _series_ok(wanted: str, have: str) -> bool:
        have = re.sub(r"\s+", "", have or "")
        if wanted.startswith("#"):
            return re.sub(r"\D", "", have) == wanted[1:]
        return not wanted or have == wanted

    def resolve(self, text: Any) -> dict[str, Any]:
        """-> {status: ok|none|unregistered|ambiguous|series-mismatch, vehicle_id?, plate?}."""
        plate = parse_plate(text)
        if plate is None:
            return {"status": "none"}
        candidates = self.by_number.get(plate["number"], [])
        if not candidates:
            return {"status": "unregistered", "plate": plate}
        exact = [v for v in candidates if self._series_ok(plate["series"], v.plate_series)]
        if len(exact) == 1:
            return {"status": "ok", "vehicle_id": exact[0].id, "plate": plate}
        if len(exact) > 1:
            return {"status": "ambiguous", "plate": plate,
                    "candidates": [v.plate for v in exact]}
        return {"status": "series-mismatch", "plate": plate,
                "candidates": [v.plate for v in candidates]}


# ───────────────────────── السائقين ─────────────────────────

def _name_tokens(text: str) -> list[str]:
    text = RANKS.sub("", clean_text(text))
    return norm_name(text).split()


def _tokens_match(wanted: list[str], have: list[str], floor: float) -> bool:
    if len(have) < len(wanted):
        return False
    return all(SequenceMatcher(None, w, h).ratio() >= floor for w, h in zip(wanted, have))


class DriverIndex:
    """سائقين اليوم (أفراد بوظيفة سائق + مجندين سواقين) ثم باقي القوة كاحتياط أشد."""

    def __init__(self, data: dict[str, Any], day: str) -> None:
        pools = fleet.drivers_on(data, day)
        self.primary = [("personnel", item["id"], item["name"]) for item in pools["personnel"]]
        self.primary += [("conscript", item["id"], item["name"]) for item in pools["conscripts"]]
        seen = {(kind, ident) for kind, ident, _ in self.primary}
        self.fallback = [("personnel", p.id, p.name) for p in PeopleRepo(data).on_force(day, "personnel")
                         if ("personnel", p.id) not in seen]
        self.fallback += [("conscript", c.id, c.name) for c in ConscriptRepo(data).all()
                          if ("conscript", c.id) not in seen]

    def resolve(self, text: str) -> dict[str, Any]:
        """-> {status: linked|text|ambiguous|none, value?, candidates?}. القيمة نص حر لو مفيش مطابقة مؤكدة."""
        text = clean_text(text)
        if _blank(text):
            return {"status": "none"}
        wanted = _name_tokens(text)
        as_text = {"kind": "text", "id": "", "name": text}
        if len(wanted) < 2:
            return {"status": "text", "value": as_text, "reason": "اسم أقل من كلمتين"}
        for pool, floor, minimum in ((self.primary, 0.85, 2), (self.fallback, 0.9, 3)):
            if len(wanted) < minimum:
                continue
            hits = [(kind, ident, name) for kind, ident, name in pool
                    if _tokens_match(wanted, _name_tokens(name), floor)]
            exact = [h for h in hits if _name_tokens(h[2]) == wanted]
            hits = exact or hits
            if len(hits) == 1:
                kind, ident, name = hits[0]
                return {"status": "linked", "value": {"kind": kind, "id": ident}, "name": name}
            if len(hits) > 1:
                return {"status": "ambiguous", "value": as_text,
                        "candidates": [f"{h[1]} {h[2]}" for h in hits[:4]]}
        return {"status": "text", "value": as_text, "reason": "لا مطابقة في سواقين اليوم"}


# ───────────────────────── مطابقة الصفوف ─────────────────────────

def _tokens(text: str) -> list[str]:
    """كلمات المفتاح: مطبّعة، من غير «ال»، وبلا ساعة/جهة/فترة."""
    core = core_service_name(re.sub(r"\([^)]*\)", " ", text or ""))
    core = re.sub(r"\b(?:وطنى)\b", "وطني", core)
    return [re.sub(r"^ال(?=..)", "", w) for w in core.split()]


def key_of(text: str) -> str:
    return " ".join(_tokens(text))


def service_score(left: str, right: str) -> float:
    a, b = set(_tokens(left)), set(_tokens(right))
    if not a or not b:
        return 0.0
    seq = SequenceMatcher(None, key_of(left), key_of(right)).ratio()
    contain = len(a & b) / min(len(a), len(b))
    smaller = min(a, b, key=len)
    if len(smaller) >= 2:
        return max(seq, 0.95 * contain)
    if len(smaller) == 1 and len(next(iter(smaller))) >= 5:
        return max(seq, 0.82 * contain)
    return seq


def split_parts(text: str) -> list[str]:
    """«فيصل + تفتيش فيصل» -> أجزاء نصية خام (الفاصل «+» قبل التطبيع لأنه بيشيله)."""
    return [clean_text(p) for p in clean_text(text).split("+") if clean_text(p)]


def _time_of(text: str) -> str:
    hit = TIME.search(QUOTED.sub(" ", str(text or "").translate(DIGITS)))
    return re.sub(r"\s+", "", hit[0]) if hit else ""


def _shift_hint(text: str) -> str | None:
    flat = str(text or "").translate(DIGITS)
    if re.search(r"1[02]\s*[لم]\b|ليل", flat):
        return "ليلية"
    if re.search(r"\d\s*ص|1[02]\s*ظ|صباح", flat):
        return "صباحية"
    return None


def classify(name: str) -> tuple[str, str | None]:
    """-> ("lorry", LOR-n) | ("appointment", LOR-An) | ("daily", canonical) | ("service", None)."""
    parts = split_parts(name)
    first = key_of(parts[0]) if parts else key_of(name)
    flat = key_of(name)
    words = set(flat.split())
    if words & {"محور", "محكمه", "افطار"} or "افطار" in flat:
        return "lorry", "LOR-1"
    if first.startswith("قنصليه"):
        return "lorry", "LOR-2"
    if first.startswith("فيصل"):
        return "lorry", "LOR-3"
    if re.match(r"^(?:ك|كمين)\s*109\b", first) or first == "ك109":
        return "lorry", "LOR-4"
    for spec, lorry_id in zip(APPOINTMENT_LORRIES, ("LOR-A1", "LOR-A2", "LOR-A3")):
        if first == key_of(spec["name"]):
            return "appointment", spec["id"]
    return "service", None


@dataclass
class Op:
    """حقل واحد في خطة اليوم: path جوه day_campaign[day]، والقيمة، وتسمية للتقرير."""
    path: tuple[str, ...]
    value: Any
    row: str                      # اسم الصف عند الأرشيف
    archive: str = ""            # النص الأصلي اللي اتحوّل للقيمة
    status: str = ""             # add | same | conflict
    current: Any = None
    overrides_inherited: bool = False


@dataclass
class DayPlan:
    day: str
    source: str = ""
    ops: list[Op] = field(default_factory=list)
    unresolved: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=lambda: {
        "rows": 0, "rows_resolved": 0, "plates": 0, "plates_resolved": 0,
        "drivers": 0, "drivers_linked": 0, "drivers_text": 0, "drivers_ambiguous": 0})
    user_touched: list[str] = field(default_factory=list)
    conflicts: list[Op] = field(default_factory=list)
    added: list[Op] = field(default_factory=list)
    same: int = 0


class DayResolver:
    """يحوّل صفوف الأرشيف ليوم واحد لعمليات على حقول day_campaign."""

    def __init__(self, data: dict[str, Any], day: str, fleet_index: FleetIndex) -> None:
        self.data, self.day = data, day
        self.fleet = fleet_index
        self.drivers = DriverIndex(data, day)
        self.plan = DayPlan(day)
        self.assignments = occasional_rows(data, day)
        self.used_assignments: set[str] = set()

    # ---- أدوات مشتركة ----
    def _unresolved(self, kind: str, row: str, reason: str, **extra: Any) -> None:
        self.plan.unresolved.append({"day": self.day, "kind": kind, "row": row, "reason": reason, **extra})

    def _vehicle(self, row: str, plate_text: str) -> str | None:
        if _blank(plate_text):
            return None
        self.plan.stats["plates"] += 1
        found = self.fleet.resolve(plate_text)
        if found["status"] == "ok":
            self.plan.stats["plates_resolved"] += 1
            return found["vehicle_id"]
        reasons = {"unregistered": "لوحة غير مسجلة في سجل المركبات",
                   "ambiguous": "أكتر من مركبة بنفس اللوحة",
                   "series-mismatch": "الرقم موجود بسلسلة مختلفة في السجل",
                   "none": "لوحة غير مقروءة"}
        self._unresolved("vehicle", row, reasons[found["status"]], plate=clean_text(plate_text),
                         candidates=found.get("candidates"))
        return None

    def _driver(self, row: str, driver_text: str) -> dict[str, Any] | None:
        found = self.drivers.resolve(driver_text)
        if found["status"] == "none":
            return None
        stats = self.plan.stats
        stats["drivers"] += 1
        if found["status"] == "linked":
            stats["drivers_linked"] += 1
            return found["value"]
        if found["status"] == "ambiguous":
            stats["drivers_ambiguous"] += 1
            self._unresolved("driver", row, "اسم السائق غامض (أكتر من مطابقة)، اتسجل نص", driver=driver_text,
                             candidates=found["candidates"], severity="text")
        else:
            stats["drivers_text"] += 1
            self._unresolved("driver", row, found.get("reason", "غير مطابق"), driver=driver_text,
                             severity="text")
        return found["value"]

    def _add(self, path: tuple[str, ...], value: Any, row: str, archive: str = "") -> None:
        if value in (None, "", [], {}):
            return
        self.plan.ops.append(Op(path, value, row, archive))

    # ---- الارتكازات ----
    def posts(self, rows: list[dict[str, str]]) -> None:
        items = campaign_posts_on(self.data, self.day)
        by_key = {(clean_text(i.get("number", "")).strip("."), norm(i["name"])): i for i in items}
        by_name: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            by_name.setdefault(norm(item["name"]), []).append(item)
        for row in rows:
            self.plan.stats["rows"] += 1
            label = f"{row['number']} {row['name']}".strip()
            item = by_key.get((row["number"].strip("."), norm(row["name"])))
            if item is None and len(by_name.get(norm(row["name"]), [])) == 1:
                item = by_name[norm(row["name"])][0]
            if item is None:
                self._unresolved("post", label, "الارتكاز غير موجود في قايمة ارتكازات اليوم")
                continue
            self.plan.stats["rows_resolved"] += 1
            pid = item["id"]
            vehicle_id = self._vehicle(label, row["plate"])
            self._add(("posts", pid, "vehicle_id"), vehicle_id, label, row["plate"])
            self._add(("posts", pid, "plate_text"), clean_text(row["plate"]), label)
            self._add(("posts", pid, "type_text"), clean_text(row["type"]), label)
            if row["driver"] and clean_text(row["driver"]) != clean_text(item.get("driver_text", "")):
                self._add(("posts", pid, "driver_text"), clean_text(row["driver"]), label)

    # ---- التوصيل ----
    def delivery(self, rows: list[dict[str, str]]) -> None:
        daily_items = campaign_daily_on(self.data, self.day)
        daily_taken: set[str] = set()
        basics = afraad_basic_on(self.data, self.day)
        for row in rows:
            self.plan.stats["rows"] += 1
            name = row["name"]
            has_data = bool(row["driver"] or not _blank(row["plate"]))
            kind, key = classify(name)
            if kind in ("lorry", "appointment"):
                self.plan.stats["rows_resolved"] += 1
                if has_data:
                    self._seat(("lorries", key), row)
                parts = split_parts(name)
                attached = self._attached(key, parts, name)
                self._add(("lorries", key, "attached"), attached, name)
                continue
            daily = self._daily_match(name, daily_items, daily_taken)
            if daily is not None:
                self.plan.stats["rows_resolved"] += 1
                daily_taken.add(daily["id"])
                if has_data:
                    self._seat(("daily", daily["id"]), row)
                self._link_basic(daily, name, basics)
                continue
            if not has_data:
                # صف خدمة بلا سائق ولا لوحة: مفيش حاجة تتسكّن (بس بنعدّه محلولًا لو الخدمة موجودة).
                if any(self._service_for(part, name, claim=False) for part in split_parts(name)):
                    self.plan.stats["rows_resolved"] += 1
                else:
                    self._unresolved("service", name, "خدمة غير موجودة في تكليفات اليوم (وبلا سائق/لوحة)")
                continue
            self._service_row(row)

    def _attached(self, lorry_id: str, parts: list[str], row_name: str) -> list[dict[str, str]]:
        base = {"LOR-1": {"محور", "محكمه", "افطار"}, "LOR-2": {"قنصليه"}, "LOR-3": {"فيصل"},
                "LOR-4": {"109", "ك109", "ك", "كمين"}}.get(lorry_id)
        if base is None:      # لوري موعد: اسمه نفسه هو الأساس
            base = {key_of(s["name"]) for s in APPOINTMENT_LORRIES if s["id"] == lorry_id}
        out: list[dict[str, str]] = []
        for part in parts:
            words = set(key_of(part).split())
            if not words or words <= base or key_of(part) in base:
                continue
            assignment = self._service_for(part, row_name, claim=True)
            out.append({"assignment_id": assignment["id"]} if assignment else {"name": part})
        return out

    def _daily_match(self, name: str, items: list[dict[str, Any]], taken: set[str]) -> dict[str, Any] | None:
        first = split_parts(name)[0] if split_parts(name) else name
        wanted = key_of(first)
        for alias, canonical in DAILY_ALIASES.items():
            if key_of(alias) in wanted:
                wanted = key_of(canonical)
        best = [(service_score(wanted, item["name"]), item) for item in items if item["id"] not in taken]
        best = [pair for pair in best if pair[0] >= DAILY_MIN_SCORE]
        best.sort(key=lambda pair: -pair[0])
        return best[0][1] if best else None

    def _link_basic(self, item: dict[str, Any], archive_name: str, basics: list[dict[str, Any]]) -> None:
        """«ارتكاز الاسعاف» -> الخدمة الأساسية المقابلة في أفراد اليوم (basic_entry_id)."""
        by_id = {b["id"]: b for b in basics}
        if item.get("basic_entry_id") in by_id:
            return                                       # القايمة نفسها رابطاها وصالحة
        wanted = key_of(item["name"])
        stripped = key_of(str(item["name"]).removeprefix("ارتكاز "))
        matches = [b for b in basics if key_of(b.get("name", "")) in (wanted, stripped)]
        if len(matches) == 1:
            self._add(("daily", item["id"], "basic_entry_id"), matches[0]["id"], item["name"], archive_name)
        elif item.get("basic_entry_id") or "ارتكاز" in str(item["name"]) or len(matches) > 1:
            # القول ماليهوش خدمة أساسية بطبيعته (زي «سائق بورتوفيق») مش مشكلة؛ بس الرابط الميت أو الغامض يتبلّغ.
            self._unresolved("basic_entry", item["name"],
                             "الرابط الحالي غير موجود في أفراد اليوم ولا مطابقة بالاسم" if not matches
                             else "أكتر من خدمة أساسية مطابقة")

    def _seat(self, base: tuple[str, ...], row: dict[str, str], vehicle_extra: dict | None = None) -> None:
        label = row["name"]
        vehicle_id = self._vehicle(label, row["plate"])
        self._add(base + ("vehicle_id",), vehicle_id, label, row["plate"])
        driver = self._driver(label, row["driver"])
        self._add(base + ("driver",), driver, label, row["driver"])

    # ---- الخدمات ----
    def _service_for(self, part: str, row_name: str, claim: bool) -> dict[str, Any] | None:
        hint = _shift_hint(row_name) or _shift_hint(part)
        stamp = _time_of(part) or _time_of(row_name)
        scored = sorted(((max(service_score(part, a.get("name") or ""), service_score(part, a.get("label") or "")), a)
                         for a in self.assignments), key=lambda pair: -pair[0])
        if not scored or scored[0][0] < SERVICE_MIN_SCORE:
            return None
        top = [a for s, a in scored if s >= scored[0][0] - 0.02]
        pool = [a for a in top if a["id"] not in self.used_assignments] if claim else top
        if stamp:
            pool = [a for a in pool if _time_of(a.get("time") or "") == stamp] or pool
        if hint:
            pool = [a for a in pool if a.get("shift") == hint] or pool
        if not pool:
            return None
        if len(pool) > 1 and len({a["id"] for a in pool}) > 1:
            # تعادل حقيقي بعد التلميحات: مانختارش — الأولوية للترتيب لو الأسماء متطابقة فعلًا
            names = {key_of(a.get("name") or "") for a in pool}
            if len(names) > 1:
                return None
        chosen = pool[0]
        if claim:
            self.used_assignments.add(chosen["id"])
        return chosen

    def _service_row(self, row: dict[str, str]) -> None:
        name = row["name"]
        matched = False
        vehicle_id = self._vehicle(name, row["plate"])
        driver = self._driver(name, row["driver"])
        for part in split_parts(name):
            assignment = self._service_for(part, name, claim=True)
            if assignment is None:
                continue
            matched = True
            aid = assignment["id"]
            self._add(("services", aid, "driver"), driver, name, row["driver"])
            if vehicle_id:
                people = _assignment_people(_assignment(self.data, self.day, aid))
                self._add(("services", aid, "vehicles"),
                          [{"vehicle_id": vehicle_id, **people, **({"driver": driver} if driver else {})}],
                          name, row["plate"])
        if matched:
            self.plan.stats["rows_resolved"] += 1
        else:
            self._unresolved("service", name, "خدمة غير موجودة في تكليفات اليوم")

    def plates(self, rows: list[list[str]]) -> None:
        if rows:
            self._add(("plates", "rows"), [[clean_text(c) for c in r] for r in rows], "سجل اللوحات")


# ───────────────────────── الدمج الواعي بالتعارض ─────────────────────────

def _get(raw: dict[str, Any], path: tuple[str, ...]) -> Any:
    node: Any = raw
    for part in path:
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _set(raw: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    node = raw
    for part in path[:-1]:
        node = node.setdefault(part, {})
    node[path[-1]] = deepcopy(value)


def _driver_key(value: Any) -> str:
    if not isinstance(value, dict) or not value:
        return ""
    if value.get("kind") in ("personnel", "conscript"):
        return f"{value['kind']}:{value.get('id')}"
    return "text:" + " ".join(_name_tokens(value.get("name", "")))


def _driver_label(value: Any, names: dict[str, str]) -> str:
    if not isinstance(value, dict):
        return ""
    return value.get("name", "") if value.get("kind") == "text" else names.get(str(value.get("id")), "")


def names_compatible(left: str, right: str) -> bool:
    """نفس الشخص: الاسم المختصر (كلمتين+) بداية الاسم الأطول، بنفس ترتيب الكلمات."""
    a, b = _name_tokens(left), _name_tokens(right)
    short, long = sorted((a, b), key=len)
    return len(short) >= 2 and _tokens_match(short, long, 0.85)


def _related(left: str, right: str) -> bool:
    a, b = set(_tokens(left)), set(_tokens(right))
    return bool(a and b and (a <= b or b <= a)) or service_score(left, right) >= 0.6


def same_value(path: tuple[str, ...], current: Any, new: Any, names: dict[str, str], archive: str = "") -> bool:
    """هل القيمة المخزنة بتمثل نفس قيمة الأرشيف؟ (المقارنة دلالية مش حرفية)."""
    field_name = path[-1]
    if field_name == "driver":
        if _driver_key(current) == _driver_key(new):
            return True
        # نفس الشخص بصيغة اسم أطول/أقصر (نصي مخزّن أو مربوط) = مش تعارض
        label = _driver_label(current, names)
        return names_compatible(label, _driver_label(new, names)) or names_compatible(label, archive)
    if field_name == "vehicles":
        have = [str(v.get("vehicle_id")) for v in (current or []) if isinstance(v, dict)]
        return sorted(have) == sorted(str(v.get("vehicle_id")) for v in new)
    if field_name == "attached":
        def label(item):
            return names.get(str(item.get("assignment_id")), "") if item.get("assignment_id") else item.get("name", "")
        have, want = list(current or []), list(new or [])
        if len(have) != len(want):
            return False
        pool = list(have)
        for item in want:
            hit = next((h for h in pool if (h.get("assignment_id") and h.get("assignment_id") == item.get("assignment_id"))
                        or _related(label(h), label(item))), None)
            if hit is None:
                return False
            pool.remove(hit)
        return True
    if path[0] == "plates":
        def rows(items):
            return [[parse_plate(c)["series"] + "/" + parse_plate(c)["number"] if parse_plate(c) else clean_text(c)
                     for c in row] for row in items or []]
        return rows(current) == rows(new)
    if field_name in ("plate_text", "type_text", "driver_text"):
        return norm(str(current or "")) == norm(str(new or ""))
    return str(current) == str(new)


def _legacy_view(raw: dict[str, Any], path: tuple[str, ...]) -> Any:
    """القيمة المخزّنة بالشكلين: services/AS/vehicle_id القديم يتعامل كـvehicles مفردة."""
    value = _get(raw, path)
    if value is None and path[0] == "services" and path[-1] == "vehicles":
        legacy = _get(raw, path[:-1] + ("vehicle_id",))
        if legacy:
            return [{"vehicle_id": legacy}]
    return value


def user_touched_entries(data: dict[str, Any], day: str) -> list[str]:
    """سطور change_log اللي تخص حملة اليوم ده وطالعة من مستخدم (مش من استيراد النظام)."""
    out = []
    for entry in data.get("change_log") or []:
        entity = str(entry.get("entity") or "")
        if "campaign" not in entity or entity == "import":
            continue
        if entry.get("day") not in (day, None) and entry.get("entity_id") != day:
            continue
        if entry.get("day") == day or entry.get("entity_id") == day:
            out.append(f"{entry.get('id')} {entry.get('ts')} {entry.get('edited_by') or ''}".strip())
    return out


def inherited_value(data: dict[str, Any], day: str, path: tuple[str, ...]) -> Any:
    previous = max((d for d in (data.get("day_campaign") or {}) if d < day), default=None)
    if previous is None:
        return None
    return _legacy_view((data.get("day_campaign") or {}).get(previous) or {}, path)


def merge_plan(data: dict[str, Any], plan: DayPlan, names: dict[str, str] | None = None,
               apply: bool = False) -> DayPlan:
    """يصنّف كل حقل (add / same / conflict) على أساس المخزّن فعلًا في اليوم، ويكتب الـadd لو apply."""
    names = {**(names or {}), **{a["id"]: a.get("name") or a.get("label") or ""
                                 for a in occasional_rows(data, plan.day)}}
    raw = (data.get("day_campaign") or {}).get(plan.day) or {}
    plan.user_touched = user_touched_entries(data, plan.day)
    for op in plan.ops:
        current = _legacy_view(raw, op.path)
        # الحقل السائق في الخدمات القديمة والجديدة بيتخزن في نفس المكان
        if current in (None, "", {}, []):
            op.status = "add"
            inherited = inherited_value(data, plan.day, op.path)
            op.overrides_inherited = bool(inherited not in (None, "", {}, []) and
                                          not same_value(op.path, inherited, op.value, names, op.archive))
            plan.added.append(op)
            continue
        op.current = deepcopy(current)
        if same_value(op.path, current, op.value, names, op.archive):
            op.status = "same"
            plan.same += 1
        else:
            op.status = "conflict"
            plan.conflicts.append(op)
    if apply and plan.added:
        sheet = data.setdefault("day_campaign", {}).setdefault(plan.day, {})
        for op in plan.added:
            _set(sheet, op.path, op.value)
    return plan


# ───────────────────────── تشغيل كامل ─────────────────────────

def build_plan(data: dict[str, Any], day: str, sheet: dict[str, Any], fleet_index: FleetIndex) -> DayPlan:
    resolver = DayResolver(data, day, fleet_index)
    resolver.plan.source = sheet.get("path", "")
    resolver.posts(sheet.get("posts") or [])
    resolver.delivery(sheet.get("delivery") or [])
    resolver.plates(sheet.get("plates") or [])
    return resolver.plan


def run_import(data: dict[str, Any], archive_root: Path, start: str = "2026-08-01", end: str | None = None,
               apply: bool = True) -> dict[str, Any]:
    """يمر على أيام الأرشيف بالترتيب (عشان وراثة اليوم السابق تتحسب بعد دمجه) ويرجّع تقرير مفصّل."""
    files = discover_files(archive_root, start, end)
    index = FleetIndex(data)
    names = {c.id: c.name for c in ConscriptRepo(data).all()}
    names.update({p["id"]: p.get("name", "") for p in (data.get("personnel") or []) if isinstance(p, dict)})
    plans, errors = [], []
    for day, path in files.items():
        sheet = extract_file(path)
        if sheet.get("error"):
            errors.append({"day": day, "path": str(path), "error": sheet["error"]})
            continue
        plan = build_plan(data, day, sheet, index)
        merge_plan(data, plan, names, apply=apply)
        plans.append(plan)
    return {"files": len(files), "plans": plans, "errors": errors,
            "range": (min(files), max(files)) if files else None}


def _pct(part: int, whole: int) -> str:
    return f"{part / whole * 100:.1f}%" if whole else "—"


def totals(report: dict[str, Any]) -> dict[str, Any]:
    out = {"days": len(report["plans"]), "fields_add": 0, "fields_same": 0, "fields_conflict": 0,
           "days_with_adds": 0, "days_with_conflicts": 0, "unresolved": 0, "unresolved_text": 0,
           "overrides_inherited": 0, "user_touched_days": 0}
    for key in ("rows", "rows_resolved", "plates", "plates_resolved", "drivers", "drivers_linked",
                "drivers_text", "drivers_ambiguous"):
        out[key] = 0
    for plan in report["plans"]:
        out["fields_add"] += len(plan.added)
        out["fields_same"] += plan.same
        out["fields_conflict"] += len(plan.conflicts)
        out["days_with_adds"] += bool(plan.added)
        out["days_with_conflicts"] += bool(plan.conflicts)
        out["user_touched_days"] += bool(plan.user_touched)
        out["overrides_inherited"] += sum(op.overrides_inherited for op in plan.added)
        hard = [u for u in plan.unresolved if u.get("severity") != "text"]
        out["unresolved"] += len(hard)
        out["unresolved_text"] += len(plan.unresolved) - len(hard)
        for key, value in plan.stats.items():
            out[key] += value
    return out


# ───────────────────────── تقرير المعاينة (عربي) ─────────────────────────

PATH_LABELS = {"vehicle_id": "المركبة", "driver": "السائق", "attached": "الملحق", "vehicles": "مركبات الخدمة",
               "plate_text": "نص اللوحة", "type_text": "نص النوع", "driver_text": "نص السائق",
               "basic_entry_id": "الخدمة الأساسية", "rows": "الصفوف"}


def _show(value: Any, data: dict[str, Any]) -> str:
    """عرض قيمة حقل للإنسان (مركبة → لوحتها، سائق → اسمه)."""
    vehicles = {v.id: v.plate for v in VehicleRepo(data).all()}
    people = {p.id: p.name for p in ConscriptRepo(data).all()}
    people.update({p["id"]: p["name"] for p in (data.get("personnel") or []) if isinstance(p, dict)})

    def one(item: Any) -> str:
        if isinstance(item, dict):
            if "vehicle_id" in item:
                return vehicles.get(item["vehicle_id"], item["vehicle_id"])
            if item.get("kind") in ("personnel", "conscript"):
                return people.get(item.get("id"), str(item.get("id")))
            if item.get("kind") == "text":
                return f"«{item.get('name')}»"
            if "assignment_id" in item:
                return str(item["assignment_id"])
            if "name" in item:
                return str(item["name"])
        return str(item)
    if isinstance(value, list):
        if value and isinstance(value[0], list):
            return "؛ ".join("/".join(map(str, row)) for row in value)
        return "، ".join(one(i) for i in value)
    if isinstance(value, str) and value in vehicles:
        return vehicles[value]
    return one(value)


def _cell(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def render_preview(report: dict[str, Any], data: dict[str, Any], mode: str = "dry-run",
                   after_rate: str | None = None) -> str:
    t = totals(report)
    lines = ["# معاينة استيراد يومية الحملة", "",
             f"النطاق: {report['range'][0]} إلى {report['range'][1]} — {t['days']} يوم "
             f"({report['files']} ملف أرشيف). الوضع: **{mode}** — المعاينة دي ما كتبتش على أي بيانات حقيقية.", "",
             "## الإجماليات", "",
             "| البند | العدد |", "|---|---|",
             f"| أيام فيها حقول هتتضاف | {t['days_with_adds']} |",
             f"| حقول هتتضاف | {t['fields_add']} |",
             f"| منها بتغيّر قيمة موروثة من يوم سابق | {t['overrides_inherited']} |",
             f"| حقول مطابقة بالفعل (مفيش تغيير) | {t['fields_same']} |",
             f"| حقول متعارضة (اتسابت كما هي) | {t['fields_conflict']} في {t['days_with_conflicts']} يوم |",
             f"| أيام عليها تعديل مستخدم مسجّل في change_log | {t['user_touched_days']} |",
             f"| صفوف أرشيف (ارتكازات + توصيل) | {t['rows']} — محلولة {t['rows_resolved']} ({_pct(t['rows_resolved'], t['rows'])}) |",
             f"| لوحات | {t['plates']} — محلولة لمركبة {t['plates_resolved']} ({_pct(t['plates_resolved'], t['plates'])}) |",
             f"| سائقين | {t['drivers']} — مربوط بشخص {t['drivers_linked']} ({_pct(t['drivers_linked'], t['drivers'])})، "
             f"نص حر {t['drivers_text']}، غامض {t['drivers_ambiguous']} |",
             f"| عناصر غير محلولة (محتاجة قرار) | {t['unresolved']} |",
             f"| سائقين محفوظين كنص (للعلم) | {t['unresolved_text']} |"]
    if after_rate:
        lines += ["", f"نسبة تطابق الحملة بعد الاستيراد: {after_rate}"]
    if report["errors"]:
        lines += ["", "## ملفات اتعذرت قراءتها", ""]
        lines += [f"- {e['day']}: {e['error']} ({e['path']})" for e in report["errors"]]

    unresolved_all = [u for plan in report["plans"] for u in plan.unresolved if u.get("severity") != "text"]
    if unresolved_all:
        from collections import Counter
        lines += ["", "## غير المحلول — ملخص بالسبب", "", "| النوع | السبب | الصف | مرات |", "|---|---|---|---|"]
        counts = Counter((u["kind"], u["reason"], u["row"]) for u in unresolved_all)
        for (kind, reason, row), n in counts.most_common(60):
            lines.append(f"| {kind} | {_cell(reason)} | {_cell(row)} | {n} |")
    lines += ["", "## تفاصيل كل يوم", ""]
    for plan in report["plans"]:
        hard = [u for u in plan.unresolved if u.get("severity") != "text"]
        s = plan.stats
        lines += [f"### {plan.day}", "",
                  f"- ملف: `{Path(plan.source).name}`",
                  f"- هتتضاف: {len(plan.added)} حقل | مطابقة: {plan.same} | تعارض: {len(plan.conflicts)} | غير محلول: {len(hard)}",
                  f"- صفوف محلولة {s['rows_resolved']}/{s['rows']}، لوحات {s['plates_resolved']}/{s['plates']}، "
                  f"سائقين: مربوط {s['drivers_linked']} / نص {s['drivers_text']} / غامض {s['drivers_ambiguous']}"]
        if plan.user_touched:
            lines.append(f"- تعديلات مستخدم مسجلة: {'، '.join(plan.user_touched[:5])}")
        if plan.added:
            lines += ["", "| الحقل | الصف (الأرشيف) | القيمة | يغيّر موروث؟ |", "|---|---|---|---|"]
            for op in plan.added:
                lines.append(f"| {'/'.join(op.path[:2])} {PATH_LABELS.get(op.path[-1], op.path[-1])} | "
                             f"{_cell(op.row)} | {_cell(_show(op.value, data))} | {'نعم' if op.overrides_inherited else ''} |")
        if plan.conflicts:
            lines += ["", "تعارضات (اتسابت):", "", "| الحقل | الصف | الأرشيف | الحالي في النظام |", "|---|---|---|---|"]
            for op in plan.conflicts:
                lines.append(f"| {'/'.join(op.path[:2])} {PATH_LABELS.get(op.path[-1], op.path[-1])} | {_cell(op.row)} | "
                             f"{_cell(_show(op.value, data))} | {_cell(_show(op.current, data))} |")
        if plan.unresolved:
            lines += ["", "غير محلول:", ""]
            for u in plan.unresolved:
                extra = u.get("plate") or u.get("driver") or ""
                tag = " (نص)" if u.get("severity") == "text" else ""
                lines.append(f"- {u['kind']}{tag}: {u['row']} — {u['reason']}" + (f" [{extra}]" if extra else ""))
        lines.append("")
    return "\n".join(lines) + "\n"

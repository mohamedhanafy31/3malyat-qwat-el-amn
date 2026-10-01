"""TRANSFORM: بيبني كل يوم مستورد بنفس شكل اليومين المرجعيين (1-9 و2-9-2026).

المدخلات: سجلات normalize (السطر = رقم الملاحظة في resolve)، خريطة الهويات
المقترحة، جدول المرادفات والأحداث (aliases)، وأحكام validate. المخرجات في
مجلد staging بس — ولا حاجة بتتكتب على البيانات الفعلية (دي شغلة STORE):

- transform/days/<date>.json: ملف اليوم بنفس مفاتيح ملف اليوم في data/days
  (assignments / officer_states / afraad_basic / counts / assignment_seq / import).
- transform/core_delta.json: عمليات مُعرّفة بمفاتيح طبيعية على الأشخاص والتاريخ
  والراحات وسجل القيادة والقوائم المرجعية.
- import/provenance/YYYY/MM/DD.json: مصدر كل قيمة (ملف، بصمة، جدول/صف، نص خام، قاعدة).

قاعدة عامة: الدليل الناقص أو الملتبس ما بيتخمّنش — بيتساب فاضي وبيتسجل عنصر مراجعة.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from backend.afraad import BASIC_SERVICES
from backend.constants import (
    SECTION_ADMIN_WORK, SECTION_BASIC, SECTION_GREAT, SECTION_OCCASIONAL,
    RANK_ORDER, SECTION_SECURITY, SECTION_SUBCAMP, SECTION_TARGETS, TARGETS_FIRST,
)
from backend.text import norm

from .aliases import (
    _canonical_board_section, _event_title, _instruction_phrase, _non_service_phrase,
    build_vocabulary, propose_alias, role_sections, service_key,
)
from .apply import grade_family
from .ledger import Ledger, atomic_write_json, atomic_write_jsonl
from .textnorm import clean_text

VERSION = "2"
PROTECTED = {"2026-09-01", "2026-09-02"}
BOARD_START = "2024-10-30"

CANONICAL_ORDER = {SECTION_BASIC, SECTION_OCCASIONAL, SECTION_TARGETS, SECTION_SUBCAMP, SECTION_GREAT,
                   SECTION_SECURITY, SECTION_ADMIN_WORK, "الراحات", "التقصيرات", "الخوارج"}
ROLE_SLOTS = {
    SECTION_SUBCAMP: "نوبتجي المعسكر الفرعي",
    SECTION_GREAT: "ضابط عظيم الإدارة",
    SECTION_SECURITY: "ضابط أمن الإدارة",
}
# أقسام اللوحة اللي بتتحسب من حالة الضباط — مش بتتخزن كتكليفات
COMPUTED_SECTIONS = {SECTION_ADMIN_WORK, "الراحات", "التقصيرات", "الخوارج"}
_COMPUTED_KEYS = ("الراحات", "التقصير", "الخوارج", "خوارج", "عمل بالاداره", "عمل بالادارة")
STATUS_VALUES = {"انتداب", "غياب", "مرضي", "فرقة", "طارئة"}
_STATUS_ALIASES = {"فرقه": "فرقة", "طارئه": "طارئة", "اجازة طارئة": "طارئة", "اجازه طارئه": "طارئة",
                   "دورة": "فرقة", "دوره": "فرقة"}
_SHIFT_WORDS = {"صباحية", "ليلية"}
_DEFAULT_SHIFT = "صباحية"  # نفس DEFAULT_SHIFT في backend/duty.py
_SHIFT_TOKEN = r"(?:فتر[ةه]\s*)?(?:صباحي[ةه]|ليلي[ةه]|مسائي[ةه]|مسايي[ةه]|صباح|صبح|ليل[ةه]?)"
_ONLY_SHIFT_RE = re.compile(rf"^(?:{_SHIFT_TOKEN}|[+/\s]|\bو)+$")
# خلية فيها فرد (درجة + / أو رقم تليفون) مش اسم خدمة
_PERSON_LABEL_RE = re.compile(r"^\s*(?:م\s*\.?\s*ش|[اأ]\s*\.?\s*ش|رقيب|عريف|مساعد|مندوب|مراقب|شرطي|[اأ]مين|معاون)(?:\s*شرط[ةه])?(?:\s+(?:اول|أول|ثان|ثاني|ثالث|ممتاز))*\s*[/\\.]|01\d{9}")
_LETTERS_RE = re.compile(r"[\u0621-\u064a]")
_MEDICAL_POST = ("الخدمات الطبيه", "الخدمات الطبية", "العياده", "العيادة")
_SEARCH_POST = ("اداره البحث", "ادارة البحث", "إدارة البحث", "ادارة الب")
_DIRECTOR_POST = ("مدير الاداره", "مدير الإدارة", "مدير الادارة", "مدير اداره")
_DEPUTY_POST = ("وكيل الاداره", "وكيل الإدارة", "وكيل الادارة", "وكيل اداره")

# الأنواع اللي TRANSFORM محتاجها بس — الباقي بيتجاهل وقت القراءة عشان الذاكرة
_KEEP = {
    ("roster", "roster_row"), ("roster", "section"),
    ("board", "board_row"), ("board", "board_label"), ("board", "header"),
    ("afraad", "afraad_basic_row"), ("afraad", "afraad_emergency_row"), ("afraad", "afraad_subheading"),
    ("duty_list", "duty_row"), ("duty_list", "duty_service_line"), ("duty_list", "duty_time_heading"),
    ("counts", "counts_row"), ("counts_leader", "counts_row"),
    ("deployment", "deployment_row"), ("match", "match_row"),
}


# ---------- القراءة ----------

def _slim(index: int, record: dict[str, Any]) -> dict[str, Any]:
    normalized = record.get("normalized") or {}
    slim = {
        "i": index, "date": record["date"], "role": record["role"], "type": record["record_type"],
        "path": record.get("path", ""), "sha1": record.get("file_sha1", ""), "table": record.get("table_index"),
        "row": record.get("row_index"), "half": record.get("half"), "label": clean_text(record.get("label")),
        "manning": clean_text(record.get("manning")), "fields": record.get("fields") or {},
        "cells": [clean_text(value) for value in record.get("raw_cells") or []],
        "aligned": record.get("aligned") or {}, "block": record.get("block", ""),
        "section": clean_text(record.get("section")), "known_section": record.get("known_section"),
        "stale": bool(record.get("stale")),
        "shift": (normalized.get("shift") or {}).get("value") or [],
        "time": (normalized.get("time") or {}).get("value") or [],
        "party": (normalized.get("party") or {}).get("value") or [],
        "conscripts": normalized.get("conscripts") or {},
        "weapon": (normalized.get("weapons") or {}).get("value") or "",
    }
    people = []
    for person in normalized.get("people") or []:
        people.append({
            "kind": person.get("kind"), "name": (person.get("name") or {}).get("value", ""),
            "rank": (person.get("rank") or person.get("grade") or {}).get("value", ""),
            "shift": person.get("shift", ""), "phones": (person.get("phones") or {}).get("value") or [],
        })
    slim["people"] = people
    officer = normalized.get("officer")
    if officer:
        daily = officer.get("daily") or {}
        rest = (officer.get("rest") or {}).get("value") or {}
        slim["officer"] = {
            "name": (officer.get("name") or {}).get("value", ""),
            "rank": (officer.get("rank") or {}).get("value", ""),
            "qualifier": (officer.get("rank") or {}).get("qualifier", ""),
            "code": (officer.get("seniority") or {}).get("value", ""),
            "post": (officer.get("post") or {}).get("value", ""),
            "note": clean_text(daily.get("raw") or daily.get("value") or ""),
            "taqseera": bool(daily.get("taqseera")), "status": daily.get("status", ""),
            "leaves": daily.get("leaves") or [], "services": daily.get("services") or [],
            "rest_system": rest.get("rest_system", ""), "rest_day": rest.get("rest_day", ""),
        }
    return slim


def load_records(path: Path, start: str | None, end: str | None) -> dict[str, list[dict[str, Any]]]:
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with path.open(encoding="utf-8") as stream:
        for index, line in enumerate(stream):
            record = json.loads(line)
            key = (record.get("role"), record.get("record_type"))
            if key not in _KEEP:
                continue
            date = record["date"]
            if (start and date < start) or (end and date > end):
                continue
            by_date[date].append(_slim(index, record))
    return by_date


def load_verdicts(path: Path) -> dict[tuple[str, str, str], str]:
    verdicts: dict[tuple[str, str, str], str] = {}
    if not path.exists():
        return verdicts
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            if record.get("source_record_type") == "document":
                verdicts[(record["date"], record["role"], record["path"])] = record.get("verdict", "ok")
    return verdicts


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


# ---------- مساعدات ----------

def _status(value: str) -> str:
    value = clean_text(value)
    value = _STATUS_ALIASES.get(value, value)
    return value if value in STATUS_VALUES else ""


def _first(values: Iterable[str]) -> str:
    return next((clean_text(value) for value in values if clean_text(value)), "")


def _is_computed(label_key: str) -> bool:
    flat = label_key.replace(" ", "")
    return any(key.replace(" ", "") in flat for key in _COMPUTED_KEYS)


def _edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def _nearest(index: dict[str, list[dict[str, Any]]], key: str) -> list[dict[str, Any]]:
    if key in index:
        return index[key]
    close = [other for other in index if other and abs(len(other) - len(key)) <= 2 and _edit_distance(other, key) <= 2]
    return index[close[0]] if len(close) == 1 else []


def _pick(candidates: list[dict[str, Any]], time: str) -> dict[str, Any] | None:
    """نفس الساعة أولًا، وإلا نفس الوردية، وإلا المرشح الوحيد — الساعة بتختلف بين الوثائق."""
    if not candidates:
        return None
    exact = [row for row in candidates if row["time"] and time and row["time"].replace(" ", "") == time.replace(" ", "")]
    if exact:
        return exact[0]
    free = [row for row in candidates if not row["time"] or not time]
    if free:
        return free[0]
    shift = _shift_from_time(time)
    same_shift = [row for row in candidates if row["shift"] == shift]
    if len(same_shift) == 1:
        return same_shift[0]
    return candidates[0] if len(candidates) == 1 else None


def _count_int(value: Any) -> int:
    # خلايا الطوارئ المزاحة بتحط رقم التليفون مكان العدد — عدد معقول بس
    match = re.search(r"(?<!\d)\d{1,3}(?!\d)", str(value or ""))
    return int(match.group()) if match and int(match.group()) <= 500 else 0


def _party(values: Iterable[str]) -> str:
    # الجهة الحقيقية نص؛ الخلية المزاحة بتجيب تليفون/عدد بدلها
    return next((clean_text(value) for value in values if clean_text(value)
                 and not re.fullmatch(r"[\d\s+/()-]+", clean_text(value))
                 and not re.search(r"\d{7,}", clean_text(value))), "")


# أنواع وحدات بتتكتب جنب «وحدة» في خانة القوام (مش تسليح ولا فئة زيادة)
_UNIT_TYPES = {"رياضي", "فض", "وحدة فض", "خفيفة", "حفظ نظام", "طلبة"}
_TIME_RAW_RE = re.compile(r"(?<!\d)\d{1,2}(?:\s*[:.]\s*\d{1,2})?\s*[صمظ](?!\w)")


def _time_text(record: dict[str, Any]) -> str:
    """الساعة بكتابة الوثيقة («10 م» مش «10م») — نفس قاعدة normalize_time."""
    for text in (record.get("label") or "", *(record.get("cells") or [])):
        match = _TIME_RAW_RE.search(text)
        if match:
            return clean_text(match.group())
    return _first(record["time"])


def _person_label(label: str) -> bool:
    # بدون تشكيل بس — norm بيشيل «/» و«.» اللي بيفرقوا «ا.ش/ فلان» عن اسم خدمة
    flat = re.sub(r"[\u064b-\u0652]", "", clean_text(label))
    return bool(_PERSON_LABEL_RE.search(flat) or (_RANK_PREFIX_RE.match(flat) and "/" in flat))


class Context:
    """كل اللي اليوم محتاجه من مراحل سابقة — بيتبني مرة واحدة للدفعة."""

    def __init__(self, ledger: Ledger, core: dict[str, Any]):
        self.ledger = ledger
        self.core = core
        id_map = json.loads(ledger.staging_path("id_map.proposed").with_suffix(".json").read_text(encoding="utf-8"))
        self.officer_ids: dict[str, str] = id_map.get("officers", {})
        self.person_ids: dict[str, str] = id_map.get("personnel", {})
        self.vocabulary = build_vocabulary(ledger.data_dir)
        self.alias_rows = {row["key"]: row for row in _read_csv(ledger.root / "review" / "aliases.csv")}
        self.events: dict[str, list[str]] = defaultdict(list)
        for row in _read_csv(ledger.root / "review" / "events.csv"):
            if row["event title"] not in self.events[row["date"]]:
                self.events[row["date"]].append(row["event title"])
        self.verdicts = load_verdicts(ledger.staging_path("validate"))
        self.known_sections = {row.get("section", "") for row in self.alias_rows.values()} | set(ROLE_SLOTS) | {
            SECTION_BASIC, SECTION_OCCASIONAL, SECTION_TARGETS}
        self._alias_cache: dict[str, dict[str, Any]] = {}
        # أسماء الخدمات زي ما النظام نفسه بيكتبها (من أيام 2026 الموجودة) — مفضّلة
        # على صيغة يومية الأفراد («تدخل سريع» مش «التدخل السريع»)
        names: dict[str, Counter] = defaultdict(Counter)
        info: dict[str, dict[str, Any]] = {}
        for path in sorted((ledger.data_dir / "days").glob("*/*/*.json")):
            day = json.loads(path.read_text(encoding="utf-8"))
            if day.get("import"):
                continue
            for row in day.get("assignments", []):
                if row.get("section") in ROLE_SLOTS or row.get("section") == SECTION_TARGETS:
                    continue
                # «ارتكاز بتروجيت ليل» اسم قديم فيه الوردية — الوردية حقل منفصل
                name = _strip_shift_word(row.get("name", ""))
                key = service_key(name, self.vocabulary)
                names[key][name] += 1
                meta = info.setdefault(name, {"kind": row.get("kind") or "خارجية",
                                              "counts_in_summary": row.get("counts_in_summary", True),
                                              "sections": Counter()})
                meta["sections"][row.get("section", "")] += 1
        self.system_names = {key: counter.most_common(1)[0][0] for key, counter in names.items()}
        for meta in info.values():
            meta["section"] = meta.pop("sections").most_common(1)[0][0]
        self.system_info = info
        system_targets: list[str] = []
        for path in sorted((ledger.data_dir / "days").glob("*/*/*.json")):
            for row in json.loads(path.read_text(encoding="utf-8")).get("assignments", []):
                if row.get("section") == SECTION_TARGETS and row.get("name") and row["name"] not in system_targets:
                    system_targets.append(row["name"])
        alias_targets = sorted({row["proposed canonical"] for row in self.alias_rows.values()
                                if row.get("category") == "target" and "بهدف" not in row["proposed canonical"]
                                and row.get("confidence") in {"high", "medium"}})
        self.system_targets = system_targets
        self.target_names = system_targets + [name for name in alias_targets if name not in system_targets]

    def alias(self, phrase: str) -> dict[str, Any]:
        phrase = clean_text(phrase)
        cached = self._alias_cache.get(phrase)
        if cached is not None:
            return cached
        key = service_key(phrase, self.vocabulary)
        row = self.alias_rows.get(key)
        if row:
            result = {"key": key, "canonical": row["proposed canonical"], "confidence": row["confidence"],
                      "category": row["category"], "kind": row["kind"], "section": row["section"],
                      "counts_in_summary": str(row.get("counts_in_summary", "true")).lower() != "false"}
        else:
            proposal = propose_alias(phrase, self.vocabulary)
            result = {"key": key, "canonical": proposal["canonical"], "confidence": proposal["confidence"],
                      "category": proposal["category"], "kind": proposal["kind"], "section": proposal["section"],
                      "counts_in_summary": bool(proposal["counts_in_summary"])}
        self._alias_cache[phrase] = result
        return result

    def service_name(self, alias: dict[str, Any]) -> tuple[str, str, bool]:
        """الاسم المعتمد + النوع + الحساب في الإجمالي، بتفضيل اسم النظام لو موجود."""
        for key in (alias["key"], service_key(alias["canonical"], self.vocabulary)):
            name = self.system_names.get(key)
            if name:
                meta = self.system_info.get(name, {})
                return name, meta.get("kind") or alias["kind"] or "خارجية", bool(meta.get("counts_in_summary", True))
        return _strip_shift_word(alias["canonical"]), alias["kind"] or "خارجية", alias["counts_in_summary"]

    def service_section(self, name: str, fallback: str) -> str:
        section = (self.system_info.get(name) or {}).get("section")
        return section if section in {SECTION_BASIC, SECTION_OCCASIONAL} else fallback

    def target_name(self, label: str) -> str:
        key = service_key(label, self.vocabulary).replace("هدف ", "").strip()
        if not key:
            return ""
        contained = []
        for name in self.target_names:
            other = service_key(name, self.vocabulary).replace("هدف ", "").strip()
            if other == key:
                return name
            if other and (key in other.split() or key in other or other in key):
                contained.append(name)
        # أسماء النظام قبل المرادفات، والأقصر الأدق («السخنة» ← «كهرباء السخنة»)
        contained.sort(key=lambda name: (name not in self.system_targets, len(name)))
        return contained[0] if contained else ""

    def usable(self, record: dict[str, Any]) -> bool:
        verdict = self.verdicts.get((record["date"], record["role"], record["path"]), "ok")
        return verdict != "quarantine" and not record["stale"]

    def officer_of_row(self, record: dict[str, Any]) -> str:
        key = f"{record['i']}:{record['date']}:{record['role']}:{record['table']}:{record['row']}"
        return self.officer_ids.get(key, "")

    def personnel_match(self, person: dict[str, Any]) -> str:
        """اسم فرد مختصر («م.ش/ السيد احمد») = أول كلمات اسم فرد واحد بس في النظام بنفس عائلة الدرجة."""
        if not hasattr(self, "_personnel_index"):
            # أفراد النظام + تجمعات الأرشيف اللي اتحسمت (NEW-IND): اسم مختصر بيطابق فرد قديم مش في
            # النظام وفرد في النظام بيبقى ملتبس وما بيتربطش
            self._personnel_index = [(item["id"], _tokens(item.get("name", "")), grade_family(item.get("role", "")))
                                     for item in self.core.get("personnel", [])]
            resolve_path = self.ledger.staging_path("resolve") if getattr(self, "ledger", None) else None
            known = {pid for pid, _, _ in self._personnel_index}
            if resolve_path is not None and resolve_path.exists():
                for line in resolve_path.read_text(encoding="utf-8").splitlines():
                    cluster = json.loads(line) if line.strip() else {}
                    pid = cluster.get("proposed_id") or ""
                    if cluster.get("identity_type") != "personnel" or not pid or pid in known:
                        continue
                    grade = (cluster.get("ranks_grades") or "").split(" (")[0]
                    for name in (cluster.get("names_seen") or "").split(" ; "):
                        if len(_tokens(name)) >= 3:
                            self._personnel_index.append((pid, _tokens(name), grade_family(grade)))
        tokens = _tokens(person.get("name", ""))
        if len(tokens) < 2:
            return ""
        family = grade_family(person.get("rank", ""))
        hits = {pid for pid, names, own in self._personnel_index
                if names[:len(tokens)] == tokens and (not family or not own or family == own)}
        return hits.pop() if len(hits) == 1 else ""

    def people_of(self, record: dict[str, Any]) -> list[tuple[dict[str, Any], str]]:
        result = []
        base = f"{record['i']}:{record['date']}:{record['role']}:{record['table']}:{record['row']}"
        for index, person in enumerate(record["people"]):
            table = self.officer_ids if person["kind"] == "officer" else self.person_ids
            result.append((person, table.get(f"{base}:{index}:0", "")))
        return result


# ---------- بناء اليوم ----------

class DayBuilder:
    def __init__(self, date: str, records: list[dict[str, Any]], ctx: Context):
        self.date = date
        self.ctx = ctx
        self.records = records
        self.rows: list[dict[str, Any]] = []
        self.provenance: dict[str, Any] = {"date": date, "assignments": {}, "officer_states": {},
                                           "afraad_basic": {}, "counts": []}
        self.review: list[dict[str, Any]] = []
        self.sources: dict[tuple[str, str], str] = {}
        self.derived = False
        self.observations: dict[str, Any] = {"officers": {}, "personnel": {}}
        self.roster_names: list[tuple[str, list[str]]] = []
        self.target_officers: dict[str, list[str]] = defaultdict(list)
        self._afraad_records: dict[str, dict[str, Any]] = {}

    # --- مصادر ---
    def _use(self, record: dict[str, Any]) -> None:
        self.sources[(record["role"], record["path"])] = record["sha1"]

    def _src(self, record: dict[str, Any], rule: str, raw: str = "") -> dict[str, Any]:
        return {"path": record["path"], "sha1": record["sha1"], "table": record["table"], "row": record["row"],
                "rule": rule, "raw": raw or " | ".join(value for value in record["cells"] if value)}

    def _of(self, role: str, *types: str) -> list[dict[str, Any]]:
        return [record for record in self.records
                if record["role"] == role and record["type"] in types and self.ctx.usable(record)]

    def _roster_rows(self) -> list[dict[str, Any]]:
        # أول صف بعد عنوان «الحراسات المشددة/الخوارج» بيتسجل نوعه section وفيه بيانات ضابط
        rows = self._of("roster", "roster_row", "section")
        return sorted(rows, key=lambda r: (r["table"] or 0, r["row"] or 0))

    # --- officer_states ---
    def officer_states(self) -> dict[str, Any]:
        states: dict[str, Any] = {}
        section = "القوة"
        for record in self._roster_rows():
            officer = record.get("officer") or {}
            if record["type"] == "section":
                flat = norm(record["section"] or " ".join(record["cells"]))
                if "الحراسات" in flat:
                    section = "الحراسات المشددة"
                elif "خوارج" in flat or "خوراج" in flat:
                    section = "الخوارج"
                if not officer.get("name"):
                    continue
            officer_id = self.ctx.officer_of_row(record)
            if not officer_id:
                if officer.get("name"):
                    self.review.append({"date": self.date, "type": "unresolved_roster_officer",
                                        "name": officer.get("name"), "source": self._src(record, "roster")})
                continue
            self._use(record)
            if officer_id in states or officer_id in self.observations["officers"]:
                self.review.append({"date": self.date, "type": "duplicate_roster_officer", "id": officer_id,
                                    "source": self._src(record, "roster")})
                continue
            self.roster_names.append((officer_id, _tokens(_RANK_PREFIX_RE.sub("", officer.get("name", "")))))
            self.provenance.setdefault("roster", []).append(officer_id)
            state: dict[str, Any] = {}
            if officer.get("note"):
                state["note"] = officer["note"]
            if officer.get("taqseera"):
                state["taqseera"] = True
            status = _status(officer.get("status", ""))
            if status:
                state["status"] = status
            if state:
                states[officer_id] = state
                self.provenance["officer_states"][officer_id] = self._src(record, "roster_row", officer.get("note", ""))
            for part in officer.get("services") or []:
                if re.search(r"بهدف", norm(part)):
                    target = self.ctx.target_name(re.sub(r"^.*?بهدف\s*", "", part))
                    if target:
                        self.target_officers[target].append(officer_id)
            post = officer.get("post", "")
            self.observations["officers"][officer_id] = {
                "rank": officer.get("rank", ""), "qualifier": officer.get("qualifier", ""),
                "code": officer.get("code", ""), "post": post, "section": section,
                "rest_system": officer.get("rest_system", ""), "rest_day": officer.get("rest_day", ""),
                "search_attached": any(key in norm(post) or key in post for key in _SEARCH_POST),
                "leaves": officer.get("leaves", []), "note": officer.get("note", ""),
                "services": officer.get("services", []), "name": officer.get("name", ""),
            }
        return states

    # --- الأشخاص ---
    def _roster_match(self, text: str) -> str:
        """اسم مختصر على اللوحة («م.اول/عمر خالد») مقابل ضباط يومية نفس اليوم."""
        tokens = _tokens(_RANK_PREFIX_RE.sub("", text))
        if not tokens:
            return ""
        hits = [officer_id for officer_id, names in self.roster_names
                if names and names[0] == tokens[0] and all(token in names for token in tokens[1:])]
        return hits[0] if len(set(hits)) == 1 else ""

    def _new_row(self, name: str, section: str, **over: Any) -> dict[str, Any]:
        row = {"section": section, "name": name, "kind": "", "shift": "", "officer_ids": [], "personnel_ids": [],
               "conscripts": [], "conscript_count": 0, "weapon": "", "time": "", "party": "",
               "counts_in_summary": True, "note": ""}
        row.update(over)
        self.rows.append(row)
        return row

    def _people_into(self, row: dict[str, Any], record: dict[str, Any], manning_text: str) -> None:
        unresolved = []
        for person, identifier in self.ctx.people_of(record):
            if not identifier and person["kind"] == "officer":
                identifier = self._roster_match(person.get("name", ""))
            elif not identifier:
                identifier = self.ctx.personnel_match(person)
                if identifier:
                    self.review.append({"date": self.date, "type": "personnel_prefix_match", "id": identifier,
                                        "raw": f"{person.get('rank', '')}/ {person.get('name', '')}"})
            if identifier:
                target = row["officer_ids"] if person["kind"] == "officer" else row["personnel_ids"]
                if identifier not in target:
                    target.append(identifier)
                if person["kind"] == "officer":
                    # ظهور على اللوحة/الكشوف — بيمد مدى الخدمة حتى لو مش في يومية الضباط
                    self.observations.setdefault("officer_refs", {}).setdefault(identifier, {
                        "name": person.get("name", ""), "rank": person.get("rank", "")})
                if person["kind"] != "officer":
                    self.observations["personnel"].setdefault(identifier, {
                        "grade": person.get("rank", ""), "name": person.get("name", ""),
                        "phones": person.get("phones", [])})
            else:
                unresolved.append(person.get("name", ""))
        if not record["people"] and manning_text:
            # المطبّع ما لقاش أشخاص (رتبة ملزوقة في الاسم، أو وثيقة مش متطبّعة) — مطابقة مباشرة
            for part in re.split(r"\s*\+\s*", manning_text):
                if _RANK_PREFIX_RE.match(part):
                    identifier = self._roster_match(part)
                    if identifier:
                        if identifier not in row["officer_ids"]:
                            row["officer_ids"].append(identifier)
                    else:
                        unresolved.append(part)
                elif _person_label(part):
                    grade, _, name = part.partition("/")
                    identifier = self.ctx.personnel_match({"name": clean_text(name), "rank": clean_text(grade)})
                    if identifier:
                        if identifier not in row["personnel_ids"]:
                            row["personnel_ids"].append(identifier)
                        self.review.append({"date": self.date, "type": "personnel_prefix_match", "id": identifier,
                                            "raw": part})
                    else:
                        unresolved.append(part)
        if unresolved and manning_text and manning_text not in row["note"]:
            # الاسم اللي ما اتحسمش ما بيضيعش — بيفضل نصه في الملاحظة
            row["note"] = clean_text(f"{row['note']} {manning_text}")

    def _conscripts_into(self, row: dict[str, Any], record: dict[str, Any]) -> None:
        """«فرد» = فرد من القوة (القائم بالخدمة) مش مجند، و«وحدة (7 مجند)» = وحدة حجمها 7 مش فئتين."""
        conscripts = record.get("conscripts") or {}
        sizes = [int(value) for value in re.findall(r"\(\s*(\d+)\s*مج", conscripts.get("raw") or "")]
        entries: list[dict[str, Any]] = []
        for entry in conscripts.get("value") or []:
            kind, count = entry.get("class", ""), int(entry.get("count") or 0)
            if kind in {"فرد", "سائق"}:
                continue
            if kind == "مج" and count in sizes and entries:
                entries[-1]["size"] = count
                sizes.remove(count)
                continue
            same = next((entry for entry in entries if entry["class"] == kind and "size" not in entry), None)
            if same is not None and kind not in _UNIT_TYPES and kind != "وحدة":
                same["count"] += count  # «+ مج ... فرد + مج» = مجندين اتنين من نفس الفئة
                continue
            entries.append({"class": kind, "count": count})
        unit = next((entry for entry in entries if entry["class"] == "وحدة"), None)
        typed = [entry for entry in entries if entry["class"] in _UNIT_TYPES and entry["count"] == 1]
        if unit is not None and len(typed) == 1:
            # «وحدة (10 مجند رياضي)» = وحدة واحدة نوعها رياضي، مش وحدتين
            if "size" in unit:
                typed[0]["size"] = unit["size"]
            entries.remove(unit)
        if entries and not row["conscripts"]:
            row["conscripts"] = [{"class": entry["class"], "count": entry["count"]} for entry in entries]
        total = sum(entry.get("size", entry["count"]) for entry in entries)
        if total and total <= 500 and not row["conscript_count"]:
            row["conscript_count"] = total

    # --- assignments ---
    def _service_row(self, label: str, section: str, record: dict[str, Any], rule: str) -> list[dict[str, Any]]:
        if section == SECTION_TARGETS:
            name = self.ctx.target_name(label) or (TARGETS_FIRST if "مشرف" in norm(label) else "")
            if not name:
                alias = self.ctx.alias(label)
                name = alias["canonical"]
            row = self._new_row(name, SECTION_TARGETS, kind="حراسات", shift="")
            self._people_into(row, record, record["manning"])
            roster = self.target_officers.get(name, [])
            if len(set(roster)) == 1 and row["officer_ids"] != roster[:1]:
                # يومية الضباط هي المرجع لمين في الهدف؛ اللوحة أحيانًا منسوخة غلط
                if row["officer_ids"]:
                    self.review.append({"date": self.date, "type": "target_officer_from_roster", "target": name,
                                        "board": list(row["officer_ids"]), "roster": roster[:1]})
                row["officer_ids"] = roster[:1]
            self.provenance["assignments"][str(len(self.rows) - 1)] = self._src(record, rule, f"{label} | {record['manning']}")
            return [row]
        if _person_label(label) or not _LETTERS_RE.search(label):
            self.review.append({"date": self.date, "type": "not_a_service_label", "section": section,
                                "raw": f"{label} | {record['manning']}", "path": record["path"]})
            return []
        alias = self.ctx.alias(label)
        if alias["category"] in {"admin_work", "other"}:
            return []
        name, kind, counted = self.ctx.service_name(alias)
        if not name:
            self.review.append({"date": self.date, "type": "empty_service_name", "section": section,
                                "raw": f"{label} | {record['manning']}", "path": record["path"]})
            return []
        shifts = [value for value in record["shift"] if value in _SHIFT_WORDS] or [""]
        time = _time_text(record)
        made = []
        for shift in shifts:
            if not shift and section not in {SECTION_BASIC}:
                shift = _shift_from_time(time) or "صباحية"
            weapon = " + ".join(token for token in (record.get("weapon") or "").split(" + ")
                                 if token and token not in _UNIT_TYPES)
            row = self._new_row(name, section, kind=kind, shift=shift, counts_in_summary=counted,
                                time=time, party=_party(record["party"]), weapon=weapon)
            self._people_into(row, record, record["manning"])
            self._conscripts_into(row, record)
            self.provenance["assignments"][str(len(self.rows) - 1)] = self._src(record, rule, f"{label} | {record['manning']}")
            made.append(row)
        return made

    def _section_for_label(self, label: str, events: list[str]) -> str:
        key = norm(label)
        if _is_computed(key):
            return SECTION_ADMIN_WORK
        display = _display_section(key)
        if display:
            return display
        title = _event_title(label, set(events))
        if title in events:
            return title
        return events[0] if len(events) == 1 else title

    def board_assignments(self) -> bool:
        if self.date < BOARD_START:
            return False
        board = self._of("board", "board_row", "board_label")
        if not board:
            return False
        events = self.ctx.events.get(self.date, [])
        halves: dict[int, list[dict[str, Any]]] = defaultdict(list)
        heading: dict[str, tuple[str, str]] = {}
        for record in board:
            halves[int(record.get("half") or 0)].append(record)
        for half in sorted(halves):
            section = SECTION_BASIC if half == 0 else SECTION_TARGETS
            previous_slot = None
            previous_label = ""
            for record in sorted(halves[half], key=lambda r: (r["table"] or 0, r["row"] or 0)):
                self._use(record)
                label = record["label"]
                key = norm(label)
                slot_row = section in ROLE_SLOTS and "فتره" in key
                if record["type"] == "board_label" and _person_label(label):
                    # اسم ضابط لوحده (قايمة راحات/خوارج) مش عنوان قسم
                    continue
                if (not slot_row and section not in ROLE_SLOTS and section != SECTION_TARGETS and previous_label
                        and record["manning"] and _ONLY_SHIFT_RE.match(key)):
                    # «ليل» تحت «X صبح»: خلية الخدمة مدموجة رأسيًا — نفس الخدمة بالوردية دي
                    self._service_row(f"{_strip_shift_word(previous_label)} {label}", section, record, "board_row_merged")
                    continue
                if not slot_row and (record["type"] == "board_label" or (not record["manning"] and record["known_section"])):
                    section = self._section_for_label(label, events)
                    previous_slot = None
                    previous_label = ""
                    if section not in CANONICAL_ORDER:
                        # «مباراة ... باستاد الجيش 2:30م»: ساعة الحدث ومكانه لكل صفوفه
                        time = _time_text(record)
                        place = _party(re.sub(_TIME_RAW_RE, "", value) for value in record["party"])
                        heading[section] = (time, place)
                    continue
                if section in COMPUTED_SECTIONS or not label:
                    continue
                if section in ROLE_SLOTS:
                    shift = "ليلية" if "ليل" in key or "مسائ" in key else "صباحية"
                    row = self._new_row(ROLE_SLOTS[section], section, kind="داخلية", shift=shift,
                                        counts_in_summary=ROLE_SLOTS[section] != "نوبتجي المعسكر الفرعي")
                    self._people_into(row, record, record["manning"])
                    if not row["officer_ids"] and not record["manning"] and previous_slot and previous_slot["officer_ids"]:
                        # خلية الفترة الليلية مدموجة رأسيًا مع الصباحية = نفس الضابط
                        row["officer_ids"] = list(previous_slot["officer_ids"])
                    if not row["officer_ids"]:
                        self.rows.pop()
                        continue
                    previous_slot = row
                    self.provenance["assignments"][str(len(self.rows) - 1)] = self._src(record, "board_role_slot")
                    continue
                if _non_service_phrase(key) or _instruction_phrase(key):
                    continue
                made = self._service_row(label, section, record, "board_row")
                if made:
                    previous_label = label
                    time, place = heading.get(section, ("", ""))
                    for row in made:
                        row["time"] = row["time"] or time
                        row["party"] = row["party"] or place
                        if time and not row["shift"]:
                            row["shift"] = _shift_from_time(time)
        return True

    def _manob_section(self) -> str:
        """«منوب الإدارة» (قاعدة المستخدم): لو في نفس اليوم ضابط تاني على «ضابط عظيم» وضابط على «ضابط أمن»
        يبقى المنوب منوب أمن الإدارة (كتلة الأمن)، وإلا يبقى هو ضابط عظيم الإدارة."""
        great = security = False
        for record in self._roster_rows():
            for part in (record.get("officer") or {}).get("services") or []:
                key = norm(part)
                if re.search(r"منوب\s+(?:ال)?اداره", key):
                    continue
                roles = role_sections(key)
                great = great or SECTION_GREAT in roles
                security = security or SECTION_SECURITY in roles
        return SECTION_SECURITY if great and security else SECTION_GREAT

    def derived_assignments(self) -> None:
        self.derived = True
        grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
        manob = self._manob_section()
        for record in self._roster_rows():
            officer_id = self.ctx.officer_of_row(record)
            officer = record.get("officer") or {}
            if not officer_id or not officer.get("name"):
                continue
            last = None
            for part in officer.get("services") or []:
                part_key = norm(part)
                if _ONLY_SHIFT_RE.match(part_key):
                    # «ارتكاز محكمة صباحية + ليلية»: الجزء التاني وردية لنفس الخدمة
                    if last is None or not _shifts_in(part):
                        continue
                    section, name, kind, counted = last
                    shifts = _shifts_in(part)
                    self._derived_row(grouped, record, part, officer_id, section, name, kind, counted, shifts)
                    continue
                if _non_service_phrase(part_key) or _instruction_phrase(part_key):
                    continue
                roles = role_sections(part_key)
                if roles and re.search(r"منوب\s+(?:ال)?اداره", part_key):
                    roles = [manob]
                if roles:
                    # «ضابط عظيم وأمن الإدارة» = الكتلتين؛ الكتلة من كلمات العبارة مش من أقرب خدمة بالاسم
                    shifts = _shifts_in(part) or [""]
                    for section in roles:
                        self._derived_row(grouped, record, part, officer_id, section, ROLE_SLOTS[section], "داخلية",
                                          section != SECTION_SUBCAMP, shifts)
                    last = (roles[0], ROLE_SLOTS[roles[0]], "داخلية", roles[0] != SECTION_SUBCAMP)
                    continue
                if re.search(r"بهدف", part_key) or part_key.startswith("مشرف الاهداف"):
                    name = self.ctx.target_name(re.sub(r"^.*?بهدف\s*", "", part)) or (
                        TARGETS_FIRST if part_key.startswith("مشرف الاهداف") else "")
                    if not name:
                        continue
                    section, shifts, kind, counted = SECTION_TARGETS, [""], "حراسات", True
                else:
                    alias = self.ctx.alias(part)
                    if alias["category"] in {"admin_work", "other", "event", "target"}:
                        continue
                    if alias["category"] == "role_slot":
                        section = alias["section"] if alias["section"] in ROLE_SLOTS else SECTION_SUBCAMP
                        name, kind, counted = ROLE_SLOTS[section], "داخلية", section != SECTION_SUBCAMP
                    else:
                        name, kind, counted = self.ctx.service_name(alias)
                        name = _strip_shift_word(name) or name
                        section = self.ctx.service_section(
                            name, alias["section"] if alias["section"] in {SECTION_BASIC, SECTION_OCCASIONAL} else SECTION_BASIC)
                    shifts = _shifts_in(part) or [""]
                if not name:
                    self.review.append({"date": self.date, "type": "empty_service_name", "section": section,
                                        "raw": part, "path": record["path"]})
                    continue
                last = (section, name, kind, counted)
                self._derived_row(grouped, record, part, officer_id, section, name, kind, counted, shifts)

    def _derived_row(self, grouped: dict[tuple[str, str, str], dict[str, Any]], record: dict[str, Any], part: str,
                     officer_id: str, section: str, name: str, kind: str, counted: bool, shifts: list[str]) -> None:
        for shift in shifts:
            identity = (section, name, shift)
            row = grouped.get(identity)
            if row is None:
                row = self._new_row(name, section, kind=kind, shift=shift, counts_in_summary=counted)
                grouped[identity] = row
                self.provenance["assignments"][str(len(self.rows) - 1)] = {
                    **self._src(record, "derived_from_roster", part), "derived": True}
            if officer_id not in row["officer_ids"]:
                row["officer_ids"].append(officer_id)

    def emergency_enrichment(self) -> None:
        index: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in self.rows:
            if row["section"] not in ROLE_SLOTS and row["section"] != SECTION_TARGETS:
                index[service_key(row["name"], self.ctx.vocabulary)].append(row)
        # صفوف الطوارئ في يومية الأفراد: خدمة | قائم | عدد | تسليح | انتظام — وأحيانًا زوجين في صف
        previous = None
        for record in self._of("afraad", "afraad_emergency_row"):
            cells = [value for value in record["cells"] if _LETTERS_RE.search(value or "")]
            if not cells or _instruction_phrase(norm(cells[0])) or _non_service_phrase(norm(cells[0])):
                continue
            self._use(record)
            label = clean_text((record["fields"] or {}).get("service")) or cells[0]
            if previous is not None and (label.startswith('"') or norm(label).startswith("ملاحظ")):
                # سطر ملاحظة تحت الخدمة — بيتحفظ في ملاحظتها
                previous["note"] = clean_text(f"{previous['note']} {label.strip(chr(34))}")
                continue
            if _person_label(label):
                if previous is not None:
                    # خلية الخدمة مدموجة رأسيًا — الفرد ده تبع الخدمة اللي فوقه
                    self._people_into(previous, record, label)
                else:
                    self.review.append({"date": self.date, "type": "not_a_service_label", "section": SECTION_OCCASIONAL,
                                        "raw": label, "path": record["path"]})
                continue
            alias = self.ctx.alias(label)
            if alias["category"] in {"admin_work", "other"}:
                continue
            name, kind, counted = self.ctx.service_name(alias)
            if not name:
                continue
            key = service_key(name, self.ctx.vocabulary)
            time = _time_text(record)
            candidates = _nearest(index, key)
            row = _pick(candidates, time)
            if row is None:
                row = self._new_row(name, SECTION_OCCASIONAL, kind=kind, counts_in_summary=counted,
                                    shift=_shift_from_time(time) or "صباحية")
                index[key].append(row)
                self.provenance["assignments"][str(len(self.rows) - 1)] = self._src(record, "afraad_emergency_row")
            previous = row
            if not row["time"] and time:
                row["time"] = time
            if not row["shift"] and time:
                row["shift"] = _shift_from_time(time)
            if not row["party"]:
                row["party"] = _party(record["party"])
            if not row["weapon"] and record.get("weapon"):
                row["weapon"] = record["weapon"]
            leader = clean_text((record["fields"] or {}).get("leader"))
            self._people_into(row, record, leader)
            count = _count_int((record["fields"] or {}).get("count"))
            if count and not row["conscript_count"]:
                row["conscript_count"] = count
        for record in self._of("duty_list", "duty_row"):
            fields = record["fields"] or {}
            label = clean_text(fields.get("الخدمة")) or _first(record["cells"])
            if not label or _non_service_phrase(norm(label)) or _instruction_phrase(norm(label)):
                continue
            alias = self.ctx.alias(label)
            name = self.ctx.service_name(alias)[0]
            time = clean_text(fields.get("ساعة الانتظام")) or _first(record["time"])
            candidates = _nearest(index, service_key(name, self.ctx.vocabulary))
            row = _pick(candidates, time)
            if row is None:
                continue
            self._use(record)
            if not row["time"] and time:
                row["time"] = time
            if not row["party"]:
                row["party"] = _party([fields.get("مكان الانتظام") or ""])
            count = _count_int(fields.get("عدد المجندين"))
            if count and not row["conscript_count"]:
                row["conscript_count"] = count

    def afraad_basic(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for record in sorted(self._of("afraad", "afraad_basic_row"), key=lambda r: (r["table"] or 0, r["row"] or 0)):
            label = _first(value for value in record["cells"] if not re.fullmatch(r"[\d\-\.]+", value))
            if not label:
                continue
            self._use(record)
            alias = self.ctx.alias(label)
            name = alias["canonical"]
            entry: dict[str, Any] = {"name": name}
            aligned = record.get("aligned") or {}
            for person, identifier in self.ctx.people_of(record):
                if person["kind"] == "officer":
                    continue
                slot = "night" if person.get("shift") == "ليلية" else "morning"
                if entry.get(f"{slot}_name"):
                    slot = "night" if slot == "morning" else "morning"
                if entry.get(f"{slot}_name"):
                    continue
                entry[f"{slot}_name"] = clean_text(f"{person.get('rank', '')}/ {person.get('name', '')}").strip("/ ")
                entry[f"{slot}_phone"] = _first(person.get("phones") or [])
                if identifier:
                    entry[f"{slot}_person_id"] = identifier
                    self.observations["personnel"].setdefault(identifier, {
                        "grade": person.get("rank", ""), "name": person.get("name", ""),
                        "phones": person.get("phones", [])})
            entry["count"] = clean_text(aligned.get("قوام الخدمة"))
            entry["weapon"] = clean_text(aligned.get("التسليح"))
            entry["schedule"] = clean_text(aligned.get("الانتظام"))
            if name not in result:
                result[name] = entry
                self._afraad_records[name] = record
            self.provenance["afraad_basic"][name] = self._src(record, "afraad_basic_row")
        return result

    def counts(self) -> dict[str, Any] | None:
        rows = self._of("counts", "counts_row")
        if not rows:
            rows = self._of("counts_leader", "counts_row")
        entries = []
        for record in sorted(rows, key=lambda r: (r["table"] or 0, r["row"] or 0)):
            cells = record["cells"]
            pairs = []
            position = 0
            while position < len(cells) - 1:
                name, value = cells[position], cells[position + 1]
                if name and not re.fullmatch(r"[\d\s.]+", name) and re.fullmatch(r"\s*\d+\s*", value or ""):
                    pairs.append((name, int(value)))
                    position += 2
                else:
                    position += 1
            if pairs:
                self._use(record)
            for name, value in pairs:
                flat = norm(name)
                if _non_service_phrase(flat) or flat.startswith(("اجمالي", "المجموع", "مجموع")):
                    continue
                block = record.get("block") or "صباحية"
                if block not in {"صباحية", "ليلية", "طوارئ"}:
                    block = "طوارئ" if "طوار" in block else "صباحية"
                party = re.search(r"\(([^)]+)\)", name)
                entries.append({"id": f"CNT-{len(entries) + 1:03d}", "name": clean_text(re.sub(r"\([^)]*\)", "", name)),
                                "block": block, "count": value, "party": party.group(1).strip() if party else "",
                                "weapon": "", "order": len(entries) + 1})
                self.provenance["counts"].append(self._src(record, "counts_row", f"{name} = {value}"))
        return {"entries": entries} if entries else None

    def basic_enrichment(self, afraad: dict[str, Any], afraad_rows: dict[str, dict[str, Any]]) -> None:
        """صفوف «الخدمات أساسية» بتاخد القائم والانتظام والقوام من يومية الأفراد لنفس الخدمة والفترة."""
        index = {service_key(name, self.ctx.vocabulary): name for name in afraad}
        for row in self.rows:
            if row["section"] != SECTION_BASIC:
                continue
            name = index.get(service_key(row["name"], self.ctx.vocabulary))
            if not name:
                continue
            entry = afraad[name]
            slot = "night" if row["shift"] == "ليلية" else "morning"
            identifier = entry.get(f"{slot}_person_id")
            if identifier and identifier not in row["personnel_ids"]:
                row["personnel_ids"].append(identifier)
            schedule = entry.get("schedule") or ""
            times = re.findall(r"\d{1,2}(?::\d{1,2})?\s*[\u0635\u0645\u0638]", schedule)
            if not row["time"] and times:
                pick = times[1] if slot == "night" and len(times) > 1 else times[0]
                row["time"] = re.sub(r"\s+", "", pick)
            if not row["weapon"] and entry.get("weapon"):
                row["weapon"] = entry["weapon"]
            if not row["conscripts"]:
                # «1 مج فض (2 مجند ) صبح + 1 سائق 1 مج فض (2 مجند ) ليل»: عدد مجندي الفترة دي
                text = entry.get("count") or ""
                by_shift = {("صباحية" if word == "صبح" else "ليلية"): int(number) for number, word in
                            re.findall(r"\(\s*(\d+)\s*مج\w*\s*\)\s*(صبح|ليل)", text)}
                sizes = re.findall(r"\(\s*(\d+)\s*مج", text)
                size = by_shift.get(row["shift"]) or (int(sizes[0]) if len(sizes) == 1 else 0)
                if size:
                    row["conscripts"] = [{"class": "مج", "count": size}]

    def counts_enrichment(self, counts: dict[str, Any] | None) -> None:
        """عدد المجندين من «اعداد الخدمات» — نفس مصدر الهجرة 005 للأيام الحالية: الطوارئ من قسم
        «طوارئ»، والخدمات الأساسية من قسم فترتها (صباحية/ليلية)."""
        if not counts:
            return
        index: dict[str, dict[str, int]] = defaultdict(dict)
        for entry in counts["entries"]:
            index[entry["block"]].setdefault(service_key(entry["name"], self.ctx.vocabulary), entry["count"])
        lookups = {block: {key: [key] for key in values} for block, values in index.items()}
        for row in self.rows:
            if row["section"] in {SECTION_TARGETS, *ROLE_SLOTS}:
                continue
            block = row["shift"] if row["section"] == SECTION_BASIC else "طوارئ"
            match = _nearest(lookups.get(block, {}), service_key(row["name"], self.ctx.vocabulary))
            if match:
                row["conscript_count"] = index[block][match[0]]

    def event_documents(self) -> None:
        """أيام قبل اللوحة: خطة انتشار/مباراة بتاريخ اليوم ومش متروكة بتتحول لقسم حدث."""
        if any(row["section"] not in {SECTION_BASIC, SECTION_OCCASIONAL, SECTION_TARGETS, *ROLE_SLOTS}
               for row in self.rows):
            return
        titles = self.ctx.events.get(self.date, [])
        if not titles:
            return
        for role in ("deployment", "match"):
            records = self._of(role, "deployment_row" if role == "deployment" else "match_row")
            if not records:
                continue
            title = next((title for title in titles if ("انتشار" in title) == (role == "deployment")), titles[0])
            for record in sorted(records, key=lambda r: (r["table"] or 0, r["row"] or 0)):
                cells = [value for value in record["cells"] if value and value != "م"]
                if len(cells) < 2 or any(word in " ".join(cells) for word in ("اسم الخدمة", "الرئاسة", "رقم الموبايل")):
                    continue
                label = cells[0]
                if re.fullmatch(r"[\d\-\.]+", label):
                    label = cells[1]
                if _non_service_phrase(norm(label)) or not _LETTERS_RE.search(label):
                    continue
                self._use(record)
                alias = self.ctx.alias(label)
                name, kind, counted = self.ctx.service_name(alias)
                if not name:
                    continue
                time = _time_text(record)
                row = self._new_row(name, title, kind=kind, time=time, shift=_shift_from_time(time) or "صباحية",
                                    counts_in_summary=counted)
                self._document_cells_into(row, record, cells[1:])
                self.provenance["assignments"][str(len(self.rows) - 1)] = self._src(record, f"{role}_document")

    def _document_cells_into(self, row: dict[str, Any], record: dict[str, Any], cells: list[str]) -> None:
        """صف «خطة الانتشار/المباراة»: الرئاسة | الموبايل | قوام الخدمة | التسليح | الانتظام — بالمحتوى مش بالترتيب."""
        leader = next((cell for cell in cells if _person_label(cell) and "/" in cell), "")
        self._people_into(row, record, leader)
        strength = next((cell for cell in cells if re.search(r"\d+\s*مج", cell)), "")
        if strength:
            row["conscript_count"] = min(int(re.search(r"\d+", strength).group()), 500)
        unit_cell = next((cell for cell in cells if cell not in {leader, strength} and _LETTERS_RE.search(cell)
                          and not re.search(r"01\d{9}", cell) and not _TIME_RAW_RE.fullmatch(cell.strip())), "")
        flat = norm(unit_cell)
        if "وحد" in flat:
            row["conscripts"] = [{"class": "وحدة فض" if "فض" in flat else "وحدة", "count": 1}]
        elif row["conscript_count"]:
            row["conscripts"] = [{"class": "مج", "count": row["conscript_count"]}]
        row["weapon"] = clean_text(unit_cell)

    def merge_duplicates(self) -> None:
        """النظام بيمنع نفس الشخص على نفس الخدمة والفترة مرتين — الصفين بيتدمجوا في الأول،
        والساعة/الجهة المختلفة بتتحفظ في الملاحظة. بيتكرر لحد ما يثبت: الدمج بيوسّع أشخاص الصف
        فممكن يبقى بيشارك صف تاني كان اتساب في نفس الجولة."""
        while self._merge_pass():
            pass

    def _merge_pass(self) -> bool:
        merged_any = False
        kept: list[dict[str, Any]] = []
        provenance: dict[str, Any] = {}
        for index, row in enumerate(self.rows):
            people = set(row["officer_ids"]) | set(row["personnel_ids"])
            # نفس مقارنة checks.duplicate_of: الاسم بعد التطبيع ونفس الفترة، أيًا كان القسم
            twin = next((other for other in kept if norm(other["name"]) == norm(row["name"])
                         and other["shift"] == row["shift"]
                         and people & (set(other["officer_ids"]) | set(other["personnel_ids"]))), None)
            source = self.provenance["assignments"].get(str(index))
            if twin is None:
                if source is not None:
                    provenance[str(len(kept))] = source
                kept.append(row)
                continue
            for field in ("officer_ids", "personnel_ids"):
                twin[field].extend(pid for pid in row[field] if pid not in twin[field])
            for field in ("time", "party", "weapon", "conscripts"):
                if not twin[field] and row[field]:
                    twin[field] = row[field]  # الصف التاني أكمل — بياناته بتكمّل الأول مش بتروح للملاحظة
            if twin["section"] == SECTION_OCCASIONAL and row["section"] not in CANONICAL_ORDER:
                twin["section"] = row["section"]  # خدمة الحدث مكانها قسم الحدث (زي مباراة 2-9-2026)
            extra = [value for value in (row["time"], row["party"], row["note"]) if value and value not in
                     (twin["time"], twin["party"]) and value not in twin["note"]]
            if extra:
                twin["note"] = clean_text(f"{twin['note']} {' | '.join(extra)}")
            twin["conscript_count"] = max(twin["conscript_count"], row["conscript_count"])
            position = kept.index(twin)
            merged = provenance.setdefault(str(position), {})
            merged.setdefault("merged", []).append(source or {})
            self.review.append({"date": self.date, "type": "duplicate_rows_merged", "section": row["section"],
                                "name": row["name"], "shift": row["shift"]})
            merged_any = True
        self.rows = kept
        self.provenance["assignments"] = provenance
        return merged_any

    def settle_shifts(self) -> None:
        """كل خدمة غير الأهداف لازم لها وردية؛ من الساعة لو موجودة، وإلا الافتراضي بعلامة مراجعة."""
        for index, row in enumerate(self.rows):
            if row["section"] == SECTION_TARGETS or row["kind"] == "حراسات":
                row["shift"] = "" if row["kind"] == "حراسات" else row["shift"]
                continue
            if row["shift"] in _SHIFT_WORDS:
                continue
            source = self.provenance["assignments"].setdefault(str(index), {})
            row["shift"] = _shift_from_time(row["time"])
            if row["shift"]:
                source["shift_rule"] = "from_time"
                continue
            row["shift"] = _DEFAULT_SHIFT
            source["shift_rule"] = "defaulted"
            self.review.append({"date": self.date, "type": "shift_defaulted", "section": row["section"],
                                "name": row["name"], "shift": _DEFAULT_SHIFT})

    def build(self, batch: str, at: str) -> dict[str, Any]:
        states = self.officer_states()
        if not self.board_assignments():
            self.derived_assignments()
        self.emergency_enrichment()
        self.event_documents()
        afraad = self.afraad_basic()
        self.basic_enrichment(afraad, self._afraad_records)
        counts = self.counts()
        self.counts_enrichment(counts)
        self.settle_shifts()
        self.merge_duplicates()
        # ترتيب الأقسام زي اليومين المرجعيين
        order = {SECTION_BASIC: 0, SECTION_OCCASIONAL: 1, SECTION_SUBCAMP: 3, SECTION_GREAT: 4,
                 SECTION_SECURITY: 5, SECTION_TARGETS: 6}
        indexed = list(enumerate(self.rows))
        # أقسام الأحداث (مباراة/خطة انتشار) بعد الأهداف — زي «مباراة ش قرية عامر» في 2-9-2026
        indexed.sort(key=lambda pair: (order.get(pair[1]["section"], 7), pair[0]))
        assignments = []
        provenance = {}
        for position, (old, row) in enumerate(indexed, 1):
            identifier = f"AS-{position:04d}"
            assignments.append({**row, "id": identifier})
            if str(old) in self.provenance["assignments"]:
                provenance[identifier] = self.provenance["assignments"][str(old)]
        self.provenance["assignments"] = provenance
        day: dict[str, Any] = {}
        if assignments:
            day["assignments"] = assignments
            day["assignment_seq"] = len(assignments)
        if states:
            day["officer_states"] = states
        if afraad:
            day["afraad_basic"] = afraad
        if counts:
            day["counts"] = counts
        day["import"] = {"batch": batch, "at": at, "derived": self.derived,
                         "sources": [{"type": role, "path": path, "sha1": sha1}
                                     for (role, path), sha1 in sorted(self.sources.items())]}
        return day


def _display_section(key: str) -> str:
    """اسم القسم بصيغة العرض اللي النظام بيستخدمها (مش الصيغة المطبّعة)."""
    flat = key.replace(" ", "")
    if "معسكرفرعي" in flat or "المعسكرالفرعي" in flat:
        return SECTION_SUBCAMP
    if "ضابطعظيم" in flat:
        return SECTION_GREAT
    if "ضابطالامن" in flat or "ضابطامن" in flat:
        return SECTION_SECURITY
    if "اساسي" in flat:
        return SECTION_BASIC
    if "طوار" in flat or "طاري" in flat:
        return SECTION_OCCASIONAL
    if "اهداف" in flat:
        return SECTION_TARGETS
    return ""


def _strip_shift_word(name: str) -> str:
    return re.sub(rf"\s+(?:{_SHIFT_TOKEN}|ص|ل)$", "", clean_text(name)).strip()


def _shift_from_time(time: str) -> str:
    match = re.search(r"(\d{1,2})(?::\d{1,2})?\s*([\u0635\u0645\u0638])", time or "")
    if not match:
        return ""
    hour, mark = int(match.group(1)), match.group(2)
    if mark in "صظ":
        return "صباحية"
    # «2:30م» نهاري، «10 م» و«12م» ليلي — زي اليوم المرجعي 2-9-2026
    return "صباحية" if 1 <= hour <= 5 else "ليلية"


_RANK_PREFIX_RE = re.compile(r"^\s*(?:ال)?(?:لواء|عميد|عقيد|مقدم|رائد|رايد|نقيب|ملازم(?:\s*[اأ]ول)?|م\s*\.?\s*[اأ]ول)\s*[/\\.]*\s*")


def _tokens(value: str) -> list[str]:
    return [token for token in norm(value).replace("ال", " ال").split() if token]


def _shifts_in(text: str) -> list[str]:
    # «من 9 م حتى 9 ص» ساعات مش ورديات — بتتشال قبل البحث عن كلمة الوردية
    flat = _TIME_RAW_RE.sub(" ", norm(text))
    result = []
    if re.search(r"صباح|صبح|(?:^|\s)ص(?:\s|$)", flat):
        result.append("صباحية")
    if re.search(r"ليل|مسائ|مساي|(?:^|\s)ل(?:\s|$)", flat):
        result.append("ليلية")
    return result


# ---------- التغييرات على البيانات الأساسية (مرور على المدى كله) ----------

def _history_entries(days: list[tuple[str, dict[str, Any]]],
                     blips: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """سجل التاريخ من ملاحظات اليومية. رتبة مش معروفة (صف متلخبط) بتاخد اللي قبلها، والتغيير اللي
    بيستمر يومية واحدة ويرجع زي ما كان بيتعامل كخطأ كتابة — بيتسجل للمراجعة ومش بيبقى تاريخ."""
    states = []
    last_rank = ""
    for date, obs in days:
        rank = obs.get("rank") or ""
        if rank not in RANK_ORDER:
            rank = last_rank
        last_rank = rank or last_rank
        states.append((date, (rank, obs.get("post") or "", obs.get("section") or "", obs.get("rest_system") or "",
                              obs.get("rest_day") or "", bool(obs.get("search_attached")))))
    kept: list[tuple[str, tuple[Any, ...]]] = []
    for index, (date, state) in enumerate(states):
        before = kept[-1][1] if kept else None
        after = states[index + 1][1] if index + 1 < len(states) else None
        if before is not None and state != before and after == before:
            if blips is not None:
                blips.append({"date": date, "state": list(state), "kept": list(before)})
            continue
        kept.append((date, state))
    entries: list[dict[str, Any]] = []
    previous = None
    for date, state in kept:
        if state != previous:
            entries.append({"from": date, "role": state[0], "post": state[1], "section": state[2],
                            "rest_system": state[3], "rest_day": state[4], "search_attached": state[5]})
            previous = state
    return entries


def _stitch_leaves(per_person: dict[str, list[tuple[str, dict[str, Any], str]]],
                   working: dict[str, set[str]] | None = None) -> list[dict[str, Any]]:
    """فترات الراحة من ملاحظات اليومية. العدّاد «(k/n)» بيفترض n يوم كاملة، لكن يومية يوم فيها
    الضابط شغال من غير راحة دليل مباشر لليوم ده — الفترة بتتقطع عنده."""
    leaves: list[dict[str, Any]] = []
    for person_id, items in sorted(per_person.items()):
        busy = (working or {}).get(person_id, set())
        intervals: list[dict[str, Any]] = []
        for date, leave, note in sorted(items, key=lambda value: value[0]):
            kind = leave.get("type") or ""
            start, end = leave.get("start") or date, leave.get("end") or date
            if not kind or not start or not end or end < start:
                continue
            last = intervals[-1] if intervals else None
            if last and last["type"] == kind and start <= _next_day(last["end"]):
                last["end"] = max(last["end"], end)
                continue
            intervals.append({"person_id": person_id, "type": kind, "start": start, "end": end, "source": note})
        for interval in intervals:
            for part in _split_on(interval, busy):
                part["return_date"] = _next_day(part["end"])
                leaves.append(part)
    return leaves


def _split_on(interval: dict[str, Any], busy: set[str]) -> list[dict[str, Any]]:
    parts, current = [], None
    day = interval["start"]
    while day <= interval["end"]:
        if day in busy:
            if current:
                parts.append(current)
                current = None
        elif current is None:
            current = {**interval, "start": day, "end": day}
        else:
            current["end"] = day
        day = _next_day(day)
    if current:
        parts.append(current)
    return parts


def _next_day(value: str) -> str:
    return (dt.date.fromisoformat(value) + dt.timedelta(days=1)).isoformat()


def core_delta(observations: dict[str, dict[str, Any]], core: dict[str, Any]) -> dict[str, Any]:
    officers_by_id = {person["id"]: person for person in core.get("officers", [])}
    personnel_by_id = {person["id"]: person for person in core.get("personnel", [])}
    per_officer: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    per_ref: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    per_person: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    leaves_evidence: dict[str, list[tuple[str, dict[str, Any], str]]] = defaultdict(list)
    working: dict[str, set[str]] = defaultdict(set)
    command_days: list[tuple[str, dict[str, Any]]] = []
    for date in sorted(observations):
        day = observations[date]
        command = {"مدير الإدارة": None, "وكيل الإدارة": None}
        groups: dict[str, list[str]] = {"طبي": [], "بحث": []}
        for officer_id, obs in sorted(day.get("officers", {}).items()):
            per_officer[officer_id].append((date, obs))
            post = norm(obs.get("post") or "")
            if any(norm(key) in post for key in _DIRECTOR_POST) and not command["مدير الإدارة"]:
                command["مدير الإدارة"] = officer_id
            elif any(norm(key) in post for key in _DEPUTY_POST) and not command["وكيل الإدارة"]:
                command["وكيل الإدارة"] = officer_id
            if obs.get("qualifier") or any(norm(key) in post for key in _MEDICAL_POST):
                groups["طبي"].append(officer_id)
            if obs.get("search_attached"):
                groups["بحث"].append(officer_id)
            for leave in obs.get("leaves") or []:
                leaves_evidence[officer_id].append((date, leave, obs.get("note", "")))
            if not obs.get("leaves"):
                working[officer_id].add(date)
        for officer_id, ref in sorted(day.get("officer_refs", {}).items()):
            if officer_id not in day.get("officers", {}):
                per_ref[officer_id].append((date, ref))
        for person_id, obs in sorted(day.get("personnel", {}).items()):
            per_person[person_id].append((date, obs))
        if day.get("officers"):
            command_days.append((date, {"command": command, "groups": groups}))

    officers = []
    # يومية الضباط هي المرجع لمدى الخدمة («أصل القوة» في الوورد = اللي في اليومية). الظهور على
    # اللوحة بره المدى ده ما بيمدّهوش — STORE بيفك الربط ويحط الاسم في ملاحظة الصف.
    ref_names = {officer_id: Counter(ref.get("name") for _, ref in refs if ref.get("name")).most_common(1)[0][0]
                 for officer_id, refs in per_ref.items() if any(ref.get("name") for _, ref in refs)}
    blips: dict[str, list[dict[str, Any]]] = {}
    for officer_id, days in sorted(per_officer.items()):
        officer_blips: list[dict[str, Any]] = []
        history = _history_entries(days, officer_blips)
        if officer_blips:
            blips[officer_id] = officer_blips
        names = Counter(obs.get("name") for _, obs in days if obs.get("name"))
        codes = Counter(obs.get("code") for _, obs in days if obs.get("code"))
        entry = {"id": officer_id, "first_seen": days[0][0], "last_seen": days[-1][0], "days": len(days),
                 "history": history, "name": max(names, key=lambda name: (len(name.split()), names[name], name)) if names else "",
                 "code": codes.most_common(1)[0][0] if codes else ""}
        existing = officers_by_id.get(officer_id)
        if existing:
            entry["action"] = "extend"
            entry["existing_join_date"] = existing.get("join_date", "")
        else:
            entry["action"] = "create"
        officers.append(entry)
    personnel = []
    for person_id, days in sorted(per_person.items()):
        names = Counter(obs.get("name") for _, obs in days if obs.get("name"))
        phones = Counter(phone for _, obs in days for phone in obs.get("phones") or [])
        grades = []
        previous = None
        for date, obs in days:
            if obs.get("grade") and obs["grade"] != previous:
                grades.append({"from": date, "role": obs["grade"]})
                previous = obs["grade"]
        personnel.append({
            "id": person_id, "action": "extend" if person_id in personnel_by_id else "create",
            "first_seen": days[0][0], "last_seen": days[-1][0], "days": len(days),
            "name": max(names, key=lambda name: (len(name.split()), names[name], name)) if names else "",
            "phones": [phone for phone, _ in phones.most_common()], "history": grades,
        })
    command_history = []
    previous = None
    for date, value in command_days:
        signature = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if signature != previous:
            command_history.append({"from": date, **value})
            previous = signature
    leaves = _stitch_leaves(leaves_evidence, working)
    existing_keys = {(leave.get("person_id"), leave.get("type"), leave.get("start")) for leave in core.get("leaves", [])}
    by_person = defaultdict(list)
    for leave in core.get("leaves", []):
        by_person[leave.get("person_id")].append(leave)
    leave_ops = []
    for leave in leaves:
        key = (leave["person_id"], leave["type"], leave["start"])
        if key in existing_keys:
            leave_ops.append({"op": "keep", **leave})
            continue
        overlap = [other for other in by_person.get(leave["person_id"], [])
                   if not (other.get("end", "") < leave["start"] or other.get("start", "") > leave["end"])]
        leave_ops.append({"op": "review_overlap" if overlap else "add", **leave,
                          "overlaps": [other.get("id") for other in overlap]})
    return {"officers": officers, "personnel": personnel, "command_history": command_history, "leaves": leave_ops,
            "ref_names": ref_names, "history_blips": blips}


def reference_versions(days: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """نسخ مؤرخة للقوائم: نسخة جديدة كل ما قائمة اليوم (بترتيبها) تختلف عن اللي قبلها، فكل
    خدمة أساسية وكل هدف موجود في وثيقة اليوم بيظهر في يومه — ولا حاجة بتستخبى."""
    known = {row["name"]: row["id"] for row in BASIC_SERVICES}
    next_number = len(BASIC_SERVICES) + 1
    afraad_versions: list[dict[str, Any]] = []
    target_versions: list[dict[str, Any]] = []
    for date in sorted(days):
        day = days[date]
        names = list(day.get("afraad_basic", {}))
        for name in names:
            if name not in known:
                known[name] = f"AFB-{next_number:02d}"
                next_number += 1
        items = [{"id": known[name], "name": name} for name in names]
        if items and (not afraad_versions or afraad_versions[-1]["items"] != items):
            afraad_versions.append({"from": date, "items": items})
        targets = []
        for row in day.get("assignments", []):
            if row["section"] == SECTION_TARGETS and row["name"] not in targets:
                targets.append(row["name"])
        if TARGETS_FIRST in targets:
            targets.remove(TARGETS_FIRST)
            targets.insert(0, TARGETS_FIRST)
        if targets and (not target_versions or target_versions[-1]["names"] != targets):
            target_versions.append({"from": date, "names": targets})
    return {"afraad_basic": afraad_versions, "targets": target_versions, "afraad_ids": known}


# ---------- المرحلة ----------

def run_transform(ledger: Ledger, state: dict[str, Any], start: dt.date | None = None,
                  end: dt.date | None = None, *, resume: bool = False) -> dict[str, Any]:
    source = ledger.staging_path("normalize")
    if not source.exists():
        raise FileNotFoundError("يجب تشغيل normalize وresolve وaliases للدفعة أولًا")
    ledger.mark_stage(state, "transform", "running")
    core = json.loads((ledger.data_dir / "core.json").read_text(encoding="utf-8"))
    ctx = Context(ledger, core)
    start_s = start.isoformat() if start else None
    end_s = end.isoformat() if end else None
    records = load_records(source, start_s, end_s)
    at = f"{ledger.batch}"
    out_dir = ledger.root / "staging" / ledger.batch / "transform" / "days"
    out_dir.mkdir(parents=True, exist_ok=True)
    days: dict[str, dict[str, Any]] = {}
    observations: dict[str, dict[str, Any]] = {}
    review: list[dict[str, Any]] = []
    stats = Counter()
    for date in sorted(records):
        builder = DayBuilder(date, records[date], ctx)
        day = builder.build(ledger.batch, at)
        days[date] = day
        observations[date] = builder.observations
        review.extend(builder.review)
        atomic_write_json(out_dir / f"{date}.json", day)
        prov_path = ledger.root / "provenance" / date[:4] / date[5:7] / f"{date}.json"
        prov_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(prov_path, builder.provenance)
        stats["days"] += 1
        stats["derived_days"] += int(builder.derived)
        stats["rows"] += len(day.get("assignments", []))
        stats["officer_states"] += len(day.get("officer_states", {}))
        stats["afraad_entries"] += len(day.get("afraad_basic", {}))
        stats["counts_days"] += int("counts" in day)
        stats["protected"] += int(date in PROTECTED)
    references = reference_versions(days)
    # AFB ids مستقرة: اسم الخدمة الأساسية → id من القائمة المؤرخة
    for date, day in days.items():
        if "afraad_basic" in day:
            day["afraad_basic"] = {references["afraad_ids"][name]: {k: v for k, v in entry.items() if k != "name"}
                                   for name, entry in day["afraad_basic"].items() if name in references["afraad_ids"]}
            atomic_write_json(out_dir / f"{date}.json", day)
    delta = core_delta(observations, core)
    delta["reference_lists"] = {"afraad_basic": references["afraad_basic"], "targets": references["targets"]}
    delta["protected_dates"] = sorted(PROTECTED)
    atomic_write_json(ledger.root / "staging" / ledger.batch / "transform" / "core_delta.json", delta)
    atomic_write_jsonl(ledger.staging_path("transform-review"), review)
    review_counts = Counter(item["type"] for item in review)
    checkpoint = {**stats, "review": dict(review_counts), "officers": len(delta["officers"]),
                  "personnel": len(delta["personnel"]), "leaves": Counter(op["op"] for op in delta["leaves"]),
                  "command_history": len(delta["command_history"]),
                  "afraad_versions": len(references["afraad_basic"]), "target_versions": len(references["targets"]),
                  "version": VERSION}
    checkpoint["leaves"] = dict(checkpoint["leaves"])
    atomic_write_json(ledger.report_path("transform.json"), checkpoint)
    ledger.mark_stage(state, "transform", "complete", checkpoint)
    return checkpoint


__all__ = ["VERSION", "PROTECTED", "DayBuilder", "Context", "core_delta", "reference_versions", "run_transform"]

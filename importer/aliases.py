"""بناء معجم الخدمات ورصد الأقسام الاستثنائية."""

from __future__ import annotations

import ast
import csv
import datetime as dt
import io
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from backend.afraad import BASIC_SERVICES
from backend.constants import (
    SECTION_ADMIN_WORK, SECTION_BASIC, SECTION_GREAT, SECTION_OCCASIONAL,
    SECTION_SECURITY, SECTION_SUBCAMP, SECTION_TARGETS,
)
from backend.dated import afraad_basic_on, targets_on
from backend.text import core_service_name, norm

from .ledger import Ledger, atomic_write_bytes, atomic_write_json, atomic_write_jsonl
from .textnorm import clean_text, dates_in_text


VERSION = "1"
REVIEW_FIELDS = [
    "key", "examples", "count", "first", "last", "contexts", "proposed canonical",
    "confidence", "runner-up", "category", "kind", "section", "counts_in_summary",
]
DECISION_FIELDS = [
    "key", "canonical", "confidence", "category", "kind", "section",
    "counts_in_summary", "note",
]
EVENT_FIELDS = ["date", "event title", "source", "member rows"]
EVENT_DECISION_FIELDS = ["date", "event title", "action", "override title", "note"]

CANONICAL_SECTIONS = {
    SECTION_BASIC, SECTION_OCCASIONAL, SECTION_TARGETS, SECTION_SUBCAMP,
    SECTION_GREAT, SECTION_SECURITY, SECTION_ADMIN_WORK,
    "الخدمات الأساسية", "الطوارئ", "خدمات الطوارئ", "عمل بالادارة",
    "الراحات", "الراحات والاجازات", "التقصيرة", "التقصيره", "الخوارج",
    "القوة", "الحراسات المشددة", "معسكر فرعي", "المعسكر الفرعي",
    "ضابط الامن", "ضابط الأمن",
}
ROLE_NAMES = {
    "نوبتجي المعسكر الفرعي": SECTION_SUBCAMP,
    "العمل بالمعسكر الفرعي": SECTION_SUBCAMP,
    "ضابط عظيم الإدارة": SECTION_GREAT,
    "ضابط أمن الإدارة": SECTION_SECURITY,
}
ADMIN_PATTERNS = ("متابعه اعمال", "متابعة اعمال", "متابعة أعمال", "عمل بالاداره", "عمل بالادارة", "عمل بالإدارة")
EVENT_RE = re.compile(
    r"^(?:خدمات\s+)?(?:المباراه|المباراة|مباراه|مباراة|الماتش|ماتش|خطه\s+(?:ال)?انتشار|"
    r"خطة\s+(?:ال)?انتشار|التراحيل|خدمات\s+سجن)|انتخاب(?:ات)?",
    re.I,
)
INSTRUCTION_RE = re.compile(r"^\s*\d+\s*(?:مجند|مج|فرد).*حفظ\s+نظام.*(?:لتامين|لتأمين)")
_ROLE_SECTIONS = {SECTION_SUBCAMP, SECTION_GREAT, SECTION_SECURITY}


@dataclass
class VocabularyItem:
    name: str
    kind: str
    section: str
    counts_in_summary: bool = True
    category: str = "service"
    aliases: set[str] = field(default_factory=set)


@dataclass
class PhraseStats:
    examples: Counter[str] = field(default_factory=Counter)
    dates: list[str] = field(default_factory=list)
    contexts: Counter[str] = field(default_factory=Counter)
    years: Counter[str] = field(default_factory=Counter)
    sources: Counter[str] = field(default_factory=Counter)

    def add(self, example: str, day: str, context: str, source: str) -> None:
        self.examples[clean_text(example)] += 1
        self.dates.append(day)
        self.contexts[context] += 1
        self.years[day[:4]] += 1
        self.sources[source] += 1

    @property
    def count(self) -> int:
        return sum(self.examples.values())


def _edit_distance(left: str, right: str) -> int:
    if len(left) > len(right):
        left, right = right, left
    previous = list(range(len(left) + 1))
    for row, char in enumerate(right, 1):
        current = [row]
        for column, other in enumerate(left, 1):
            current.append(min(current[-1] + 1, previous[column] + 1,
                               previous[column - 1] + (char != other)))
        previous = current
    return previous[-1]


def _base_key(value: str) -> str:
    """يجعل أداة التعريف اختيارية في المقارنة فقط."""
    value = core_service_name(clean_text(value))
    tokens = []
    for token in value.split():
        if token in {"ص", "م", "ظ", "صبح", "ليل", "صباحي", "ليلي"}:
            continue
        if token.startswith("ال") and len(token) > 4:
            token = token[2:]
        elif token.startswith("بال") and len(token) > 5:
            token = token[3:]
        elif token.startswith("لل") and len(token) > 4:
            token = token[2:]
        if token:
            tokens.append(token)
    return " ".join(tokens)


def _vocabulary_tokens(items: Iterable[VocabularyItem]) -> set[str]:
    return {token for item in items for token in _base_key(item.name).split() if len(token) >= 4}


_VOCAB_TOKEN_CACHE: dict[int, tuple[int, dict[tuple[int, str], tuple[str, ...]]]] = {}
_SERVICE_KEY_CACHE: dict[tuple[int, str], str] = {}
_MATCH_CACHE: dict[int, tuple[int, list[tuple[VocabularyItem, tuple[str, ...]]],
                              dict[str, set[int]], dict[str, set[int]]]] = {}
_DISPLAY_CACHE: dict[int, tuple[int, dict[str, VocabularyItem]]] = {}


def service_key(value: str, vocabulary: Iterable[VocabularyItem] = ()) -> str:
    """مفتاح الخدمة، مع تصحيح خطأ هجائي واضح وحيد ضد المعجم."""
    key = _base_key(value)
    if not vocabulary:
        return key
    vocab_id = id(vocabulary)
    size = len(vocabulary) if hasattr(vocabulary, "__len__") else -1
    cached_key = (vocab_id, key)
    if cached_key in _SERVICE_KEY_CACHE:
        return _SERVICE_KEY_CACHE[cached_key]
    cached = _VOCAB_TOKEN_CACHE.get(vocab_id)
    if cached is None or cached[0] != size:
        grouped: dict[tuple[int, str], list[str]] = defaultdict(list)
        for token in _vocabulary_tokens(vocabulary):
            grouped[(len(token), token[:1])].append(token)
        cached = (size, {group: tuple(sorted(values)) for group, values in grouped.items()})
        _VOCAB_TOKEN_CACHE[vocab_id] = cached
    grouped = cached[1]
    corrected = []
    for token in key.split():
        exact = grouped.get((len(token), token[:1]), ())
        if token in exact or len(token) < 4:
            corrected.append(token)
            continue
        pool = [known for length in range(len(token) - 1, len(token) + 2)
                for known in grouped.get((length, token[:1]), ())]
        candidates = [known for known in pool if _edit_distance(token, known) == 1]
        corrected.append(candidates[0] if len(candidates) == 1 else token)
    result = " ".join(corrected)
    _SERVICE_KEY_CACHE[cached_key] = result
    return result


def _csv_write(path: Path, fields: list[str], rows: Iterable[dict[str, Any]]) -> None:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    atomic_write_bytes(path, b"\xef\xbb\xbf" + stream.getvalue().encode("utf-8"))


def _csv_read(path: Path, key_fields: tuple[str, ...]) -> dict[tuple[str, ...], dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return {tuple(row.get(key, "") for key in key_fields): row for row in csv.DictReader(stream)
                if all(row.get(key) for key in key_fields)}


def _filled(row: dict[str, str], key_fields: tuple[str, ...]) -> bool:
    """قرار فيه حاجة اتكتبت فعلًا (مش صف فاضي متولّد)."""
    return any(value and key not in key_fields for key, value in row.items() if key)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _legacy_catalog() -> list[tuple[str, str, list[str], bool]]:
    """يقرأ البذرة كبيانات، بلا تشغيل المستورد القديم المرتبط بمسار 2026."""
    path = Path(__file__).resolve().parent.parent / "import_archive" / "services.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "CATALOG"
                                                for target in node.targets):
            values = ast.literal_eval(node.value)
            names = {"EXTERNAL": "خارجية", "INTERNAL": "داخلية",
                     "GUARD": "حراسات", "MEDICAL": "طبية", "SEARCH": "داخلية"}
            # literal_eval لا يقرأ أسماء الثوابت، لذلك نستبدلها في نسخة AST.
            return values  # pragma: no cover - لن يصل مع أسماء الثوابت
    return []


def _legacy_catalog_safe() -> list[tuple[str, str, list[str], bool]]:
    path = Path(__file__).resolve().parent.parent / "import_archive" / "services.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    kinds = {"EXTERNAL": "خارجية", "INTERNAL": "داخلية", "GUARD": "حراسات",
             "MEDICAL": "طبية", "SEARCH": "داخلية"}
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "CATALOG"
                                                      for t in node.targets) and isinstance(node.value, ast.List)):
            continue
        result = []
        for row in node.value.elts:
            if not isinstance(row, ast.Tuple) or len(row.elts) != 4:
                continue
            name = ast.literal_eval(row.elts[0])
            kind_node = row.elts[1]
            kind = kinds.get(kind_node.id, "خارجية") if isinstance(kind_node, ast.Name) else ast.literal_eval(kind_node)
            aliases = ast.literal_eval(row.elts[2])
            standing = ast.literal_eval(row.elts[3])
            result.append((name, kind, aliases, standing))
        return result
    return []


def _rebind_event_decisions(events: list[dict[str, Any]], decisions: dict[tuple[str, ...], dict[str, str]]) -> None:
    """عنوان الحدث المتولّد ممكن يتغير لما الاستخراج يتحسن. لو في اليوم قرار واحد بس مالوش حدث
    وحدث واحد بس مالوش قرار، القرار بيتنقل له (مع ملاحظة) بدل ما يضيع."""
    by_date: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        by_date.setdefault(event["date"], []).append(event)
    for date, items in by_date.items():
        titles = {event["event title"] for event in items}
        orphans = [key for key, row in decisions.items()
                   if key[0] == date and key[1] not in titles and _filled(row, ("date", "event title"))]
        unbound = [event for event in items if (date, event["event title"]) not in decisions]
        if len(orphans) == 1 and len(unbound) == 1:
            row = dict(decisions.pop(orphans[0]))
            row["event title"] = unbound[0]["event title"]
            row["note"] = f"{row.get('note') or ''} [أعيد ربطه من «{orphans[0][1]}»]".strip()
            decisions[(date, row["event title"])] = row


def build_vocabulary(data_dir: Path, records: list[dict[str, Any]] | None = None) -> list[VocabularyItem]:
    items: dict[tuple[str, str, str, bool], VocabularyItem] = {}

    def add(name: str, kind: str, section: str, counted: bool = True,
            category: str = "service", aliases: Iterable[str] = ()) -> None:
        name = clean_text(name)
        if not name:
            return
        identity = (name, kind, section, bool(counted))
        item = items.setdefault(identity, VocabularyItem(name, kind, section, bool(counted), category))
        item.aliases.update(clean_text(alias) for alias in aliases if clean_text(alias))

    for path in sorted((data_dir / "days").glob("2026/[0][6-9]/*.json")) + \
                sorted((data_dir / "days").glob("2026/10/*.json")):
        day = json.loads(path.read_text(encoding="utf-8"))
        for row in day.get("assignments", []):
            section = clean_text(row.get("section")) or SECTION_OCCASIONAL
            category = "target" if section == SECTION_TARGETS else (
                "role_slot" if section in _ROLE_SECTIONS else "service")
            add(row.get("name", ""), row.get("kind", "خارجية"), section,
                row.get("counts_in_summary", True), category)

    core_path = data_dir / "core.json"
    core = json.loads(core_path.read_text(encoding="utf-8")) if core_path.exists() else {}
    # دليل الخدمات في اللقطة مصدر مساند للقوائم المؤرخة.
    for row in core.get("service_catalog") or []:
        add(row.get("name", ""), row.get("kind") or "خارجية", SECTION_BASIC)
    reference_days = {"2023-10-01", "2024-01-01", "2025-01-01", "2026-01-01", "2026-09-01"}
    reference_days.update(str(row.get("from")) for rows in (core.get("reference_lists") or {}).values()
                          for row in rows if row.get("from"))
    for day in sorted(reference_days):
        for name in targets_on(core, day):
            add(name, "حراسات", SECTION_TARGETS, True, "target")
        for row in afraad_basic_on(core, day):
            add(row["name"], "خارجية", SECTION_BASIC, True, "service")
    for row in BASIC_SERVICES:
        add(row["name"], "خارجية", SECTION_BASIC)
    # صفوف الأفراد هي النسخ المؤرخة الفعلية للقائمة في الأرشيف.
    for record in records or []:
        if record.get("record_type") == "afraad_basic_row":
            add(_first_service_cell(record), "خارجية", SECTION_BASIC)
    for name, section in ROLE_NAMES.items():
        add(name, "داخلية", section, name != "نوبتجي المعسكر الفرعي", "role_slot")
    for name, kind, aliases, standing in _legacy_catalog_safe():
        if name.startswith("هدف "):
            name = name[4:]
        section = SECTION_TARGETS if kind == "حراسات" else (SECTION_BASIC if standing else SECTION_OCCASIONAL)
        category = "target" if kind == "حراسات" else ("role_slot" if name in ROLE_NAMES else "service")
        add(name, kind, section, name != "نوبتجي المعسكر الفرعي", category, aliases)
    return sorted(items.values(), key=lambda item: (item.name, item.section, item.kind))


def _score(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left in right or right in left:
        return min(len(left), len(right)) / max(len(left), len(right)) + 0.35
    a, b = set(left.split()), set(right.split())
    return len(a & b) / max(len(a), len(b)) if a and b else 0.0


def propose_alias(phrase: str, vocabulary: list[VocabularyItem]) -> dict[str, Any]:
    key = service_key(phrase, vocabulary)
    vocab_id = id(vocabulary)
    display_cache = _DISPLAY_CACHE.get(vocab_id)
    if display_cache is None or display_cache[0] != len(vocabulary):
        display_cache = (len(vocabulary), {clean_text(item.name): item for item in vocabulary})
        _DISPLAY_CACHE[vocab_id] = display_cache
    cached = _MATCH_CACHE.get(vocab_id)
    if cached is None or cached[0] != len(vocabulary):
        prepared: list[tuple[VocabularyItem, tuple[str, ...]]] = []
        exact_index: dict[str, set[int]] = defaultdict(set)
        token_index: dict[str, set[int]] = defaultdict(set)
        for item in vocabulary:
            variants = tuple(sorted({service_key(value, vocabulary) for value in {item.name, *item.aliases}}))
            index = len(prepared)
            prepared.append((item, variants))
            for variant in variants:
                exact_index[variant].add(index)
                for token in variant.split():
                    token_index[token].add(index)
        cached = (len(vocabulary), prepared, exact_index, token_index)
        _MATCH_CACHE[vocab_id] = cached
    _size, prepared, exact_index, token_index = cached
    candidate_indexes = set(exact_index.get(key, set()))
    for token in key.split():
        candidate_indexes.update(token_index.get(token, set()))
    candidates: dict[str, tuple[float, VocabularyItem]] = {}
    for index in candidate_indexes:
        item, variants = prepared[index]
        score = max((_score(key, value) for value in variants), default=0.0)
        old = candidates.get(item.name)
        if old is None or score > old[0]:
            candidates[item.name] = (score, item)
    ranked = sorted(candidates.values(), key=lambda pair: (-pair[0], pair[1].name))
    display_exact = display_cache[1].get(clean_text(phrase)) or \
        display_cache[1].get(clean_text(core_service_name(phrase)))
    exact_names = {prepared[index][0].name for index in exact_index.get(key, set())}
    exact = [pair for pair in ranked if pair[1].name in exact_names]
    if display_exact:
        item = display_exact
        confidence = "high"
    elif exact:
        score, item = exact[0]
        confidence = "high"
    elif ranked and ranked[0][0] >= 0.45:
        score, item = ranked[0]
        confidence = "medium"
    else:
        item = VocabularyItem(clean_text(core_service_name(phrase)), "خارجية", SECTION_OCCASIONAL)
        confidence = "low"
    flat = norm(phrase)
    if flat == "عمل" or any(norm(pattern) in flat for pattern in ADMIN_PATTERNS) or \
            ("تشغيل من خلال" in flat and "اداره" in flat and "بحث" in flat) or \
            flat in {"اداره بحث", "اداره ال0بحث"} or \
            ("عياده" in flat and "عمل" in flat):
        item = VocabularyItem(clean_text(core_service_name(phrase)), "", SECTION_ADMIN_WORK, False, "admin_work")
        confidence = "high"
    elif EVENT_RE.search(flat):
        item = VocabularyItem(clean_text(core_service_name(phrase)), "خارجية", SECTION_OCCASIONAL, True, "event")
    elif re.search(r"(?:^|\s)(?:عمل\s+)?بهدف\s+", flat):
        target_key = re.sub(r"^(?:عمل\s+)?بهدف\s+", "", service_key(phrase, vocabulary)).strip()
        target = max((entry for entry in vocabulary if entry.category == "target"),
                     key=lambda entry: _score(target_key, service_key(entry.name, vocabulary)), default=None)
        if target and _score(target_key, service_key(target.name, vocabulary)) >= .45:
            item, confidence = target, "medium" if confidence == "low" else confidence
        else:
            item = VocabularyItem(clean_text(core_service_name(phrase)), "حراسات", SECTION_TARGETS, True, "target")
    runner = next((candidate.name for _, candidate in ranked if candidate.name != item.name), "")
    return {"key": key, "canonical": item.name, "confidence": confidence, "runner_up": runner,
            "category": item.category, "kind": item.kind, "section": item.section,
            "counts_in_summary": item.counts_in_summary}


def _first_service_cell(record: dict[str, Any]) -> str:
    cells = [clean_text(value) for value in record.get("raw_cells", [])]
    cells = [value for value in cells if value and not re.fullmatch(r"\d+", value)]
    for value in cells:
        flat = norm(value)
        if re.search(r"(?:^|\s)(?:لواء|عميد|عقيد|مقدم|رائد|نقيب|ملازم|م\s*ش|ا\s*ش|امين|رقيب|مساعد)\s*[/\\-]", flat):
            continue
        if re.fullmatch(r"[\d\s()+/.-]*(?:مجند|مج|فرد)?[\d\s()+/.-]*", flat):
            continue
        return value.split("\n", 1)[0]
    return ""


def collect_phrases(records: list[dict[str, Any]], vocabulary: list[VocabularyItem]
                    ) -> tuple[dict[str, PhraseStats], list[dict[str, Any]]]:
    phrases: dict[str, PhraseStats] = defaultdict(PhraseStats)
    notes: list[dict[str, Any]] = []
    board_sections: dict[tuple[str, str, int], str] = defaultdict(lambda: SECTION_BASIC)

    def add(raw: str, record: dict[str, Any], context: str, source: str) -> None:
        raw = clean_text(raw)
        flat = norm(raw)
        if not raw or raw in {"-", "--", "---"} or _non_service_phrase(flat):
            return
        if _instruction_phrase(flat):
            notes.append({"date": record["date"], "source": source, "text": raw, "classification": "note"})
            return
        key = service_key(raw, vocabulary)
        if key and not re.fullmatch(r"\d+", key):
            phrases[key].add(raw, record["date"], context, source)

    for record in records:
        kind, role = record.get("record_type"), record.get("role")
        if role == "roster" and kind == "roster_row":
            for value in record.get("normalized", {}).get("officer", {}).get("daily", {}).get("services", []):
                add(value, record, "التشغيل اليومي", "roster")
        elif role == "board" and kind in {"board_label", "board_row"}:
            raw = clean_text(record.get("label"))
            marker = norm(raw)
            ident = (record["date"], record.get("path", ""), int(record.get("half", 0)))
            mapped = _canonical_board_section(marker)
            if mapped:
                board_sections[ident] = mapped
            elif kind == "board_label" and EVENT_RE.search(marker):
                board_sections[ident] = raw
            else:
                add(raw, record, f"board:{board_sections[ident]}", "board")
        elif kind == "afraad_basic_row":
            add(_first_service_cell(record), record, "afraad:الخدمات الأساسية", "afraad_basic")
        elif kind == "afraad_emergency_row":
            raw = clean_text(record.get("fields", {}).get("service")) or _first_service_cell(record)
            if INSTRUCTION_RE.search(norm(" ".join(record.get("raw_cells", [])))):
                notes.append({"date": record["date"], "source": "afraad", "text": " | ".join(record.get("raw_cells", [])),
                              "classification": "note"})
            else:
                add(raw, record, "afraad:الخدمات الطارئة", "afraad_emergency")
        elif role == "duty_list" and kind in {"duty_service_line", "duty_row", "duty_officer_row"}:
            add(_first_service_cell(record), record, "duty_list", "duty_list")
        elif role in {"counts", "counts_leader"} and kind == "counts_row":
            for raw in _count_names(record):
                add(raw, record, f"counts:{record.get('block', '')}", role)
        elif role == "command_order" and kind == "command_row":
            raw = clean_text(record.get("service"))
            if raw and not dates_in_text(raw) and not re.match(
                    r"^(?:لواء|عميد|عقيد|مقدم|رائد|رايد|نقيب|ملازم)\b", norm(raw)):
                add(raw, record, "command_order", "command_order")
    return phrases, notes


# رتبة مع «ال» أو من غيرها، لوحدها أو قبل اسم — دي إشارة لشخص مش اسم خدمة
_RANK_RE = re.compile(r"^(?:ال)?(?:لواء|عميد|عقيد|مقدم|رايد|رائد|نقيب|ملازم(?:\s+اول)?|م\s*\.?\s*اول)(?:\s|$|/)")
# حالات وراحات الضابط بتتسجل في officer_states/leaves، مش كخدمة
_STATUS_RE = re.compile(r"^(?:اجازه|راحه|فرقه|دوره|مرضي|غياب|انتداب|تدريب دوري|تقصيره)(?:\s|$)")
# صفوف الإجماليات في كشوف الأعداد
_TOTAL_RE = re.compile(r"^(?:ال)?(?:اجمالي|مجموع)(?:\s|$)")
# سطور تعليمات بعدد مجندين («عدد 10 مجند حفظ نظام…»، «مجند دنك علي ممشي…») — ملاحظة مش خدمة
_INSTRUCTION_PHRASE_RE = re.compile(r"^(?:عدد\s*\d*|\d+\s*(?:\(\s*)?)?\s*(?:مجند|مج)(?:\s|$)")


def _non_service_phrase(flat: str) -> bool:
    if _RANK_RE.match(flat) or _STATUS_RE.match(flat) or _TOTAL_RE.match(flat):
        return True
    return flat in {
        "خوارج", "الخوارج", "تقصيرات", "التقصيرات", "الراحات", "المركبات",
        "عدد المجندين", "عدد مجندين", "م", "الاسم", "الرتبه", "الدرجه",
    }


def _instruction_phrase(flat: str) -> bool:
    return bool(_INSTRUCTION_PHRASE_RE.match(flat))


def _canonical_board_section(value: str) -> str:
    if value in {norm(section) for section in CANONICAL_SECTIONS}:
        return value
    rules = (("خدمات اساسي", SECTION_BASIC), ("خدمات الطواري", SECTION_OCCASIONAL),
             ("الطواري", SECTION_OCCASIONAL), ("الاهداف", SECTION_TARGETS),
             ("معسكر فرعي", SECTION_SUBCAMP), ("ضابط عظيم", SECTION_GREAT),
             ("ضابط الامن", SECTION_SECURITY), ("ضابط امن", SECTION_SECURITY))
    return next((section for needle, section in rules if needle in value), "")


def _count_names(record: dict[str, Any]) -> list[str]:
    result = []
    for cell in record.get("raw_cells", []):
        value = clean_text(cell)
        flat = norm(value)
        if not value or re.fullmatch(r"[-\d\s()+./]+(?:مجند|مج|فرد)?", flat):
            continue
        if any(word in flat for word in ("الخدمات الاساسيه", "الخدمات الطاريه", "العدد", "المجموع", "الاجمالي")):
            continue
        result.append(value)
    return result[:2]


def _quarantined(records: list[dict[str, Any]]) -> set[tuple[str, str, str]]:
    return {(row["date"], row["role"], row["path"]) for row in records if row.get("verdict") == "quarantine"}


def _tidy_event_title(title: str) -> str:
    """عنوان قسم الحدث بصيغة واحدة: من غير «خدمات»/«ليوم…»/الساعة/التنصيص،
    وبتهجئة موحّدة — الوورد كاتب نفس الحدث بعشر صيغ («الماتش»، «خدمات المباراه»…)."""
    title = re.sub(r"[\"«»“”].*?[\"«»“”]", " ", title)
    title = re.sub(r"\s*(?:ليوم|يوم|عن يوم)\b.*$", "", title)
    title = re.sub(r"\s*(?:الساعه|الساعة)?\s*\d{1,2}(?::\d{1,2})?\s*[\u0635مظ]\b", " ", title)
    title = re.sub(r"^\s*خدمات\s+(?:تأمين\s+|تامين\s+)?", "", title)
    for old_word, new_word in (("المباراه", "المباراة"), ("مباراه", "مباراة"), ("الماتش", "المباراة"), ("ماتش", "مباراة"),
                               ("خطه", "خطة"), ("الإنتشار", "الانتشار"), ("أنتشار", "انتشار")):
        title = re.sub(rf"(?<![\u0621-\u064a]){old_word}(?![\u0621-\u064a])", new_word, title)
    title = re.sub(r"^خطة انتشار\b", "خطة الانتشار", title)
    title = re.sub(r"^المباراة\b", "مباراة", title)
    return re.sub(r"\s+", " ", title).strip(" ـ:-")


def _event_title(raw: str, known_sections: set[str]) -> str:
    title = clean_text(raw).strip("ـ:-")
    title = re.sub(r"\s+\d{1,2}(?::\d{1,2})?\s*[\u0635مظ]\s*$", "", title)
    title = _tidy_event_title(title) or title
    key = _base_key(title)
    ranked = sorted(((_score(key, _base_key(value)), value) for value in known_sections), reverse=True)
    # عنوان عام («مباراة»، «خطة الانتشار») ما يتربطش بقسم معروف — كان بيحوّل كل
    # مباراة إلى «مباراة ش قرية عامر»؛ الربط للعناوين المحددة القريبة جدًا بس
    if ranked and ranked[0][0] >= .75 and len(key.split()) > 1:
        return ranked[0][1]
    return title


def detect_events(records: list[dict[str, Any]], validations: list[dict[str, Any]],
                  known_sections: set[str]) -> list[dict[str, Any]]:
    bad = _quarantined(validations)
    found: dict[tuple[str, str], dict[str, Any]] = {}

    def add(day: str, raw: str, source: str, member_rows: int) -> None:
        title = _event_title(raw, known_sections)
        if not title or not EVENT_RE.search(norm(title)):
            return
        key = (day, title)
        row = found.setdefault(key, {"date": day, "event title": title, "sources": [], "member rows": 0})
        if source not in row["sources"]:
            row["sources"].append(source)
        row["member rows"] = max(row["member rows"], member_rows)

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[(record["date"], record["role"], record.get("path", ""))].append(record)
        if (record["date"], record["role"], record.get("path", "")) in bad:
            continue
        if record.get("role") == "board" and record.get("record_type") == "board_label":
            raw = clean_text(record.get("label"))
            if EVENT_RE.search(norm(raw)) and not _canonical_board_section(norm(raw)):
                add(record["date"], raw, "board", 0)
        elif record.get("record_type") == "afraad_subheading":
            raw = clean_text(record.get("section"))
            if EVENT_RE.search(norm(raw)) and not _canonical_board_section(norm(raw)):
                add(record["date"], raw, "afraad", 0)
    for (day, role, path), rows in grouped.items():
        if role not in {"match", "deployment"} or (day, role, path) in bad:
            continue
        internal_dates = {date.isoformat() for row in rows for value in
                          [row.get("raw_text", ""), *row.get("raw_cells", [])]
                          for date in dates_in_text(value)}
        if day not in internal_dates:
            continue
        header = next((row for row in rows if row.get("record_type") == f"{role}_header"), None)
        if not header:
            continue
        raw = _first_service_cell(header) or clean_text(Path(path).stem)
        if role == "deployment":
            raw = re.sub(r"\s+(?:يوم\s+)?(?:السبت|الاحد|الأحد|الاثنين|الثلاثاء|الاربعاء|الأربعاء|الخميس|الجمعة)?\s*"
                         r"\d{1,2}\s*[/.-]\s*\d{1,2}\s*[/.-]\s*\d{4}.*$", "", raw).strip()
            raw = raw if "انتشار" in norm(raw) else "خطة انتشار"
        else:
            raw = raw if re.search(r"(?:مبار|ماتش)", norm(raw)) else "مباراة"
        members = sum(row.get("record_type") == f"{role}_row" and bool(_first_service_cell(row)) for row in rows)
        add(day, raw, role, members)
    return [{"date": row["date"], "event title": row["event title"],
             "source": " + ".join(row.pop("sources")), "member rows": row["member rows"]}
            for row in sorted(found.values(), key=lambda value: (value["date"], value["event title"]))]


def _coverage(rows: list[dict[str, Any]], stats: dict[str, PhraseStats]) -> dict[str, Any]:
    overall = Counter()
    years: dict[str, Counter[str]] = defaultdict(Counter)
    sources: dict[str, Counter[str]] = defaultdict(Counter)
    confidence = {row["key"]: row["confidence"] for row in rows}
    for key, value in stats.items():
        level = confidence[key]
        overall[level] += value.count
        for year, count in value.years.items():
            years[year][level] += count
        for source, count in value.sources.items():
            sources[source][level] += count

    def summary(counter: Counter[str]) -> dict[str, Any]:
        total = sum(counter.values())
        result = {level: counter[level] for level in ("high", "medium", "low")}
        result["total"] = total
        result["high_medium_percent"] = round(100 * (counter["high"] + counter["medium"]) / total, 2) if total else 0
        return result
    return {"overall": summary(overall), "per_year": {key: summary(value) for key, value in sorted(years.items())},
            "per_source": {key: summary(value) for key, value in sorted(sources.items())}}


def run_aliases(ledger: Ledger, state: dict[str, Any], start: dt.date | None = None,
                end: dt.date | None = None, *, resume: bool = False) -> dict[str, Any]:
    source = ledger.staging_path("normalize")
    validate_path = ledger.staging_path("validate")
    if not source.exists():
        raise FileNotFoundError("يجب تشغيل normalize للدفعة أولًا")
    ledger.mark_stage(state, "aliases", "running")
    records = _load_jsonl(source)
    if start:
        records = [row for row in records if row["date"] >= start.isoformat()]
    if end:
        records = [row for row in records if row["date"] <= end.isoformat()]
    validations = _load_jsonl(validate_path) if validate_path.exists() else []
    vocabulary = build_vocabulary(ledger.data_dir, records)
    phrases, notes = collect_phrases(records, vocabulary)
    review_dir, decisions_dir = ledger.root / "review", ledger.root / "decisions"
    review_dir.mkdir(parents=True, exist_ok=True)
    decisions_dir.mkdir(parents=True, exist_ok=True)
    decisions = _csv_read(decisions_dir / "aliases.csv", ("key",))
    rows = []
    for key, stats in sorted(phrases.items(), key=lambda pair: (-pair[1].count, pair[0])):
        proposal = propose_alias(stats.examples.most_common(1)[0][0], vocabulary)
        decision = decisions.get((key,), {})
        row = {"key": key, "examples": " ; ".join(value for value, _ in stats.examples.most_common(5)),
               "count": stats.count, "first": min(stats.dates), "last": max(stats.dates),
               "contexts": " ; ".join(value for value, _ in stats.contexts.most_common()),
               "proposed canonical": decision.get("canonical") or proposal["canonical"],
               "confidence": decision.get("confidence") or proposal["confidence"],
               "runner-up": proposal["runner_up"], "category": decision.get("category") or proposal["category"],
               "kind": decision.get("kind") or proposal["kind"], "section": decision.get("section") or proposal["section"],
               "counts_in_summary": decision.get("counts_in_summary") or str(proposal["counts_in_summary"]).lower()}
        rows.append(row)
    _csv_write(review_dir / "aliases.csv", REVIEW_FIELDS, rows)
    # قرار المراجع ما بيضيعش لو مفتاحه اختفى من التشغيلة دي — بيفضل في آخر الملف
    current_keys = {(row["key"],) for row in rows}
    orphans = [row for key, row in sorted(decisions.items()) if key not in current_keys and _filled(row, ("key",))]
    _csv_write(decisions_dir / "aliases.csv", DECISION_FIELDS,
               [{"key": row["key"], **decisions.get((row["key"],), {})} for row in rows] + orphans)
    special_sections = {item.section for item in vocabulary if item.section not in CANONICAL_SECTIONS}
    events = detect_events(records, validations, special_sections)
    event_decisions = _csv_read(decisions_dir / "events.csv", ("date", "event title"))
    _rebind_event_decisions(events, event_decisions)
    final_events = []
    for event in events:
        decision = event_decisions.get((event["date"], event["event title"]), {})
        if decision.get("action") == "تجاهل":
            continue
        if decision.get("override title"):
            event["event title"] = decision["override title"]
        final_events.append(event)
    _csv_write(review_dir / "events.csv", EVENT_FIELDS, final_events)
    current_events = {(event["date"], event["event title"]) for event in events}
    event_orphans = [row for key, row in sorted(event_decisions.items())
                     if key not in current_events and _filled(row, ("date", "event title"))]
    _csv_write(decisions_dir / "events.csv", EVENT_DECISION_FIELDS,
               [{"date": event["date"], "event title": event["event title"],
                 **event_decisions.get((event["date"], event["event title"]), {})} for event in events] + event_orphans)
    atomic_write_jsonl(ledger.staging_path("alias-notes"), notes)
    coverage = _coverage(rows, phrases)
    low = [{"key": row["key"], "count": row["count"], "examples": row["examples"]}
           for row in rows if row["confidence"] == "low"][:40]
    event_years = {year: len({event["date"] for event in final_events if event["date"].startswith(year)})
                   for year in sorted({event["date"][:4] for event in final_events})}
    reference_names = set()
    for date in ("2026-09-01", "2026-09-02"):
        path = ledger.data_dir / "days" / "2026" / "09" / f"{date}.json"
        if path.exists():
            reference_names.update(row.get("name", "") for row in json.loads(path.read_text(encoding="utf-8")).get("assignments", []))
    exact_failures = sorted(name for name in reference_names
                            if propose_alias(name, vocabulary)["canonical"] != name or
                            propose_alias(name, vocabulary)["confidence"] != "high")
    report = {"distinct_keys": len(rows), "coverage": coverage, "top_40_low": low,
              "event_days_per_year": event_years,
              "reference_exact_failures": exact_failures, "notes": len(notes), "version": VERSION}
    atomic_write_json(ledger.report_path("aliases.json"), report)
    checkpoint = report | {"events": len(final_events)}
    ledger.mark_stage(state, "aliases", "complete", checkpoint)
    return checkpoint


__all__ = ["VERSION", "VocabularyItem", "build_vocabulary", "collect_phrases", "detect_events",
           "propose_alias", "run_aliases", "service_key"]

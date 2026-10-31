"""تصحيح محافظ لأخطاء الاستيراد التاريخية (Class C).

المرحلة بتعيد discover -> extract -> validate -> normalize -> resolve -> aliases ->
transform من ملفات الأرشيف، وبتقارن كل حقل بثلاث نسخ:

* archive: ناتج المستورد الحالي من Word/Excel.
* original: نسخة transform اللي الـbatch الأصلي كتبها.
* stored: القيمة الموجودة دلوقتي.

الحقل مابيتصححش إلا لو stored == original، ومفيش change-log بعد
لحظة الـbatch يقول إن نفس الحقل اتلمس. لو snapshot/مصدر الصف ناقص أو
المطابقة مش وحيدة، الحقل بيتساب للمراجعة.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import os
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from backend import store

from .aliases import VERSION as ALIASES_VERSION, run_aliases
from .discover import VERSION as DISCOVER_VERSION, run_discover
from .extract import VERSION as EXTRACT_VERSION, run_extract
from .ledger import Ledger
from .normalize import VERSION as NORMALIZE_VERSION, run_normalize
from .resolve import VERSION as RESOLVE_VERSION, run_resolve
from .single_day import day_files
from .transform import VERSION as TRANSFORM_VERSION, run_transform
from .validate import VERSION as VALIDATE_VERSION, run_validate
from .verify import transformed_days

KINDS = ("board", "afraad_basic", "afraad_emergency", "officers", "counts")
KIND_LABELS = {
    "board": "تكليفات اللوحة", "afraad_basic": "أفراد - خدمات أساسية",
    "afraad_emergency": "أفراد - خدمات طارئة", "officers": "حالات الضباط",
    "counts": "الأعداد",
}
FIELDS = {
    "board": ("section", "name", "time", "party", "officer_ids", "personnel_ids", "conscript_count"),
    "afraad_emergency": ("time", "party", "personnel_ids", "conscript_count", "weapon"),
    "afraad_basic": ("morning_person_id", "night_person_id", "count", "weapon", "schedule"),
    "officers": ("status", "taqseera", "note"),
    "counts": ("name", "block", "count", "party", "weapon", "order"),
}
_MISSING = object()


@dataclass
class Op:
    kind: str
    day: str
    entity_id: str
    field: str
    archive: Any
    stored: Any
    original: Any
    status: str = "correct"       # correct | protected
    reason: str = ""
    risk: str = ""


@dataclass
class Unresolved:
    kind: str
    day: str
    entity_id: str
    field: str
    reason: str
    archive: Any = None
    stored: Any = None


@dataclass
class Report:
    start: str
    end: str
    kinds: tuple[str, ...]
    ops: list[Op] = field(default_factory=list)
    unresolved: list[Unresolved] = field(default_factory=list)
    extraction_errors: list[str] = field(default_factory=list)


def _json_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _same(left: Any, right: Any) -> bool:
    return left == right


def _source_keys(source: Any) -> set[tuple[Any, ...]]:
    """مفتاح الصف من مكانه في الملف، مش من ID متولد ممكن يتحرك."""
    if not isinstance(source, dict):
        return set()
    out = set()
    if source.get("path"):
        out.add((source.get("path"), source.get("table"), source.get("row"), source.get("rule")))
    for merged in source.get("merged") or []:
        out |= _source_keys(merged)
    return out


def _match_by_source(old_ids: list[str], new_ids: list[str], old_prov: dict[str, Any],
                     new_prov: dict[str, Any]) -> tuple[dict[str, str], set[str]]:
    matched: dict[str, str] = {}
    ambiguous: set[str] = set()
    for old_id in old_ids:
        source = _source_keys(old_prov.get(old_id))
        scored = []
        for new_id in new_ids:
            overlap = len(source & _source_keys(new_prov.get(new_id)))
            if overlap:
                scored.append((overlap, new_id))
        if scored:
            best = max(score for score, _ in scored)
            hits = [identifier for score, identifier in scored if score == best]
            if len(hits) == 1:
                matched[old_id] = hits[0]
            else:
                ambiguous.add(old_id)
        elif old_id in new_ids:
            # الـID بديل محافظ للقوائم اللي provenance فيها مش مفهرس بالـID.
            matched[old_id] = old_id
        else:
            ambiguous.add(old_id)
    # ممن اتنين قدام يمسكوا نفس الصف الجديد بعد merge؛ ساعتها منصححش الاتنين.
    reverse = Counter(matched.values())
    for old_id, new_id in list(matched.items()):
        if reverse[new_id] > 1:
            ambiguous.add(old_id)
            del matched[old_id]
    return matched, ambiguous


def _match_counts(old_ids: list[str], new_ids: list[str], old_sources: dict[str, Any],
                  new_sources: dict[str, Any]) -> tuple[dict[str, str], set[str]]:
    """صف Excel الواحد ممكن يشيل كذا (خدمة، عدد)؛ `raw` هنا جزء من الهوية
    عشان مانعتبرش كل أزواج الصف الواحد غامضة.
    """
    def key(source: Any):
        if not isinstance(source, dict):
            return None
        return (source.get("path"), source.get("table"), source.get("row"),
                source.get("rule"), source.get("raw"))

    index: dict[tuple[Any, ...], list[str]] = defaultdict(list)
    for identifier in new_ids:
        if (source_key := key(new_sources.get(identifier))) is not None:
            index[source_key].append(identifier)
    matched, ambiguous = {}, set()
    for identifier in old_ids:
        hits = index.get(key(old_sources.get(identifier)), [])
        if len(hits) == 1:
            matched[identifier] = hits[0]
        else:
            ambiguous.add(identifier)
    return matched, ambiguous


def _change_day(change: dict[str, Any]) -> str:
    day = change.get("day") or ""
    if day:
        return day
    reason = str(change.get("reason") or "")
    import re
    hit = re.search(r"20\d\d-\d\d-\d\d", reason)
    return hit.group(0) if hit else ""


def _batch_times(data: dict[str, Any]) -> dict[str, str]:
    return {str(row.get("entity_id")): str(row.get("ts") or "")
            for row in data.get("change_log") or [] if row.get("entity") == "import"}


def _logged_edit(data: dict[str, Any], batch_time: str, kind: str, day: str,
                 entity_id: str, field_name: str) -> str:
    entities = {
        "board": {"assignment"}, "afraad_emergency": {"assignment"},
        "officers": {"officer_state"}, "afraad_basic": {"afraad", "personnel_daily"},
        "counts": {"counts", "service_count"},
    }[kind]
    for row in data.get("change_log") or []:
        if row.get("entity") not in entities or str(row.get("entity_id")) != entity_id:
            continue
        if _change_day(row) != day or (batch_time and str(row.get("ts") or "") <= batch_time):
            continue
        before, after = row.get("before"), row.get("after")
        if not isinstance(before, dict) or not isinstance(after, dict):
            return f"سجل تغيير لاحق ({row.get('id', '')}) من غير فرق حقول واضح"
        if before.get(field_name, _MISSING) != after.get(field_name, _MISSING):
            return f"الحقل اتعدل بعد الاستيراد ({row.get('id', '')})"
    return ""


def _risk(field_name: str, old: Any, new: Any) -> str:
    if field_name in {"officer_ids", "personnel_ids", "morning_person_id", "night_person_id"}:
        if old and new:
            return "person_id_swap"
    if field_name in {"count", "conscript_count"}:
        return "count_change"
    return ""


def _add_fields(report: Report, data: dict[str, Any], batch_time: str, kind: str, day: str,
                entity_id: str, old: dict[str, Any], new: dict[str, Any], current: dict[str, Any]) -> None:
    for name in FIELDS[kind]:
        original = old.get(name)
        archive = new.get(name)
        stored = current.get(name)
        if _same(archive, stored):
            continue
        op = Op(kind, day, entity_id, name, copy.deepcopy(archive), copy.deepcopy(stored),
                copy.deepcopy(original), risk=_risk(name, stored, archive))
        if not _same(stored, original):
            op.status = "protected"
            op.reason = "القيمة الحالية مش نسخة الاستيراد الأصلية"
        elif reason := _logged_edit(data, batch_time, kind, day, entity_id, name):
            op.status = "protected"
            op.reason = reason
        report.ops.append(op)


def _unresolved_fields(report: Report, kind: str, day: str, entity_id: str, reason: str,
                       current: dict[str, Any] | None = None) -> None:
    for name in FIELDS[kind]:
        report.unresolved.append(Unresolved(kind, day, entity_id, name, reason,
                                            stored=(current or {}).get(name)))


def _rows(blob: dict[str, Any], key: str) -> dict[str, dict[str, Any]]:
    return {str(row.get("id")): row for row in blob.get(key) or [] if row.get("id")}


def _dated_items(versions: list[dict[str, Any]], day: str) -> list[dict[str, Any]]:
    chosen = []
    for version in sorted(versions or [], key=lambda row: row.get("from", "")):
        if version.get("from", "") <= day:
            chosen = version.get("items") or []
    return chosen


def _plan_day(report: Report, data: dict[str, Any], day: str, original: dict[str, Any],
              archive: dict[str, Any], old_prov: dict[str, Any], new_prov: dict[str, Any],
              batch_time: str) -> None:
    current_blob = store.split(data)[1].get(day, {})

    # اللوحة + صفوف طوارئ الأفراد ليهم نفس الكيان المخزن؛ المصدر هو اللي بيفصلهم.
    if {"board", "afraad_emergency"} & set(report.kinds):
        old_rows, new_rows, cur_rows = (_rows(original, "assignments"), _rows(archive, "assignments"),
                                        _rows(current_blob, "assignments"))
        mapping, ambiguous = _match_by_source(list(old_rows), list(new_rows),
                                              old_prov.get("assignments") or {},
                                              new_prov.get("assignments") or {})
        for old_id, old_row in old_rows.items():
            source = old_prov.get("assignments", {}).get(old_id) or {}
            emergency = any(key[-1] == "afraad_emergency_row" for key in _source_keys(source))
            kind = "afraad_emergency" if emergency else "board"
            if kind not in report.kinds:
                continue
            current = cur_rows.get(old_id)
            if current is None:
                _unresolved_fields(report, kind, day, old_id, "الصف المخزن الأصلي اتمسح/اتغير ID بتاعه")
            elif old_id in ambiguous or old_id not in mapping:
                _unresolved_fields(report, kind, day, old_id, "مصدر الصف مش مطابق لصف واحد في إعادة الاستخراج", current)
            else:
                _add_fields(report, data, batch_time, kind, day, old_id, old_row,
                            new_rows[mapping[old_id]], current)

    if "afraad_basic" in report.kinds:
        from backend.dated import afraad_basic_on

        old_rows = original.get("afraad_basic") or {}
        new_rows = archive.get("afraad_basic") or {}
        cur_rows = current_blob.get("afraad_basic") or {}
        old_names = {row["id"]: row.get("name", "") for row in afraad_basic_on(data, day)}
        new_ids = defaultdict(list)
        for identifier, name in (archive.get("_afraad_names") or {}).items():
            new_ids[name].append(identifier)
        for entry_id, old_row in old_rows.items():
            current = cur_rows.get(entry_id)
            matches = new_ids.get(old_names.get(entry_id, ""), [])
            new = new_rows.get(matches[0]) if len(matches) == 1 else None
            if current is None or new is None:
                _unresolved_fields(report, "afraad_basic", day, entry_id,
                                   "اسم الخدمة الأساسية مش مطابق لصف واحد في إعادة الاستخراج", current)
                continue
            _add_fields(report, data, batch_time, "afraad_basic", day, entry_id, old_row, new, current)

    if "officers" in report.kinds:
        old_rows, new_rows = original.get("officer_states") or {}, archive.get("officer_states") or {}
        cur_rows = current_blob.get("officer_states") or {}
        for officer_id, old_row in old_rows.items():
            current, new = cur_rows.get(officer_id), new_rows.get(officer_id)
            if current is None or new is None:
                _unresolved_fields(report, "officers", day, officer_id,
                                   "هوية الضابط/حالة اليوم مش موجودة في النسخ التلاتة", current)
                continue
            _add_fields(report, data, batch_time, "officers", day, officer_id, old_row, new, current)

    if "counts" in report.kinds:
        old_rows, new_rows, cur_rows = (_rows(original.get("counts") or {}, "entries"),
                                        _rows(archive.get("counts") or {}, "entries"),
                                        _rows(current_blob.get("counts") or {}, "entries"))
        old_sources = {identifier: source for identifier, source in
                       zip(old_rows, old_prov.get("counts") or [])}
        new_sources = {identifier: source for identifier, source in
                       zip(new_rows, new_prov.get("counts") or [])}
        mapping, ambiguous = _match_counts(list(old_rows), list(new_rows), old_sources, new_sources)
        for entry_id, old_row in old_rows.items():
            current = cur_rows.get(entry_id)
            new = new_rows.get(mapping.get(entry_id, "")) if entry_id not in ambiguous else None
            if current is None or new is None:
                _unresolved_fields(report, "counts", day, entry_id,
                                   "مصدر صف الأعداد مش مطابق لصف واحد في إعادة الاستخراج", current)
                continue
            _add_fields(report, data, batch_time, "counts", day, entry_id, old_row, new, current)


def _write_scratch_data(data: dict[str, Any], target: Path) -> None:
    core, days = store.split(data)
    target.mkdir(parents=True, exist_ok=True)
    (target / "core.json").write_text(json.dumps(core, ensure_ascii=False), encoding="utf-8")
    for day, blob in days.items():
        path = target / "days" / day[:4] / day[5:7] / f"{day}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(blob, ensure_ascii=False), encoding="utf-8")


def extract_range(data: dict[str, Any], archive_root: Path, start: str, end: str,
                  decision_source: Path | None = None) -> tuple[dict, dict, list[str]]:
    """إعادة استخراج المدى مرة واحدة في temp. الـdata المنسوخة core+days بس؛
    ملفات الأرشيف symlinks للقراءة، ومخرجات importer جديدة مؤقتة.
    """
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="correction-024-") as raw:
        root = Path(raw)
        scratch, archive = root / "data", root / "archive"
        _write_scratch_data(data, scratch)
        current, stop = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
        while current <= stop:
            day = current.isoformat()
            for source in day_files(archive_root, day):
                target = archive / archive_root.name / str(current.month) / str(current.day) / source.name
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.symlink(source, target)
                except FileExistsError:
                    pass
            current += dt.timedelta(days=1)
        batch = "correction-024-extract"
        ledger = Ledger(scratch, batch)
        begin, finish = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
        state = ledger.initialise(
            {"archive": str(archive), "data_dir": str(scratch), "from": start, "to": end,
             "batch": batch, "write": False, "resume": False},
            {"discover": DISCOVER_VERSION, "extract": EXTRACT_VERSION, "validate": VALIDATE_VERSION,
             "normalize": NORMALIZE_VERSION, "resolve": RESOLVE_VERSION, "aliases": ALIASES_VERSION,
             "transform": TRANSFORM_VERSION})
        run_discover(archive, ledger, begin, finish, state)
        run_extract(archive, ledger, begin, finish, state)
        run_validate(ledger, state, begin, finish)
        run_normalize(ledger, state, begin, finish)
        run_resolve(ledger, state, begin, finish, decision_source=decision_source)
        run_aliases(ledger, state, begin, finish, decision_source=decision_source)
        run_transform(ledger, state, begin, finish)
        days = transformed_days(ledger)
        delta_path = ledger.root / "staging" / batch / "transform" / "core_delta.json"
        delta = json.loads(delta_path.read_text(encoding="utf-8")) if delta_path.exists() else {}
        versions = ((delta.get("reference_lists") or {}).get("afraad_basic") or [])
        for day, blob in days.items():
            blob["_afraad_names"] = {row["id"]: row.get("name", "")
                                     for row in _dated_items(versions, day)}
        provenance = {}
        for day in days:
            path = ledger.root / "provenance" / day[:4] / day[5:7] / f"{day}.json"
            provenance[day] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        unresolved_path = ledger.staging_path("resolve-unresolved")
        if unresolved_path.exists():
            errors.append(f"مشاهدات هوية غير محلولة: {sum(1 for x in unresolved_path.read_text().splitlines() if x.strip())}")
        return days, provenance, errors


def _load_original(provenance_root: Path, marker: dict[str, Any], day: str) -> tuple[dict, dict]:
    batch = str(marker.get("batch") or "")
    if not batch:
        return {}, {}
    day_path = provenance_root / "staging" / batch / "transform" / "days" / f"{day}.json"
    prov_path = provenance_root / "provenance" / day[:4] / day[5:7] / f"{day}.json"
    original = json.loads(day_path.read_text(encoding="utf-8")) if day_path.exists() else {}
    provenance = json.loads(prov_path.read_text(encoding="utf-8")) if prov_path.exists() else {}
    return original, provenance


def _apply(report: Report, data: dict[str, Any]) -> int:
    applied = 0
    day_blobs = store.split(data)[1]
    for op in report.ops:
        if op.status != "correct":
            continue
        blob = day_blobs.get(op.day)
        target = None
        if op.kind in {"board", "afraad_emergency"}:
            target = next((row for row in blob.get("assignments") or [] if row.get("id") == op.entity_id), None)
        elif op.kind == "afraad_basic":
            target = (blob.get("afraad_basic") or {}).get(op.entity_id)
        elif op.kind == "officers":
            target = (blob.get("officer_states") or {}).get(op.entity_id)
        elif op.kind == "counts":
            target = next((row for row in (blob.get("counts") or {}).get("entries") or []
                           if row.get("id") == op.entity_id), None)
        if target is None or target.get(op.field) != op.stored:
            op.status, op.reason = "protected", "القيمة اتغيرت أثناء بناء الخطة"
            continue
        target[op.field] = copy.deepcopy(op.archive)
        applied += 1
    if applied:
        # نركب ملفات الأيام بعد التعديلات من غير ما نقرب باقي core.
        for key, name in store.DAY_SECTIONS.items():
            data[key] = {day: blob[name] for day, blob in day_blobs.items() if name in blob}
    return applied


def run_import(data: dict[str, Any], archive_root: Path, start: str, end: str,
               kinds: tuple[str, ...] = KINDS, provenance_root: Path | None = None,
               archive_days: dict[str, dict[str, Any]] | None = None,
               archive_provenance: dict[str, dict[str, Any]] | None = None,
               original_loader: Callable[[dict[str, Any], str], tuple[dict, dict]] | None = None,
               apply: bool = True) -> Report:
    report = Report(start, end, tuple(kinds))
    if archive_days is None:
        decision_source = (provenance_root or (store.ROOT / "data" / "import")) / "decisions"
        archive_days, archive_provenance, errors = extract_range(
            data, archive_root, start, end, decision_source=decision_source)
        report.extraction_errors += errors
    archive_provenance = archive_provenance or {}
    provenance_root = provenance_root or (store.ROOT / "data" / "import")
    original_loader = original_loader or (lambda marker, day: _load_original(provenance_root, marker, day))
    times = _batch_times(data)
    blobs = store.split(data)[1]
    current, stop = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    while current <= stop:
        day = current.isoformat()
        blob = blobs.get(day) or {}
        marker = blob.get("import") or {}
        archive = archive_days.get(day)
        if not marker:
            for kind in kinds:
                report.unresolved.append(Unresolved(kind, day, "day", "*", "اليوم مفيهوش علامة import"))
        elif archive is None:
            for kind in kinds:
                report.unresolved.append(Unresolved(kind, day, "day", "*", "إعادة الاستخراج ماطلعتش اليوم"))
        else:
            original, old_prov = original_loader(marker, day)
            if not original:
                for kind in kinds:
                    report.unresolved.append(Unresolved(kind, day, "day", "*",
                                                        f"مفيش transform snapshot للـbatch {marker.get('batch', '')}"))
            else:
                _plan_day(report, data, day, original, archive, old_prov,
                          archive_provenance.get(day) or {}, times.get(str(marker.get("batch") or ""), ""))
        current += dt.timedelta(days=1)
    if apply:
        _apply(report, data)
    return report


def totals(report: Report) -> dict[str, Any]:
    result = {kind: {"correct": 0, "protected": 0, "unresolved": 0} for kind in report.kinds}
    fields: dict[tuple[str, str], Counter] = defaultdict(Counter)
    risks = Counter()
    risk_status: dict[str, Counter] = defaultdict(Counter)
    for op in report.ops:
        result.setdefault(op.kind, Counter())[op.status] += 1
        fields[(op.kind, op.field)][op.status] += 1
        if op.risk:
            risks[op.risk] += 1
            risk_status[op.risk][op.status] += 1
    for item in report.unresolved:
        if item.kind in result:
            result[item.kind]["unresolved"] += 1
            fields[(item.kind, item.field)]["unresolved"] += 1
    return {"kinds": result, "fields": fields, "risks": risks, "risk_status": risk_status,
            "correct": sum(v["correct"] for v in result.values()),
            "protected": sum(v["protected"] for v in result.values()),
            "unresolved": sum(v["unresolved"] for v in result.values())}


def render_preview(report: Report, mode: str = "dry-run", rates: dict[str, Any] | None = None) -> str:
    total = totals(report)
    lines = ["# معاينة التصحيح الآمن لأخطاء الاستيراد (024)", "",
             f"- النطاق: `{report.start}` .. `{report.end}`.",
             f"- الوضع: **{mode}**. المعاينة لا تعتبر موافقة على المخاطر.",
             "- قاعدة الحماية: الحالي = snapshot الاستيراد، ولا يوجد تغيير لاحق لنفس الحقل.", "",
             "## الإجمالي حسب النوع", "",
             "| النوع | سيُصحح | محمي لتعديل لاحق | غير محسوم |", "|---|---:|---:|---:|"]
    for kind in report.kinds:
        row = total["kinds"][kind]
        lines.append(f"| {KIND_LABELS[kind]} | {row['correct']} | {row['protected']} | {row['unresolved']} |")
    lines += ["", "## الإجمالي حسب الحقل", "",
              "| النوع / الحقل | يُصحح | محمي | غير محسوم |", "|---|---:|---:|---:|"]
    for (kind, name), counts in sorted(total["fields"].items()):
        lines.append(f"| {KIND_LABELS.get(kind, kind)} / `{name}` | {counts['correct']} | {counts['protected']} | {counts['unresolved']} |")
    lines += ["", "## تغييرات عالية الخطورة", "",
              f"- تبديلات هويات أشخاص: **{total['risks']['person_id_swap']}** "
              f"(يُصحح {total['risk_status']['person_id_swap']['correct']}، محمي {total['risk_status']['person_id_swap']['protected']}).",
              f"- تغييرات عدد/قوام: **{total['risks']['count_change']}** "
              f"(يُصحح {total['risk_status']['count_change']['correct']}، محمي {total['risk_status']['count_change']['protected']})."]
    risky = [op for op in report.ops if op.risk]
    for op in risky:
        lines.append(f"- `{op.day}` {KIND_LABELS[op.kind]} `{op.entity_id}.{op.field}`: "
                     f"{_json_value(op.stored)} → {_json_value(op.archive)} ({op.status}).")
    by_day: dict[str, list[Any]] = defaultdict(list)
    for item in [*report.ops, *report.unresolved]:
        by_day[item.day].append(item)
    lines += ["", "## التفاصيل حسب اليوم"]
    for day, items in sorted(by_day.items()):
        lines += ["", f"### {day}", ""]
        for item in items:
            if isinstance(item, Op):
                tail = f" — {item.reason}" if item.reason else ""
                lines.append(f"- **{item.status}** {KIND_LABELS[item.kind]} `{item.entity_id}.{item.field}`: "
                             f"الأرشيف={_json_value(item.archive)}، المخزن={_json_value(item.stored)}، "
                             f"الجديد={_json_value(item.archive) if item.status == 'correct' else _json_value(item.stored)}{tail}")
            else:
                lines.append(f"- **unresolved** {KIND_LABELS.get(item.kind, item.kind)} "
                             f"`{item.entity_id}.{item.field}` — {item.reason}.")
    if report.extraction_errors:
        lines += ["", "## تحذيرات إعادة الاستخراج", ""] + [f"- {x}" for x in report.extraction_errors]
    if rates:
        lines += ["", "## قياس tools/compare_dailies.py", ""]
        for label, value in rates.items():
            lines.append(f"- {label}: `{value}`")
    return "\n".join(lines) + "\n"

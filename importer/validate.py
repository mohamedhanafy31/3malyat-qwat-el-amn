"""التحقق البنيوي من مخرجات EXTRACT قبل أي تفسير دلالي."""

from __future__ import annotations

import datetime as dt
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any

from .discover import AUTHORITATIVE_ROLES
from .ledger import Ledger, atomic_write_jsonl
from .textnorm import WEEKDAYS, clean_text, norm


VERSION = "1"
ALLOWED_ADJACENT = {"duty_list", "command_order", "afraad"}
LEVEL = {"ok": 0, "warn": 1, "quarantine": 2}
NUMBER_ONLY_RE = re.compile(r"^[\d\s./()\-]+$")
CELL_REF_RE = re.compile(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", re.I)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _doc_key(record: dict[str, Any]) -> tuple[str, str, str]:
    return record["date"], record["role"], record["path"]


def _worst(reasons: list[tuple[str, str]]) -> str:
    return max((verdict for verdict, _ in reasons), key=LEVEL.get, default="ok")


def _validation(record: dict[str, Any], index: int,
                reasons: list[tuple[str, str]], details: dict[str, Any] | None = None) -> dict[str, Any]:
    verdict = _worst(reasons)
    codes = list(dict.fromkeys(code for _, code in reasons))
    primary = next((code for level, code in reasons if level == verdict), "ok")
    return {
        "record_type": "validation",
        "source_index": index,
        "source_record_type": record["record_type"],
        "date": record["date"],
        "role": record["role"],
        "path": record["path"],
        "file_sha1": record.get("file_sha1"),
        "verdict": verdict,
        "reason_code": primary,
        "reason_codes": codes or ["ok"],
        **(details or {}),
    }


def _date_reasons(records: list[dict[str, Any]]) -> list[tuple[str, str]]:
    document = records[0]
    expected = dt.date.fromisoformat(document["date"])
    role = document["role"]
    found: list[dt.date] = []
    dated_titles: list[dict[str, Any]] = []
    for record in records:
        if record.get("parsed_dates"):
            dated_titles.append(record)
        for value in record.get("parsed_dates", []):
            parsed = dt.date.fromisoformat(value)
            if parsed not in found:
                found.append(parsed)
    source_date = document.get("source_title_date")
    if source_date:
        found = [dt.date.fromisoformat(source_date)]
    elif found:
        found = found[:1]
    weekdays = [record["weekday"] for record in dated_titles[:1] if record.get("weekday")]
    if not weekdays:
        weekdays = [record["weekday"] for record in records[:9] if record.get("weekday")][:1]
    reasons: list[tuple[str, str]] = []
    weekday_date = expected
    if found:
        closest = min(found, key=lambda value: abs((value - expected).days))
        weekday_date = closest
        delta = abs((closest - expected).days)
        if delta and delta == 1 and role in ALLOWED_ADJACENT:
            reasons.append(("warn", "title_date_adjacent"))
        elif delta:
            reasons.append(("quarantine", "title_date_mismatch"))
    for weekday in weekdays:
        if WEEKDAYS.get(weekday) != weekday_date.weekday():
            reasons.append(("warn", "weekday_mismatch"))
            break
    return reasons


def _row_signature(records: list[dict[str, Any]], role: str) -> dict[str, Any]:
    signature: dict[str, Any] = {}
    occurrences: Counter[str] = Counter()

    def put(key: str, value: Any) -> None:
        key = clean_text(key)
        if not key:
            return
        occurrences[key] += 1
        signature[f"{key}#{occurrences[key]}"] = value

    if role == "roster":
        for record in records:
            if record["record_type"] != "roster_row":
                continue
            fields = record.get("fields", {})
            put(fields.get("الاسم", ""), clean_text(
                fields.get("التشغيل اليومي", "") or fields.get("ملاحظات", "")
            ))
    elif role == "board":
        for record in records:
            if record["record_type"] in {"board_row", "board_label"}:
                put(record.get("label", ""), clean_text(record.get("manning", "")))
    elif role == "afraad":
        header: dict[int, str] = {}
        for record in records:
            if record["record_type"] != "afraad_header":
                continue
            for value, columns in zip(record.get("raw_cells", []), record.get("column_indexes", [])):
                for column in columns:
                    header[column] = norm(value)
            break
        service = next((column for column, value in header.items() if value == "الخدمه"), None)
        morning = next((column for column, value in header.items() if "الصباحيه" in value), None)
        night = next((column for column, value in header.items() if "الليليه" in value), None)
        for record in records:
            if record["record_type"] != "afraad_basic_row":
                continue
            grid = {column: value for value, columns in
                    zip(record.get("raw_cells", []), record.get("column_indexes", []))
                    for column in columns}
            put(grid.get(service, ""), (
                clean_text(grid.get(morning, "")), clean_text(grid.get(night, "")),
            ))
    return signature


def _similarity(left: dict[str, Any], right: dict[str, Any], day: dt.date) -> dict[str, Any]:
    denominator = max(len(left), len(right))
    matches = sum(key in right and right[key] == value for key, value in left.items())
    return {
        "date": day.isoformat(),
        "identical_rows": matches,
        "compared_rows": denominator,
        "similarity": round(matches / denominator, 6) if denominator else 0.0,
    }


def _is_title_typo(expected: dt.date, title: dt.date,
                   metadata: dict[str, Any]) -> bool:
    filename = metadata.get("filename_date")
    folder = metadata.get("folder_date")
    if filename != expected.isoformat() or folder != expected.isoformat() or title.day != expected.day:
        return False
    return (title.month != expected.month) ^ (title.year != expected.year)


def _core_date_reasons(key: tuple[str, str, str], records: list[dict[str, Any]],
                       groups: dict[tuple[str, str, str], list[tuple[int, dict[str, Any]]]],
                       metadata: dict[str, Any]) -> tuple[list[tuple[str, str]], dict[str, Any]]:
    expected = dt.date.fromisoformat(key[0])
    role = key[1]
    title_value = records[0].get("source_title_date")
    if not title_value:
        title_value = next((values[0] for record in records
                            if (values := record.get("parsed_dates"))), None)
    title = dt.date.fromisoformat(title_value) if title_value else None
    filename_value = metadata.get("filename_date")
    filename = dt.date.fromisoformat(filename_value) if filename_value else None
    title_typo = bool(title and title != expected and _is_title_typo(expected, title, metadata))
    comparison_needed = bool(
        (title and title != expected and not title_typo) or
        (filename and filename != expected)
    )
    candidates: list[dt.date] = []
    if comparison_needed:
        for candidate in (title, filename, expected - dt.timedelta(days=1), expected + dt.timedelta(days=1)):
            if candidate and candidate != expected and candidate not in candidates:
                candidates.append(candidate)
    own = _row_signature(records, role)
    similarities: list[dict[str, Any]] = []
    if candidates:
        all_records = {dt.date.fromisoformat(day): [record for _, record in indexed]
                       for (day, group_role, _), indexed in groups.items() if group_role == role}
        similarities = [_similarity(own, _row_signature(all_records[candidate], role), candidate)
                        for candidate in candidates if candidate in all_records]
    reasons: list[tuple[str, str]] = []
    if title_typo:
        reasons.append(("warn", "title_typo"))
    elif title and title != expected:
        best = max(similarities, key=lambda item: item["similarity"], default=None)
        if best and best["similarity"] >= 0.9:
            reasons.append(("quarantine", f"copy_of_other_day:{best['date']}"))
        else:
            reasons.append(("warn", "title_date_differs_content_unique"))
    elif filename and filename != expected:
        match = next((item for item in similarities if item["date"] == filename.isoformat()), None)
        if match and match["similarity"] >= 0.9:
            reasons.append(("quarantine", f"copy_of_other_day:{match['date']}"))

    dated_title = next((record for record in records if record.get("parsed_dates")), None)
    weekday = dated_title.get("weekday") if dated_title else None
    weekday_date = title or expected
    if weekday and WEEKDAYS.get(weekday) != weekday_date.weekday():
        reasons.append(("warn", "weekday_mismatch"))
    details = {
        "title_date": title_value,
        "filename_date": filename_value,
        "folder_date": metadata.get("folder_date"),
        "content_signature_rows": len(own),
        "similarities": similarities,
    }
    return reasons, details


def _meaningful_roster_row(record: dict[str, Any]) -> bool:
    values = [value.strip() for value in record.get("raw_cells", []) if value.strip()]
    return bool(values) and not all(NUMBER_ONLY_RE.fullmatch(value) for value in values)


def _roster_name(record: dict[str, Any]) -> str:
    fields = record.get("fields", {})
    return fields.get("الاسم", "").strip()


def _column_number(value: str) -> int:
    result = 0
    for letter in value.upper():
        result = result * 26 + ord(letter) - 64
    return result - 1


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


def _xlsx_total_reasons(records: list[dict[str, Any]]) -> dict[int, list[tuple[str, str]]]:
    values: dict[tuple[int, int, int], Any] = {}
    for record in records:
        table = record.get("table_index")
        row = record.get("row_index")
        if table is None or row is None:
            continue
        for column, value in enumerate(record.get("raw_cells", [])):
            values[table, row, column] = value
    result: dict[int, list[tuple[str, str]]] = defaultdict(list)
    for index, record in enumerate(records):
        formulas = record.get("formulas", {})
        for column_value, formula in formulas.items():
            column = int(column_value)
            matches = list(CELL_REF_RE.finditer(formula))
            if not matches:
                continue
            expected = 0.0
            found = False
            for match in matches:
                c1, r1, c2, r2 = match.groups()
                for row in range(int(r1) - 1, int(r2)):
                    for source_column in range(_column_number(c1), _column_number(c2) + 1):
                        number = _number(values.get((record["table_index"], row, source_column)))
                        if number is not None:
                            expected += number
                            found = True
            actual = _number(record.get("raw_cells", [])[column] if column < len(record.get("raw_cells", [])) else None)
            if found and actual is not None and abs(actual - expected) > 1e-9:
                result[index].append(("warn", "xlsx_total_mismatch"))
    return result


def validate_records(records: list[dict[str, Any]],
                     document_metadata: dict[tuple[str, str, str], dict[str, Any]] | None = None
                     ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str, str], list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for index, record in enumerate(records):
        grouped[_doc_key(record)].append((index, record))
    reasons_by_index: dict[int, list[tuple[str, str]]] = defaultdict(list)
    details_by_index: dict[int, dict[str, Any]] = {}
    doc_reasons: dict[tuple[str, str, str], list[tuple[str, str]]] = defaultdict(list)
    document_metadata = document_metadata or {}

    for key, indexed in grouped.items():
        docs = [record for _, record in indexed]
        first_index, first = indexed[0]
        reasons = doc_reasons[key]
        if first["record_type"] == "extract_error":
            reasons.append(("quarantine", "extract_error"))
        elif first["role"] in {"roster", "afraad", "board"}:
            date_reasons, details = _core_date_reasons(
                key, docs, grouped, document_metadata.get(key, {})
            )
            reasons.extend(date_reasons)
            details_by_index[first_index] = details
        else:
            reasons.extend(_date_reasons(docs))
        if first.get("stale"):
            reasons.append(("warn", "stale"))
        role = first["role"]
        if role == "roster":
            officer_count = 0
            for index, record in indexed:
                if record["record_type"] != "roster_row" or not _meaningful_roster_row(record):
                    continue
                if _roster_name(record):
                    officer_count += 1
                else:
                    reasons_by_index[index].append(("quarantine", "roster_name_missing"))
                    reasons.append(("quarantine", "roster_name_missing"))
            if officer_count < 20:
                reasons.append(("warn", "roster_too_few_rows"))
        elif role == "board" and not any(record.get("known_section") for record in docs):
            reasons.append(("quarantine", "board_section_missing"))
        elif role == "afraad" and not any(record["record_type"] == "afraad_header" for record in docs):
            reasons.append(("quarantine", "afraad_header_missing"))
        if role == "counts" and Path(first["path"]).suffix.lower() == ".xlsx":
            xlsx = _xlsx_total_reasons(docs)
            for local_index, local_reasons in xlsx.items():
                global_index = indexed[local_index][0]
                reasons_by_index[global_index].extend(local_reasons)
                reasons.extend(local_reasons)
        reasons_by_index[first_index].extend(reasons)

    validations = [_validation(record, index, reasons_by_index[index], details_by_index.get(index))
                   for index, record in enumerate(records)]
    quarantined: list[dict[str, Any]] = []
    quarantined_docs = {
        key for key, reasons in doc_reasons.items() if _worst(reasons) == "quarantine"
    }
    for index, (record, validation) in enumerate(zip(records, validations)):
        if validation["verdict"] == "quarantine" or _doc_key(record) in quarantined_docs:
            quarantined.append({**record, "validation": validation})
    return validations, quarantined


def _metrics(records: list[dict[str, Any]], validations: list[dict[str, Any]],
             quarantined: list[dict[str, Any]]) -> dict[str, Any]:
    document_indices = [index for index, record in enumerate(records)
                        if record["record_type"] in {"document", "extract_error"}]
    verdicts = Counter(validations[index]["verdict"] for index in document_indices)
    reason_codes = Counter(code for index in document_indices
                           for code in validations[index]["reason_codes"] if code != "ok")
    quarantine_docs = {(_doc_key(record)) for record in quarantined}
    quarantine_by_role = Counter(key[1] for key in quarantine_docs)
    rows_by_layout: dict[str, Counter[str]] = defaultdict(Counter)
    for record in records:
        if record["record_type"] == "roster_row" and _roster_name(record):
            rows_by_layout[record.get("layout_version") or "unknown"][record["date"]] += 1
    distribution = {}
    for layout, per_day in sorted(rows_by_layout.items()):
        values = sorted(per_day.values())
        distribution[layout] = {"days": len(values), "min": min(values),
                                "median": median(values), "max": max(values)}
    return {
        "documents": len(document_indices), "records": len(records),
        "document_verdicts": dict(sorted(verdicts.items())),
        "quarantined_documents": len(quarantine_docs),
        "quarantine_by_role": dict(sorted(quarantine_by_role.items())),
        "top_reason_codes": reason_codes.most_common(10),
        "roster_rows_by_layout": distribution,
        "version": VERSION,
    }


def run_validate(ledger: Ledger, state: dict[str, Any], start: dt.date | None = None,
                 end: dt.date | None = None, *, resume: bool = False) -> dict[str, Any]:
    output = ledger.staging_path("validate")
    prior = state.get("stages", {}).get("validate", {})
    if resume and prior.get("status") == "complete" and output.exists():
        return prior.get("checkpoint", {})
    source = ledger.staging_path("extract")
    if not source.exists():
        raise FileNotFoundError("يجب تشغيل extract للدفعة أولًا")
    ledger.mark_stage(state, "validate", "running")
    records = _load_jsonl(source)
    if start is not None:
        records = [record for record in records if dt.date.fromisoformat(record["date"]) >= start]
    if end is not None:
        records = [record for record in records if dt.date.fromisoformat(record["date"]) <= end]
    document_metadata: dict[tuple[str, str, str], dict[str, Any]] = {}
    discover = ledger.staging_path("discover")
    if discover.exists():
        for item in _load_jsonl(discover):
            for day in item.get("chosen_for", []):
                document_metadata[(day, item.get("role"), item.get("path"))] = item
    validations, quarantined = validate_records(records, document_metadata)
    atomic_write_jsonl(output, validations)
    by_role: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in quarantined:
        by_role[record["role"]].append(record)
    quarantine_dir = ledger.root / "quarantine" / ledger.batch
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    for role in AUTHORITATIVE_ROLES:
        atomic_write_jsonl(quarantine_dir / f"{role}.jsonl", by_role.get(role, []))
    checkpoint = _metrics(records, validations, quarantined)
    ledger.mark_stage(state, "validate", "complete", checkpoint)
    return checkpoint


__all__ = ["VERSION", "run_validate", "validate_records"]

"""Structural, read-only preview for Word board imports.

This stage sits between transform and verify.  It checks that the geometric
board extraction survived into logical records without silently dropping a
cell, then writes a human-readable source/proposal report for every day.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from backend.text import norm

from .ledger import Ledger, atomic_write_json, atomic_write_text
from .verify import transformed_days

VERSION = "1"

_BOARD_TYPES = {"header", "board_label", "board_row"}
_REVIEW_ERRORS = {"empty_service_name", "not_a_service_label"}
_SERVICE_WORDS_RE = re.compile(r"(?:ترحيل|ماموري|مأموري|مبار|حمله|حملة|ارتكاز|تبه|تبة|ازال|إزال|تامين|تأمين)")
_STRENGTH_WORDS = {
    "فرد", "افراد", "مج", "مجند", "مجندين", "سائق", "سائقين", "وحده", "وحدة",
    "فض", "رياضي", "رياضيين", "حفظ", "نظام", "طلبه", "طلبة", "خفيفه", "خفيفة",
}


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _strength_only(value: str) -> bool:
    words = re.findall(r"[\u0621-\u064a]+", norm(value))
    return bool(words) and all(word in _STRENGTH_WORDS for word in words)


def _accounted(record: dict[str, Any]) -> bool:
    """Every non-empty logical source cell must have an explicit destination."""
    source = Counter(_clean(value) for value in record.get("raw_cells") or [] if _clean(value))
    captured = Counter(_clean(value) for value in (
        [record.get("label"), record.get("manning")] + list(record.get("extra_cells") or [])
    ) if _clean(value))
    return source == captured


def inspect_day(date: str, records: list[dict[str, Any]], proposed: dict[str, Any],
                review: list[dict[str, Any]], provenance: dict[str, Any]) -> dict[str, Any]:
    board = [record for record in records
             if record.get("role") == "board" and record.get("record_type") in _BOARD_TYPES
             and not record.get("stale")]
    headers = [record for record in board if record.get("record_type") == "header"]
    rows = [record for record in board if record.get("record_type") in {"board_label", "board_row"}]
    issues: list[dict[str, Any]] = []

    def issue(code: str, message: str, record: dict[str, Any] | None = None,
              level: str = "error") -> None:
        record = record or {}
        issues.append({
            "level": level, "code": code, "message": message,
            "path": record.get("path", ""), "table": record.get("table_index"),
            "row": record.get("row_index"), "half": record.get("half"),
        })

    if rows and not headers:
        issue("missing_board_header", "لم يُكتشف رأس يقسم جدول اللوحة إلى مسارين")
    for header in headers:
        starts = header.get("half_starts") or []
        labels = [_clean(value) for value in header.get("half_labels") or []]
        if not header.get("known_section") or len(starts) != 2 or len(labels) != 2 or not all(labels):
            issue("uncertain_lane_boundaries", "حدود مساري اللوحة غير محسومة من عناوين الأقسام", header)
        elif starts != sorted(set(starts)):
            issue("invalid_lane_boundaries", "بدايات المسارات متداخلة أو غير مرتبة", header)

    for record in rows:
        if not _accounted(record):
            issue("unaccounted_cells", "خلية أو أكثر لم تُحفظ في label/manning/extra_cells", record)
        label, manning = _clean(record.get("label")), _clean(record.get("manning"))
        if _strength_only(label):
            issue("strength_used_as_service", f"القوة ظهرت كاسم خدمة: {label}", record)
            if _SERVICE_WORDS_RE.search(norm(manning)):
                issue("shifted_service_columns", f"يبدو أن اسم الخدمة انتقل إلى خانة القائم: {manning}", record)

    headings = {norm(record.get("label") or "") for record in rows
                if record.get("record_type") == "board_label"}
    for assignment in proposed.get("assignments") or []:
        if norm(assignment.get("name") or "") in headings:
            issue("heading_became_assignment", f"عنوان قسم تحول إلى تكليف: {assignment.get('name', '')}")

    if rows:
        for source in (provenance.get("assignments") or {}).values():
            if source.get("rule") == "afraad_emergency_row":
                issue("afraad_created_board_service", "يومية الأفراد أنشأت خدمة رغم وجود لوحة مرجعية")

    for item in review:
        if item.get("type") in _REVIEW_ERRORS:
            issue("unresolved_transform_record", f"سجل لم يُحسم: {item.get('raw', '')}")

    return {
        "date": date,
        "source_rows": len(rows),
        "assignments": len(proposed.get("assignments") or []),
        "errors": sum(item["level"] == "error" for item in issues),
        "warnings": sum(item["level"] == "warning" for item in issues),
        "issues": issues,
        "board": board,
        "proposed": proposed,
        "review": review,
    }


def _cell(value: Any, limit: int = 100) -> str:
    return _clean(value).replace("|", "/")[:limit] or "—"


def _day_report(result: dict[str, Any]) -> str:
    status = "مجتاز" if not result["errors"] else "معزول"
    lines = [f"# Preview — {result['date']}", "",
             f"- الحالة: **{status}**",
             f"- صفوف اللوحة: {result['source_rows']}، التكليفات المقترحة: {result['assignments']}، "
             f"أخطاء: {result['errors']}، تحذيرات: {result['warnings']}.", "",
             "## المصدر المنطقي من Word", "",
             "| الصف | المسار | النوع | العنوان/الخدمة | القائم/القوة | التفاصيل | الأعمدة |",
             "|---:|---:|---|---|---|---|---|"]
    for record in result["board"]:
        kind = record.get("record_type", "")
        if kind == "header":
            label = " / ".join(_clean(value) for value in record.get("half_labels") or [])
            manning = "بدايات: " + ", ".join(map(str, record.get("half_starts") or []))
        else:
            label, manning = record.get("label", ""), record.get("manning", "")
        lines.append(f"| {record.get('row_index', '')} | {record.get('half', '—')} | {kind} | {_cell(label)} | "
                     f"{_cell(manning)} | {_cell(' / '.join(record.get('extra_cells') or []))} | "
                     f"{_cell(record.get('column_indexes'))} |")
    lines += ["", "## JSON المقترح", "", "| القسم | الخدمة | الفترة | الضباط | الأفراد | القوة | الساعة |",
              "|---|---|---|---|---|---:|---|"]
    for row in result["proposed"].get("assignments") or []:
        lines.append(f"| {_cell(row.get('section'))} | {_cell(row.get('name'))} | {_cell(row.get('shift'))} | "
                     f"{_cell(', '.join(row.get('officer_ids') or []))} | {_cell(', '.join(row.get('personnel_ids') or []))} | "
                     f"{int(row.get('conscript_count') or 0)} | {_cell(row.get('time'))} |")
    lines += ["", "## بوابات التحقق", ""]
    if result["issues"]:
        lines += [f"- **{item['level']} / {item['code']}**: {item['message']} "
                  f"({item['path']} — row {item['row']}، lane {item['half']})" for item in result["issues"]]
    else:
        lines.append("- لا توجد مشاكل بنيوية.")
    if result["review"]:
        lines += ["", "## طابور المراجعة", ""] + [f"- {item.get('type')}: {_cell(item.get('raw'))}" for item in result["review"]]
    return "\n".join(lines) + "\n"


def run_preview(ledger: Ledger, state: dict[str, Any]) -> dict[str, Any]:
    source_path = ledger.staging_path("extract")
    if not source_path.exists():
        raise FileNotFoundError("ناتج extract غير موجود — شغّل extract أولًا")
    days = transformed_days(ledger)
    if not days:
        raise FileNotFoundError("ناتج transform غير موجود — شغّل transform أولًا")
    records_by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in _read_jsonl(source_path):
        records_by_day[record.get("date", "")].append(record)
    review_by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in _read_jsonl(ledger.staging_path("transform-review")):
        review_by_day[item.get("date", "")].append(item)

    out_dir = ledger.root / "reports" / f"{ledger.batch}-preview"
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for date, proposed in sorted(days.items()):
        provenance_path = ledger.root / "provenance" / date[:4] / date[5:7] / f"{date}.json"
        provenance = json.loads(provenance_path.read_text(encoding="utf-8")) if provenance_path.exists() else {}
        result = inspect_day(date, records_by_day.get(date, []), proposed, review_by_day.get(date, []), provenance)
        results.append(result)
        atomic_write_text(out_dir / f"{date}.md", _day_report(result))

    quarantined = {item["date"]: [issue["code"] for issue in item["issues"] if issue["level"] == "error"]
                   for item in results if item["errors"]}
    summary = {
        "version": VERSION, "days": len(results), "passed": len(results) - len(quarantined),
        "quarantined": len(quarantined), "errors": sum(item["errors"] for item in results),
        "warnings": sum(item["warnings"] for item in results),
        "results": [{key: item[key] for key in ("date", "source_rows", "assignments", "errors", "warnings")}
                    for item in results],
    }
    atomic_write_json(ledger.root / "quarantine" / f"{ledger.batch}-preview.json", {"days": quarantined})
    atomic_write_json(ledger.report_path("preview.json"), summary)
    lines = [f"# PREVIEW — {ledger.batch}", "",
             f"- الأيام: {summary['days']}", f"- مجتاز: {summary['passed']}",
             f"- معزول: {summary['quarantined']}", f"- أخطاء: {summary['errors']}، تحذيرات: {summary['warnings']}", "",
             "| اليوم | صفوف Word | التكليفات | الأخطاء | التحذيرات | التقرير |",
             "|---|---:|---:|---:|---:|---|"]
    lines += [f"| {item['date']} | {item['source_rows']} | {item['assignments']} | {item['errors']} | "
              f"{item['warnings']} | [{item['date']}](./{ledger.batch}-preview/{item['date']}.md) |"
              for item in summary["results"]]
    atomic_write_text(ledger.report_path("preview.md"), "\n".join(lines) + "\n")
    ledger.mark_stage(state, "preview", "complete", {key: summary[key] for key in
                      ("days", "passed", "quarantined", "errors", "warnings", "version")})
    return summary


__all__ = ["VERSION", "inspect_day", "run_preview"]

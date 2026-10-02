"""Read-only comparison of source manifest, transformed days, and target data."""

from __future__ import annotations

import csv
import datetime as dt
from collections import Counter
from typing import Any

from .golden import compare_day
from .ledger import Ledger, atomic_write_text
from .verify import load_target_days, transformed_days

VERSION = "1"
SOURCE_ROLES = ("roster", "afraad")


def _manifest(ledger: Ledger) -> dict[str, dict[str, str]]:
    path = ledger.report_path("manifest.csv")
    if not path.exists():
        raise FileNotFoundError(f"manifest غير موجود: {path} — شغّل discover أولًا")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return {row["date"]: row for row in csv.DictReader(stream) if row.get("date")}


def _dates(start: dt.date, end: dt.date) -> list[str]:
    return [(start + dt.timedelta(days=offset)).isoformat()
            for offset in range((end - start).days + 1)]


def _source_status(row: dict[str, str] | None) -> str:
    if row is None:
        return "source_gap"
    if any(not (row.get(role) or "").strip() for role in SOURCE_ROLES):
        return "partial_source"
    return "complete"


def _target_status(day: dict[str, Any] | None) -> str:
    if day is None:
        return "missing"
    return "present" if day.get("import") else "unverified"


def run_audit(ledger: Ledger, start: dt.date, end: dt.date,
              state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Generate audit reports without writing target data or changing core.json."""
    if start > end:
        raise ValueError("بداية النطاق بعد نهايته")
    manifest = _manifest(ledger)
    reference = transformed_days(ledger)
    if not reference:
        raise FileNotFoundError("ناتج transform غير موجود — شغّل transform أولًا")
    target = load_target_days(ledger.data_dir)
    rows: list[dict[str, Any]] = []
    for date in _dates(start, end):
        source = manifest.get(date)
        proposed = reference.get(date)
        current = target.get(date)
        source_status = _source_status(source)
        target_status = _target_status(current)
        missing = extra = field_diffs = state_diffs = 0
        if current is not None and proposed is not None:
            result = compare_day(proposed, current)
            missing = len(result["missing"])
            extra = len(result["extra"])
            field_diffs = len(result["field_diffs"])
            state_diffs = len(result["state_diffs"])
        if source_status == "source_gap":
            action = "skip"
        elif target_status == "missing":
            action = "add" if source_status == "complete" else "review"
        else:
            action = "skip"
        rows.append({
            "date": date,
            "source_status": source_status,
            "target_status": target_status,
            "reference_rows": len((proposed or {}).get("assignments") or []),
            "target_rows": len((current or {}).get("assignments") or []),
            "missing_rows": missing,
            "extra_rows": extra,
            "field_diffs": field_diffs,
            "state_diffs": state_diffs,
            "action": action,
            "roster": (source or {}).get("roster", ""),
            "afraad": (source or {}).get("afraad", ""),
            "notes": (source or {}).get("notes", ""),
        })
    report_dir = ledger.root / "reports"
    csv_path = report_dir / f"{ledger.batch}-audit.csv"
    fields = list(rows[0]) if rows else ["date", "source_status", "target_status", "action"]
    output = ["\ufeff" + ",".join(fields)]
    for row in rows:
        output.append(",".join('"' + str(row.get(field, "")).replace('"', '""') + '"' for field in fields))
    atomic_write_text(csv_path, "\n".join(output) + "\n")
    counts = Counter((row["source_status"], row["target_status"], row["action"]) for row in rows)
    lines = [f"# AUDIT — {ledger.batch}", "", f"النطاق: {start.isoformat()} إلى {end.isoformat()}", "",
             "| المصدر | الهدف | القرار | العدد |", "|---|---|---|---:|"]
    for key, count in sorted(counts.items()):
        lines.append(f"| {key[0]} | {key[1]} | {key[2]} | {count} |")
    lines += ["", "## الأيام التي تحتاج مراجعة", ""]
    review = [row for row in rows if row["action"] == "review"]
    lines.extend(f"- {row['date']}: {row['source_status']}، roster={row['roster'] or '—'}، أفراد={row['afraad'] or '—'}"
                 for row in review)
    if not review:
        lines.append("لا يوجد.")
    lines += ["", f"التفاصيل الآلية: `{csv_path.name}`", ""]
    atomic_write_text(report_dir / f"{ledger.batch}-audit.md", "\n".join(lines))
    if state is not None:
        ledger.mark_stage(state, "audit", "complete", {"days": len(rows), "csv": str(csv_path)})
    return {"days": len(rows), "rows": rows, "counts": counts, "csv": str(csv_path)}


__all__ = ["VERSION", "run_audit"]

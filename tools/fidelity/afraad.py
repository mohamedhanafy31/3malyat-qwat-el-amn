#!/usr/bin/env python3
"""Compare archive and system exports for the afraad (personnel daily) kind.

The command is deliberately read-only.  It extracts the first table from each
DOCX, normalizes Arabic text for comparison, aligns the fixed basic block by
row order, and aligns emergency rows by row order.  The JSON result is useful
for machine aggregation; the text result is intended for a quick review.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
PLACEHOLDER_RE = re.compile(r"^[\sـ\-–—_.]*$")


def normalize(value: object) -> str:
    """Normalize only for comparison; original strings remain in the report."""
    text = str(value or "").translate(ARABIC_DIGITS).replace("\u0640", "")
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي").replace("ئ", "ي")
    return " ".join(text.replace("\n", " ").replace("\r", " ").split()).lower()


def unique_cells(row):
    seen, cells = set(), []
    for cell in row.cells:
        key = id(cell._tc)
        if key not in seen:
            seen.add(key)
            cells.append(cell.text)
    return cells


def structure_signature(document: Document) -> dict:
    table = document.tables[0]
    grid = []
    for column in table._tbl.tblGrid.gridCol_lst:
        grid.append(int(column.get(qn("w:w"), 0)))
    rows = []
    for row in table.rows:
        shapes = []
        for cell_text in unique_cells(row):
            # Find the corresponding XML cell by text order.  The unique-cell
            # count is the stable observable; spans/vMerge are the fidelity
            # details that distinguish the archive's manual variants.
            del cell_text
        seen, cells = set(), []
        for cell in row.cells:
            if id(cell._tc) in seen:
                continue
            seen.add(id(cell._tc))
            tcpr = cell._tc.tcPr
            span = tcpr.find(qn("w:gridSpan")) if tcpr is not None else None
            merge = tcpr.find(qn("w:vMerge")) if tcpr is not None else None
            cells.append((int(span.get(qn("w:val"), 1)) if span is not None else 1,
                          merge.get(qn("w:val"), "") if merge is not None else ""))
        rows.append(tuple(cells))
    section = document.sections[0]
    return {"grid_columns": tuple(grid), "rows": tuple(rows),
            "page_width": section.page_width, "page_height": section.page_height,
            "margins": (section.top_margin, section.right_margin,
                        section.bottom_margin, section.left_margin)}


def title_day(document: Document) -> str:
    for paragraph in document.paragraphs:
        match = re.search(r"(\d{1,2})\s*[/\-]\s*(\d{1,2})\s*[/\-]\s*(20\d\d)",
                          paragraph.text.translate(ARABIC_DIGITS))
        if match:
            return f"{int(match[3]):04d}-{int(match[2]):02d}-{int(match[1]):02d}"
    return ""


def archive_file(root: Path, day: str) -> Path | None:
    value = date.fromisoformat(day)
    folder = root / str(value.month) / str(value.day)
    exact = folder / f"{value.day}-{value.month}-2026 افراد.docx"
    if exact.exists():
        return exact
    if day == "2026-09-08":
        stale = root / "9" / "9" / "8-9-2026 افراد.docx"
        if stale.exists():
            return stale
    return None
    """
    if False:
        pass
        try:
            document = Document(path)
        except Exception:
        printed_day = title_day(document)
        filename_day = f"{value.day}-{value.month}-2026 افراد.docx"
        if printed_day == day or path.name == filename_day:
            # The printed title is authoritative; agreement is only a tie-breaker.
            candidates.append((printed_day == day, path.stat().st_mtime, path))
    return sorted(candidates, reverse=True)[0][2] if candidates else None
    """


def parse_document(path: Path) -> dict:
    document = Document(path)
    rows = [unique_cells(row) for row in document.tables[0].rows]
    heading = next((i for i, row in enumerate(rows)
                    if "طارئ" in normalize(" ".join(row))), None)
    if heading is None:
        heading = len(rows)

    basic = []
    for row in rows[1:heading]:
        if len(row) >= 8 and normalize(row[1]).strip() == "كمين 109":
            basic.append({"service": f"{row[1]} - {row[2]}", "morning": row[3],
                          "night": row[4], "count": row[5], "weapon": row[6],
                          "schedule": row[7], "cells": len(row)})
        elif len(row) >= 7:
            basic.append({"service": row[1], "morning": row[2], "night": row[3],
                          "count": row[4], "weapon": row[5], "schedule": row[6],
                          "cells": len(row)})

    emergency = []
    for row in rows[heading + 1:]:
        emergency.append({"label": row[0], "who": row[1] if len(row) > 1 else "",
                          "count": row[2] if len(row) > 2 else "",
                          "weapon": row[3] if len(row) > 3 else "",
                          "time": row[4] if len(row) > 4 else "",
                          "cells": len(row)})
    return {"path": str(path), "rows": rows, "basic": basic,
            "emergency": emergency, "heading": heading,
            "structure": structure_signature(document)}


def difference(archive_value: object, system_value: object) -> str | None:
    left, right = normalize(archive_value), normalize(system_value)
    if left == right:
        return None
    compact_left = left.replace("/", "").replace(" ", "")
    compact_right = right.replace("/", "").replace(" ", "")
    if compact_left == compact_right:
        return "abbreviation/formatting only"
    return "real value mismatch"


def compare_day(day: str, archive: Path | None, system: Path | None) -> dict:
    if archive is None:
        return {"day": day, "status": "ARCHIVE_MISSING",
                "events": [{"category": "STRUCTURE", "cause": "archive missing"}]}
    if system is None or not system.exists():
        return {"day": day, "status": "SYSTEM_MISSING",
                "events": [{"category": "STRUCTURE", "cause": "system export missing"}]}
    left, right = parse_document(archive), parse_document(system)
    events = []
    if left["structure"] != right["structure"]:
        events.append({"category": "STRUCTURE", "cause": "grid/merge/page settings differ",
                       "archive": {"grid_columns": len(left["structure"]["grid_columns"]),
                                   "rows": len(left["structure"]["rows"])},
                       "system": {"grid_columns": len(right["structure"]["grid_columns"]),
                                  "rows": len(right["structure"]["rows"])}})
    if len(left["rows"]) != len(right["rows"]):
        events.append({"category": "STRUCTURE", "cause": "row/grid count differs",
                       "archive_rows": len(left["rows"]), "system_rows": len(right["rows"])})
    if len(left["basic"]) != len(right["basic"]):
        events.append({"category": "STRUCTURE", "cause": "basic row count differs",
                       "archive": len(left["basic"]), "system": len(right["basic"])})

    fields = ("service", "morning", "night", "count", "weapon", "schedule")
    for index in range(max(len(left["basic"]), len(right["basic"]))):
        if index >= len(left["basic"]):
            events.append({"category": "DATA-EXTRA", "region": "basic", "row": index + 1,
                           "cause": "system basic row has no archive row"})
            continue
        if index >= len(right["basic"]):
            events.append({"category": "DATA-MISSING", "region": "basic", "row": index + 1,
                           "cause": "archive basic row absent from system",
                           "archive": left["basic"][index]["service"]})
            continue
        for field in fields:
            sub = difference(left["basic"][index][field], right["basic"][index][field])
            if sub:
                events.append({"category": "DATA-DIFFERENT", "sub_category": sub,
                               "region": "basic", "row": index + 1, "field": field,
                               "archive": left["basic"][index][field],
                               "system": right["basic"][index][field],
                               "cause": "system data differs" if field != "service"
                               else "archive/manual service label or dated-list mismatch"})

    fields = ("label", "who", "count", "weapon", "time")
    for index in range(max(len(left["emergency"]), len(right["emergency"]))):
        if index >= len(left["emergency"]):
            events.append({"category": "DATA-EXTRA", "region": "emergency", "row": index + 1,
                           "cause": "system emergency row has no archive row"})
            continue
        if index >= len(right["emergency"]):
            events.append({"category": "DATA-MISSING", "region": "emergency", "row": index + 1,
                           "cause": "archive emergency row absent from system",
                           "archive": left["emergency"][index]["label"]})
            continue
        if left["emergency"][index]["cells"] != 5 or right["emergency"][index]["cells"] != 5:
            events.append({"category": "STRUCTURE", "region": "emergency", "row": index + 1,
                           "cause": "non-standard multi-cell emergency row",
                           "archive_cells": left["emergency"][index]["cells"],
                           "system_cells": right["emergency"][index]["cells"]})
        for field in fields:
            sub = difference(left["emergency"][index][field], right["emergency"][index][field])
            if sub:
                events.append({"category": "DATA-DIFFERENT", "sub_category": sub,
                               "region": "emergency", "row": index + 1, "field": field,
                               "archive": left["emergency"][index][field],
                               "system": right["emergency"][index][field],
                               "cause": "system data differs" if field != "label"
                               else "archive/manual emergency label"})
    return {"day": day, "status": "OK", "archive": str(archive),
            "system": str(system), "events": events}


def run(args) -> dict:
    days = [date.fromisoformat(x) for x in args.days] if args.days else []
    if not days:
        current = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
        while current <= end:
            days.append(current)
            current += timedelta(days=1)
    results = []
    for value in days:
        day = value.isoformat()
        results.append(compare_day(day, archive_file(args.archive_root, day),
                                   args.system_root / day / "afraad.docx"))
    counts, subcategories, causes, day_counts = Counter(), Counter(), Counter(), Counter()
    patterns = Counter()
    for result in results:
        day_counts[result["day"]] = len(result["events"])
        for event in result["events"]:
            counts[event["category"]] += 1
            subcategories[event.get("sub_category", "")] += 1
            causes[event.get("cause", "")] += 1
            if event["category"] == "DATA-DIFFERENT":
                key = "|".join((event["region"], event["field"], event["sub_category"]))
                patterns[key] += 1
    return {"scope": {"days": [d.isoformat() for d in days],
                       "archive_root": str(args.archive_root),
                       "system_root": str(args.system_root)},
            "summary": {"counts": dict(counts), "subcategories": dict(subcategories),
                        "causes": dict(causes), "top_patterns": patterns.most_common(20),
                        "worst_days": day_counts.most_common(10)},
            "days": results}


def readable(report: dict) -> str:
    summary = report["summary"]
    lines = ["afraad fidelity comparison", f"days={len(report['days'])}",
             "counts=" + json.dumps(summary["counts"], ensure_ascii=False),
             "subcategories=" + json.dumps(summary["subcategories"], ensure_ascii=False),
             "causes=" + json.dumps(summary["causes"], ensure_ascii=False),
             "worst_days=" + json.dumps(summary["worst_days"], ensure_ascii=False)]
    for result in report["days"]:
        if result["events"]:
            lines.append(f"{result['day']} status={result['status']} events={len(result['events'])}")
            for event in result["events"][:8]:
                lines.append("  " + json.dumps(event, ensure_ascii=False))
            if len(result["events"]) > 8:
                lines.append(f"  ... {len(result['events']) - 8} more")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("days", nargs="*", help="ISO days; omit to use --start/--end")
    parser.add_argument("--start", default="2026-08-01")
    parser.add_argument("--end", default="2026-09-29")
    parser.add_argument("--archive-root", type=Path,
                        default=Path(__file__).resolve().parents[4] / "2026")
    parser.add_argument("--system-root", type=Path, required=True,
                        help="directory containing YYYY-MM-DD/afraad.docx")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--text-out", type=Path)
    args = parser.parse_args()
    report = run(args)
    text = readable(report)
    print(text, end="")
    if args.json_out:
        args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.text_out:
        args.text_out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

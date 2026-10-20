#!/usr/bin/env python3
"""Compare archived ``اعداد الخدمات`` workbooks with ``/api/counts/<day>``.

The project has no Excel exporter for this kind.  This module therefore treats
the archive as the observed workbook and the API payload as the system side.
It is intentionally read-only and never loads the live data directory unless
the caller explicitly points ``PERSONNEL_DATA_DIR`` at a copy.
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARCHIVE = ROOT.parent.parent / "2026"
LATEST_MERGES = {
    "B2:H2", "B25:H25", "H4:H12", "H14:H23", "H26:H34",
    "H35:H36", "C41:E48", "F41:F48",
}
LATEST_WIDTHS = (2.425781, 54.0, 14.0, 50.710938, 14.0, 50.710938,
                 15.285156, 27.425781)


def norm(value: Any) -> str:
    """Comparison normalization, not a display transformation."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFC", str(value))
    text = text.replace("ـ", "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.translate(str.maketrans("إأآٱى", "ااااي"))
    text = text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789"))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_day(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


def target_days(start: str = "2026-08-01", end: str = "2026-09-29") -> list[str]:
    a, b = parse_day(start), parse_day(end)
    out = []
    while a <= b:
        out.append(a.isoformat())
        a += dt.timedelta(days=1)
    return out


def archive_files(archive_root: Path, day: str) -> list[Path]:
    d = parse_day(day)
    # ``archive_root`` is the ``.../2026`` directory, matching the task's
    # ``../../2026/<month>/<day>`` convention.
    folder = archive_root / str(d.month) / str(d.day)
    return sorted(p for p in folder.glob("*.xlsx")
                  if "اعداد الخدمات" in p.name and not p.name.startswith("~$")
                  and not p.name.endswith(".tmp"))


def title_date(ws) -> str | None:
    text = str(ws["B2"].value or "")
    m = re.search(r"يوم.*?(\d+)\s*/\s*(\d+)\s*/\s*(\d+)", text)
    if not m:
        return None
    return f"{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"


def workbook_signature(ws) -> dict[str, Any]:
    return {
        "dimension": ws.calculate_dimension(),
        "rows": ws.max_row,
        "columns": ws.max_column,
        "orientation": ws.page_setup.orientation,
        "paper_size": ws.page_setup.paperSize,
        "margins": {k: getattr(ws.page_margins, k) for k in
                    ("left", "right", "top", "bottom", "header", "footer")},
        "widths": [round(ws.column_dimensions[c].width or 13, 6)
                   for c in "ABCDEFGH"],
        "merges": sorted(str(x) for x in ws.merged_cells.ranges),
        "rtl": bool(ws.sheet_view.rightToLeft),
    }


def _pairs(ws, rows: range) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        for name_col, count_col in (("B", "C"), ("D", "E"), ("F", "G")):
            name = ws[f"{name_col}{r}"].value
            count = ws[f"{count_col}{r}"].value
            if name not in (None, "") or count not in (None, ""):
                out.append({"name": "" if name is None else str(name),
                            "count": count, "cell": f"{name_col}{r}",
                            "count_cell": f"{count_col}{r}"})
    return out


def read_archive(path: Path) -> dict[str, Any]:
    wb = load_workbook(path, data_only=False)
    cached = load_workbook(path, data_only=True)
    ws, wc = wb["اعداد الخدمات"], cached["اعداد الخدمات"]
    formulas = {}
    for row in ws.iter_rows():
        for cell in row:
            if isinstance(cell.value, str) and cell.value.startswith("="):
                formulas[cell.coordinate] = {"formula": cell.value,
                                             "cached": wc[cell.coordinate].value}
    return {
        "path": str(path), "title_date": title_date(ws),
        "signature": workbook_signature(ws),
        "basic_am": _pairs(ws, range(4, 13)),
        "basic_pm": _pairs(ws, range(14, 24)),
        "emergency": _pairs(ws, range(27, 36)),
        "formulas": formulas,
        "sheetnames": wb.sheetnames,
    }


def _display_name(entry: dict[str, Any]) -> str:
    name = str(entry.get("name") or "").strip()
    party = str(entry.get("party") or "").strip()
    return f"{name} ({party})" if party else name


def _payload_entries(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    # The archive lays each logical list down column-major: B, then D, then F.
    # Its emergency block contains the recurring rows followed by board/custom
    # rows; the API keeps those sources separate, so flatten them here.
    emergency = list(payload.get("recurring") or []) + list(payload.get("emergency") or [])
    for section in payload.get("custom_sections") or []:
        emergency.extend(section.get("rows") or [])
    return {"basic_am": list(payload.get("basic_am") or []),
            "basic_pm": list(payload.get("basic_pm") or []),
            "emergency": emergency}


def get_payload(day: str) -> dict[str, Any]:
    if not os.environ.get("PERSONNEL_DATA_DIR"):
        raise RuntimeError("refusing to call Flask without PERSONNEL_DATA_DIR pointing to a data copy")
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from app import app
    from backend.auth.users import by_username
    from backend.auth.security import secret_key
    user = by_username("testadmin")
    if not user:
        raise RuntimeError("testadmin is required, as in tools/export_days_probe.py")
    app.config.update(TESTING=True)
    app.secret_key = secret_key()
    client = app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = user["id"]
        session["session_version"] = int(user.get("session_version", 0))
        session.permanent = True
    response = client.get(f"/api/counts/{day}")
    if response.status_code != 200:
        raise RuntimeError(f"/api/counts/{day} returned HTTP {response.status_code}")
    return response.get_json()


def _structure_issues(archive: dict[str, Any]) -> list[dict[str, Any]]:
    sig = archive["signature"]
    issues = []
    if sig["rows"] != 52 or sig["columns"] != 8:
        issues.append({"kind": "dimension", "actual": sig["dimension"], "expected": "B2:H52"})
    if sig["orientation"] != "landscape":
        issues.append({"kind": "orientation", "actual": sig["orientation"], "expected": "landscape"})
    if tuple(sig["widths"]) != LATEST_WIDTHS:
        issues.append({"kind": "column_widths", "actual": sig["widths"], "expected": list(LATEST_WIDTHS)})
    if set(sig["merges"]) != LATEST_MERGES:
        issues.append({"kind": "merges", "actual": sig["merges"], "expected": sorted(LATEST_MERGES)})
    if archive["sheetnames"] != ["اعداد الخدمات"]:
        issues.append({"kind": "sheet_names", "actual": archive["sheetnames"], "expected": ["اعداد الخدمات"]})
    return issues


def _compare_list(section: str, archived: list[dict[str, Any]], system: list[dict[str, Any]]) -> list[dict[str, Any]]:
    diffs = []
    n = max(len(archived), len(system))
    for i in range(n):
        a = archived[i] if i < len(archived) else None
        s = system[i] if i < len(system) else None
        cell = a["cell"] if a else None
        if a is None:
            diffs.append({"category": "DATA-EXTRA", "section": section, "position": i + 1,
                          "system": _display_name(s), "count": s.get("count"),
                          "cause": "system_data_differs_archive"})
            continue
        if s is None:
            diffs.append({"category": "DATA-MISSING", "section": section, "position": i + 1,
                          "cell": cell, "archive": a["name"], "count": a.get("count"),
                          "cause": "system_data_differs_archive"})
            continue
        an, sn = norm(a["name"]), norm(_display_name(s))
        if an != sn:
            # A set-level match means this is mostly ordering/column packing.
            remaining = [norm(_display_name(x)) for x in system]
            cat = "ORDER" if an in remaining else "DATA-DIFFERENT"
            sub = "formatting_only" if cat == "DATA-DIFFERENT" and (norm(a["name"].replace("(", " ").replace(")", "")) == norm(s.get("name"))) else "value_or_label"
            cause = "archive_manual_order_or_layout" if cat == "ORDER" else (
                "archive_manual_formatting" if sub == "formatting_only" else "archive_manual_label_quirk")
            diffs.append({"category": cat, "subtype": sub, "section": section,
                          "position": i + 1, "cell": cell, "archive": a["name"],
                          "system": _display_name(s), "cause": cause})
        if a.get("count") != s.get("count"):
            diffs.append({"category": "DATA-DIFFERENT", "subtype": "count_value",
                          "section": section, "position": i + 1, "cell": a["count_cell"],
                          "archive": a.get("count"), "system": s.get("count"),
                          "cause": "system_data_differs_archive"})
    return diffs


def compare_day(day: str, archive_root: Path) -> dict[str, Any]:
    candidates = archive_files(archive_root, day)
    if not candidates:
        return {"day": day, "archive_files": [], "status": "MISSING_ARCHIVE"}
    payload = get_payload(day)
    result = {"day": day, "archive_files": [], "status": "ok", "differences": []}
    for path in candidates:
        archive = read_archive(path)
        result["archive_files"].append({"path": str(path), "title_date": archive["title_date"],
                                         "structure": archive["signature"], "formulas": archive["formulas"]})
        result["differences"].extend({"file": str(path), "category": "STRUCTURE",
                                      "cause": "archive_format_evolution", **x}
                                      for x in _structure_issues(archive))
        expected = _payload_entries(payload)
        for section in ("basic_am", "basic_pm", "emergency"):
            result["differences"].extend({"file": str(path), **x}
                                          for x in _compare_list(section, archive[section], expected[section]))
        # Cached formula values are evidence too.  Check both the formula
        # result and the formula text against the API totals where the mapping
        # is unambiguous; check per-column emergency sums from the workbook.
        expected_totals = {
            "H4": sum(int(x.get("count") or 0) for x in expected["basic_am"]),
            "H14": sum(int(x.get("count") or 0) for x in expected["basic_pm"]),
            "H35": sum(int(x.get("count") or 0) for x in expected["emergency"]),
            "F41": sum(int(x.get("count") or 0) for group in expected.values() for x in group),
            "F38": sum(int(x.get("count") or 0) for group in expected.values() for x in group),
        }
        for coord, f in archive["formulas"].items():
            actual = f["cached"]
            if coord in expected_totals and isinstance(actual, (int, float)) and actual != expected_totals[coord]:
                result["differences"].append({"file": str(path), "category": "DATA-DIFFERENT",
                                               "subtype": "formula_cached_value", "cell": coord,
                                               "archive": actual, "system": expected_totals[coord],
                                               "formula": f["formula"], "cause": "system_data_differs_archive"})
    return result


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    cats = Counter(); subs = Counter(); patterns = Counter(); days = Counter(); causes = Counter()
    for result in results:
        for diff in result.get("differences", []):
            cat = diff["category"]; cats[cat] += 1; days[result["day"]] += 1
            if diff.get("subtype"): subs[f"{cat}:{diff['subtype']}"] += 1
            key = (cat, diff.get("subtype", ""), diff.get("section", ""),
                   norm(diff.get("archive", "")), norm(diff.get("system", "")))
            patterns["|".join(key)] += 1
            causes[diff.get("cause", "unknown")] += 1
    return {"days_checked": len(results), "archive_files_checked": sum(len(r.get("archive_files", [])) for r in results),
            "categories": dict(cats), "subcategories": dict(subs), "causes": dict(causes),
            "worst_days": sorted(({"day": d, "differences": n} for d, n in days.items()),
                                  key=lambda x: (-x["differences"], x["day"]))[:10],
            "top_patterns": [{"pattern": k, "count": n} for k, n in patterns.most_common(20)]}


def readable(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [f"Counts fidelity: {s['days_checked']} days, {s['archive_files_checked']} archive workbooks",
             "Categories: " + ", ".join(f"{k}={v}" for k, v in s["categories"].items()),
             "Causes: " + ", ".join(f"{k}={v}" for k, v in s["causes"].items()), "Worst days:"]
    lines += [f"  {x['day']}: {x['differences']} differences" for x in s["worst_days"]]
    if s["top_patterns"]:
        lines.append("Top patterns:")
        lines += [f"  {x['count']} x {x['pattern']}" for x in s["top_patterns"]]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("days", nargs="*", help="YYYY-MM-DD; omit for 2026-08-01..2026-09-29")
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--start", default="2026-08-01")
    parser.add_argument("--end", default="2026-09-29")
    parser.add_argument("--json", type=Path, help="write machine-readable report")
    args = parser.parse_args(argv)
    days = args.days or target_days(args.start, args.end)
    results = [compare_day(day, args.archive_root) for day in days]
    report = {"summary": summarize(results), "days": results}
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(readable(report))
    if args.json:
        print(f"JSON: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

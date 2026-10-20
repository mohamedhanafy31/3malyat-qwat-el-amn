"""Measure fidelity of the officers' duty-roster DOCX export.

This module deliberately does not import the Flask app or write project data.
It reads the canonical archive DOCX and a DOCX produced by
``tools/export_days_probe.py`` and compares their XML-level table grids.

Examples::

    python3 tools/fidelity/duty.py --day 2026-09-29 \
      --system-root /tmp/fidelity-duty-20261020
    python3 tools/fidelity/duty.py --all --system-root /tmp/fidelity-duty-20261020 \
      --json-out /tmp/duty-fidelity.json --text-out /tmp/duty-fidelity.txt
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable
from zipfile import ZipFile

from lxml import etree


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
ARCHIVE_DEFAULT = Path(__file__).resolve().parents[2].parent.parent / "2026"
DAY_RE = re.compile(r"^2026-(08|09)-(0[1-9]|[12][0-9]|3[01])$")


def _a(name: str) -> str:
    return f"{{{W}}}{name}"


def archive_path(day: str, archive_root: Path | None = None) -> Path:
    root = archive_root or ARCHIVE_DEFAULT
    year, month, dom = (int(x) for x in day.split("-"))
    return root / str(month) / str(dom) / f"{dom}-{month}-{year}.docx"


def _cell_text(tc: etree._Element) -> str:
    out: list[str] = []
    for node in tc.iter():
        if node.tag == _a("t"):
            out.append(node.text or "")
        elif node.tag in {_a("br"), _a("cr")}:
            out.append("\n")
        elif node.tag == _a("tab"):
            out.append("\t")
    return "".join(out)


def _int_attr(node: etree._Element | None, name: str) -> int | None:
    if node is None:
        return None
    value = node.get(_a(name))
    return int(value) if value and value.lstrip("-").isdigit() else None


def _row_grid(row: etree._Element, width: int) -> tuple[list[str], list[dict[str, Any]]]:
    values: list[str] = []
    meta: list[dict[str, Any]] = []
    for tc in row.findall("w:tc", NS):
        tcpr = tc.find("w:tcPr", NS)
        span = _int_attr(tcpr.find("w:gridSpan", NS) if tcpr is not None else None, "val") or 1
        vm_node = tcpr.find("w:vMerge", NS) if tcpr is not None else None
        vm = None
        if vm_node is not None:
            vm = vm_node.get(_a("val")) or "continue"
        shd = tcpr.find("w:shd", NS) if tcpr is not None else None
        fill = shd.get(_a("fill")) if shd is not None else None
        text = _cell_text(tc)
        for offset in range(span):
            values.append(text if offset == 0 else "")
            meta.append({"span": span if offset == 0 else 0, "vmerge": vm, "fill": fill})
    if len(values) < width:
        values.extend([""] * (width - len(values)))
        meta.extend([{"span": 0, "vmerge": None, "fill": None}] * (width - len(meta)))
    return values[:width], meta[:width]


def _paragraphs(root: etree._Element) -> list[dict[str, Any]]:
    result = []
    for p in root.findall(".//w:body/w:p", NS):
        text = _cell_text(p)
        ppr = p.find("w:pPr", NS)
        jc = ppr.find("w:jc", NS) if ppr is not None else None
        bidi = ppr.find("w:bidi", NS) if ppr is not None else None
        result.append({"text": text, "alignment": jc.get(_a("val")) if jc is not None else None,
                       "bidi": bidi is not None})
    return result


def load_docx(path: Path) -> dict[str, Any]:
    """Return normalized XML structure and logical cell grids for one DOCX."""
    with ZipFile(path) as zf:
        root = etree.fromstring(zf.read("word/document.xml"))
    sect = root.find(".//w:body/w:sectPr", NS)
    if sect is None:
        sect = root.find(".//w:sectPr", NS)
    pg = sect.find("w:pgSz", NS) if sect is not None else None
    mar = sect.find("w:pgMar", NS) if sect is not None else None
    setup = {
        "page": {k: _int_attr(pg, k) for k in ("w", "h")},
        "margins": {k: _int_attr(mar, k) for k in ("top", "right", "bottom", "left", "header", "footer", "gutter")},
    }
    tables = []
    for table in root.findall(".//w:body/w:tbl", NS):
        grid = [_int_attr(col, "w") or 0 for col in table.findall("w:tblGrid/w:gridCol", NS)]
        rows = []
        for row in table.findall("w:tr", NS):
            trpr = row.find("w:trPr", NS)
            height = _int_attr(trpr.find("w:trHeight", NS) if trpr is not None else None, "val")
            values, meta = _row_grid(row, len(grid))
            rows.append({"cells": values, "meta": meta, "height": height})
        tables.append({"grid": grid, "rows": rows, "physical_rows": len(rows)})
    return {"path": str(path), "setup": setup, "paragraphs": _paragraphs(root), "tables": tables}


def _structure(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "setup": doc["setup"],
        "paragraphs": [{"alignment": p["alignment"], "bidi": p["bidi"]} for p in doc["paragraphs"]],
        "tables": [{"grid": t["grid"], "physical_rows": t["physical_rows"],
                    "rows": [{"height": r["height"], "meta": r["meta"]} for r in t["rows"]]}
                   for t in doc["tables"]],
    }


_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_DIACRITICS = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed]")
_DASHES = "-‐‑‒–—―ـ_"


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").translate(_ARABIC_DIGITS)
    text = text.replace("ـ", "")
    text = _DIACRITICS.sub("", text)
    text = text.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي"}))
    return re.sub(r"\s+", " ", text).strip()


def _format_key(text: str) -> str:
    value = normalize(text)
    value = value.replace("م.اول", "ملازم اول").replace("م. أول", "ملازم اول")
    value = re.sub(r"[" + re.escape(_DASHES) + r"\s/.,:؛()\[\]+]", "", value)
    return value


def _format_only(a: str, b: str) -> bool:
    if _format_key(a) == _format_key(b):
        return True
    # The archive uses several dash lengths and both slash-spacing conventions.
    if normalize(a).strip(_DASHES + " ") == normalize(b).strip(_DASHES + " "):
        return True
    return False


def _row_key(row: list[str], table_index: int, row_index: int) -> str:
    if table_index == 0 and row_index == 0:
        return "__header__"
    if table_index == 0:
        cells = [normalize(x) for x in row]
        if cells and ("خوارج" in cells[0] or "حراسات" in cells[0]):
            return "__section__:" + cells[0]
        return "name:" + (cells[2] if len(cells) > 2 else "")
    return f"row:{row_index}"


def _align_rows(archive_rows: list[list[str]], system_rows: list[list[str]], table_index: int):
    akeys = [_row_key(r, table_index, i) for i, r in enumerate(archive_rows)]
    skeys = [_row_key(r, table_index, i) for i, r in enumerate(system_rows)]
    # Duty rows are keyed by officer name.  A changed order must not turn all
    # subsequent cells into artificial missing/extra rows; it is reported once
    # as ORDER and then the same officers are compared cell-by-cell.
    if table_index == 0:
        positions: dict[str, list[int]] = defaultdict(list)
        for j, key in enumerate(skeys):
            positions[key].append(j)
        pairs: list[tuple[int | None, int | None]] = []
        used: set[int] = set()
        matched_system_positions: list[int] = []
        for i, key in enumerate(akeys):
            candidate = next((j for j in positions.get(key, []) if j not in used), None)
            if candidate is None:
                pairs.append((i, None))
            else:
                used.add(candidate)
                matched_system_positions.append(candidate)
                pairs.append((i, candidate))
        pairs.extend((None, j) for j in range(len(skeys)) if j not in used)
        order = matched_system_positions != sorted(matched_system_positions)
        return pairs, order, akeys, skeys
    matcher = difflib.SequenceMatcher(a=akeys, b=skeys, autojunk=False)
    pairs: list[tuple[int | None, int | None]] = []
    order = False
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            pairs.extend((i, j) for i, j in zip(range(i1, i2), range(j1, j2)))
        else:
            order = order or (tag == "replace" and (i2 - i1) == (j2 - j1))
            pairs.extend((i, None) for i in range(i1, i2))
            pairs.extend((None, j) for j in range(j1, j2))
    return pairs, order, akeys, skeys


def _diff(a: str, b: str, day: str, table: int, row: int, col: int, path: str) -> dict[str, Any] | None:
    na, nb = normalize(a), normalize(b)
    if na == nb:
        return None
    if not na and nb:
        category, sub = "DATA-EXTRA", None
    elif na and not nb:
        category, sub = "DATA-MISSING", None
    else:
        category, sub = "DATA-DIFFERENT", "formatting-only" if _format_only(a, b) else "real-value-mismatch"
    return {"day": day, "table": table, "row": row, "column": col, "path": path,
            "category": category, "subcategory": sub, "archive": a, "system": b}


def compare_day(day: str, archive_root: Path | None, system_root: Path) -> dict[str, Any]:
    ap = archive_path(day, archive_root)
    sp = system_root / day / "duty.docx"
    archive, system = load_docx(ap), load_docx(sp)
    diffs: list[dict[str, Any]] = []
    if _structure(archive) != _structure(system):
        diffs.append({"day": day, "category": "STRUCTURE", "path": "document.xml",
                      "detail": "page setup, table grid/merge/row geometry, or paragraph direction differs"})
    for ti in range(max(len(archive["tables"]), len(system["tables"]))):
        if ti >= len(archive["tables"]):
            diffs.append({"day": day, "category": "STRUCTURE", "path": f"tables[{ti}]", "detail": "system-only table"})
            continue
        if ti >= len(system["tables"]):
            diffs.append({"day": day, "category": "STRUCTURE", "path": f"tables[{ti}]", "detail": "archive-only table"})
            continue
        ar = [r["cells"] for r in archive["tables"][ti]["rows"]]
        sr = [r["cells"] for r in system["tables"][ti]["rows"]]
        pairs, order, akeys, skeys = _align_rows(ar, sr, ti)
        if order:
            diffs.append({"day": day, "category": "ORDER", "table": ti, "path": f"tables[{ti}].rows",
                          "detail": "row keys are in a different order", "archive_keys": akeys,
                          "system_keys": skeys})
        for ai, si in pairs:
            if ai is None:
                diffs.append({"day": day, "category": "DATA-EXTRA", "table": ti, "row": si,
                              "path": f"tables[{ti}].rows[{si}]", "detail": "system-only row", "system": sr[si]})
                continue
            if si is None:
                diffs.append({"day": day, "category": "DATA-MISSING", "table": ti, "row": ai,
                              "path": f"tables[{ti}].rows[{ai}]", "detail": "archive-only row", "archive": ar[ai]})
                continue
            width = max(len(ar[ai]), len(sr[si]))
            for ci in range(width):
                av = ar[ai][ci] if ci < len(ar[ai]) else ""
                sv = sr[si][ci] if ci < len(sr[si]) else ""
                # The first roster column is a display ordinal, not an
                # officer field.  When names are matched but their order
                # differs, its changed number is evidence for ORDER only.
                if ti == 0 and ci == 0 and re.fullmatch(r"\s*\d+\s*-?\s*", normalize(av)) and re.fullmatch(r"\s*\d+\s*-?\s*", normalize(sv)):
                    continue
                d = _diff(av, sv, day, ti, ai, ci, f"tables[{ti}].rows[{ai}].cells[{ci}]")
                if d:
                    d["system_row"] = si
                    diffs.append(d)
    return {"day": day, "archive": str(ap), "system": str(sp), "diffs": diffs,
            "counts": dict(Counter(d["category"] for d in diffs))}


def _days() -> list[str]:
    return [f"2026-{m:02d}-{d:02d}" for m in (8, 9) for d in range(1, 32 if m == 8 else 30)]


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    all_diffs = [d for r in results for d in r["diffs"]]
    patterns = Counter()
    examples: dict[str, dict[str, Any]] = {}
    for d in all_diffs:
        if d["category"] == "STRUCTURE":
            key = "structure:archive-vs-export-geometry"
        elif d["category"] == "ORDER":
            key = "order:row-key-sequence"
        elif d["category"] in {"DATA-MISSING", "DATA-EXTRA"}:
            key = f"{d['category'].lower()}:{d.get('path','')}"
        else:
            key = f"{d['category'].lower()}:{d.get('subcategory')}:{normalize(d.get('archive',''))}->{normalize(d.get('system',''))}"
        patterns[key] += 1
        examples.setdefault(key, d)
    day_counts = sorted(((r["day"], sum(r["counts"].values()), r["counts"]) for r in results), key=lambda x: (-x[1], x[0]))
    causes = Counter()
    for d in all_diffs:
        if d["category"] == "STRUCTURE":
            cause = "exporter formatting/structure bug"
        elif d["day"] >= "2026-09-22" and d["category"] in {"DATA-MISSING", "DATA-EXTRA", "DATA-DIFFERENT"}:
            cause = "system data differs from archive (or exporter mapping rule)"
        else:
            cause = "archive evolution/manual quirk"
        causes[cause] += 1
    top = []
    for key, count in patterns.most_common(30):
        top.append({"pattern": key, "count": count, "example": examples[key],
                    "cause": ("exporter formatting/structure bug" if key.startswith("structure:")
                              else "archive evolution/manual quirk" if examples[key]["day"] < "2026-09-22"
                              else "system data differs from archive (or exporter mapping rule)")})
    return {"days": len(results), "total_differences": len(all_diffs),
            "category_counts": dict(Counter(d["category"] for d in all_diffs)),
            "cause_counts": dict(causes), "top_patterns": top, "worst_days": day_counts[:15],
            "results": results}


def readable(report: dict[str, Any]) -> str:
    lines = [f"Duty fidelity: {report['days']} days; {report['total_differences']} differences",
             "Category counts: " + json.dumps(report["category_counts"], ensure_ascii=False),
             "Cause counts: " + json.dumps(report["cause_counts"], ensure_ascii=False), "", "Top patterns:"]
    for item in report["top_patterns"][:10]:
        ex = item["example"]
        value = f" archive={ex.get('archive','')!r} system={ex.get('system','')!r}" if "archive" in ex else ""
        lines.append(f"- {item['count']} {item['pattern']} cause={item['cause']} example={ex['day']} {ex.get('path','')}{value}")
    lines.append("\nWorst days:")
    for day, count, cats in report["worst_days"]:
        lines.append(f"- {day}: {count} {cats}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--day")
    group.add_argument("--all", action="store_true")
    parser.add_argument("--archive-root", type=Path, default=ARCHIVE_DEFAULT)
    parser.add_argument("--system-root", type=Path, required=True)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--text-out", type=Path)
    args = parser.parse_args(argv)
    days = [_ for _ in (_days() if args.all else [args.day]) if _ and DAY_RE.match(_)]
    results = [compare_day(day, args.archive_root, args.system_root) for day in days]
    report = summarize(results)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    text = readable(report)
    if args.json_out:
        args.json_out.write_text(payload + "\n", encoding="utf-8")
    if args.text_out:
        args.text_out.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Measure Word fidelity for the detailed daily board.

This module deliberately compares the archive XML with an already exported
DOCX.  It does not import the Flask app and never writes to the data store.

Examples:
  python3 tools/fidelity/board.py --day 2026-09-29 \
    --archive-root /path/to/2026 --exports /tmp/fidelity-board
  python3 tools/fidelity/board.py --all --archive-root /path/to/2026 \
    --exports /tmp/fidelity-board --json-out /tmp/board.json --text-out /tmp/board.txt
"""
from __future__ import annotations

import argparse
import json
import hashlib
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from zipfile import ZipFile

from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
Q = lambda name: "{" + W + "}" + name
ARCHIVE_DEFAULT = Path(__file__).resolve().parents[3] / "2026"


def days_between(start="2026-08-01", end="2026-09-29"):
    d, last = date.fromisoformat(start), date.fromisoformat(end)
    while d <= last:
        yield d.isoformat()
        d += timedelta(days=1)


def _attr(node, name, default=""):
    return node.get(Q(name), default) if node is not None else default


def _cell_text(tc):
    return "".join(tc.itertext()).replace("\xa0", " ")


def normalize(text: str) -> str:
    """Comparison normalization, intentionally less aggressive than display."""
    s = unicodedata.normalize("NFKC", text or "")
    s = s.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789"))
    s = s.replace("ـ", "")
    s = "".join(c for c in s if unicodedata.category(c) not in {"Mn", "Me"})
    s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    s = s.replace("ى", "ي")
    s = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _cell_meta(tc):
    pr = tc.find(Q("tcPr"))
    span = _attr(pr.find(Q("gridSpan")) if pr is not None else None, "val", "1")
    vm_node = pr.find(Q("vMerge")) if pr is not None else None
    vm = "" if vm_node is None else (_attr(vm_node, "val", "continue") or "continue")
    shd = pr.find(Q("shd")) if pr is not None else None
    return {"span": int(span or 1), "vmerge": vm, "shading": _attr(shd, "fill", "")}


def read_docx(path: Path):
    with ZipFile(path) as z:
        root = etree.fromstring(z.read("word/document.xml"))
    sect = root.find(".//" + Q("sectPr"))
    pg = sect.find(Q("pgSz")) if sect is not None else None
    mar = sect.find(Q("pgMar")) if sect is not None else None
    tables = root.xpath("//w:tbl", namespaces={"w": W})
    table = tables[0] if tables else None
    grid = table.find(Q("tblGrid")) if table is not None else None
    widths = [_attr(c, "w") for c in grid.findall(Q("gridCol"))] if grid is not None else []
    rows = []
    if table is not None:
        for tr in table.findall(Q("tr")):
            cells = []
            for tc in tr.findall(Q("tc")):
                cells.append({"text": _cell_text(tc), **_cell_meta(tc)})
            rows.append(cells)
    return {
        "path": str(path),
        "page": {"w": _attr(pg, "w"), "h": _attr(pg, "h"), "orient": _attr(pg, "orient"),
                 "top": _attr(mar, "top"), "right": _attr(mar, "right"),
                 "bottom": _attr(mar, "bottom"), "left": _attr(mar, "left")},
        "columns": len(widths), "grid_widths": widths, "rows": rows,
        "paragraphs": ["".join(p.itertext()) for p in root.xpath("//w:body/w:p", namespaces={"w": W})],
    }


def signature(doc):
    return {"page": doc["page"], "columns": doc["columns"],
            "grid_widths": doc["grid_widths"], "row_count": len(doc["rows"]),
            "merge_shape": [[(c["span"], c["vmerge"]) for c in row] for row in doc["rows"]]}


def _flat(doc):
    return [[normalize(c["text"]) for c in row] for row in doc["rows"]]


def classify_diff(a, b):
    if not a and b:
        return "DATA-EXTRA", "real-value-mismatch"
    if a and not b:
        return "DATA-MISSING", "real-value-mismatch"
    if normalize(a) == normalize(b):
        return None, None
    # A weaker whitespace/punctuation comparison identifies display-only drift.
    loose = lambda x: re.sub(r"[\s/،,+×()\"'_-]+", "", normalize(x))
    sub = "abbreviation/formatting-only" if loose(a) == loose(b) else "real-value-mismatch"
    return "DATA-DIFFERENT", sub


def compare(day, archive, exported):
    a, b = read_docx(archive), read_docx(exported)
    issues = []
    if (a["columns"], a["grid_widths"]) != (b["columns"], b["grid_widths"]):
        issues.append({"category": "STRUCTURE", "detail": "grid", "archive": [a["columns"], a["grid_widths"]],
                       "system": [b["columns"], b["grid_widths"]]})
    if a["page"] != b["page"]:
        issues.append({"category": "STRUCTURE", "detail": "page-settings", "archive": a["page"], "system": b["page"]})
    if len(a["rows"]) != len(b["rows"]):
        issues.append({"category": "STRUCTURE", "detail": "row-count", "archive": len(a["rows"]), "system": len(b["rows"])})
    ar, br = _flat(a), _flat(b)
    for ri in range(max(len(ar), len(br))):
        ac, bc = ar[ri] if ri < len(ar) else [], br[ri] if ri < len(br) else []
        for ci in range(max(len(ac), len(bc))):
            av, bv = (ac[ci] if ci < len(ac) else ""), (bc[ci] if ci < len(bc) else "")
            cat, sub = classify_diff(av, bv)
            if cat:
                issues.append({"category": cat, "subtype": sub, "row": ri, "col": ci,
                               "archive": av, "system": bv})
    # Row order is a separate signal: same non-empty tokens but materially reordered.
    aa = [x for row in ar for x in row if x]
    bb = [x for row in br for x in row if x]
    if aa and bb and set(aa) == set(bb) and aa != bb:
        issues.append({"category": "ORDER", "detail": "same-cell-token-set-different-order"})
    # The route's source-doc decision is external to this comparator. Byte
    # equality is a useful observable proxy, without assuming where the
    # private data copy stores source_docs.
    byte_equal_archive = hashlib.sha256(archive.read_bytes()).digest() == hashlib.sha256(exported.read_bytes()).digest()
    return {"day": day, "archive": str(archive), "system": str(exported),
            "byte_equal_archive": byte_equal_archive, "archive_signature": signature(a),
            "system_signature": signature(b), "issues": issues,
            "archive_rows": ar, "system_rows": br}


def locate_archive(root: Path, day: str):
    d = date.fromisoformat(day)
    # ``archive_root`` is the supplied .../2026 directory, not its parent.
    p = root / str(d.month) / str(d.day) / f"{d.day}.docx"
    return p if p.is_file() else None


def run(days, archive_root, exports):
    results, missing = [], []
    for day in days:
        archive = locate_archive(archive_root, day)
        exported = exports / day / "board.docx"
        if not archive or not exported.is_file():
            missing.append({"day": day, "archive": bool(archive), "system": exported.is_file()})
            continue
        results.append(compare(day, archive, exported))
    counts = Counter(issue["category"] for result in results for issue in result["issues"])
    patterns = Counter()
    examples = defaultdict(list)
    for result in results:
        for issue in result["issues"]:
            key = issue["category"] + ":" + issue.get("detail", issue.get("subtype", ""))
            patterns[key] += 1
            if len(examples[key]) < 5:
                examples[key].append(result["day"] + (f" r{issue['row']}c{issue['col']}" if "row" in issue else ""))
    worst = sorted(((r["day"], len(r["issues"])) for r in results), key=lambda x: (-x[1], x[0]))
    return {"kind": "board", "range": [min(days), max(days)] if days else [],
            "days_compared": len(results), "missing": missing, "category_counts": dict(counts),
            "patterns": [{"pattern": k, "count": v, "examples": examples[k]} for k, v in patterns.most_common()],
            "worst_days": worst[:10], "days": results}


def render_text(report):
    lines = [f"board fidelity: {report['days_compared']} days; range {report['range']}",
             "category counts: " + json.dumps(report["category_counts"], ensure_ascii=False),
             "recurring patterns:"]
    for p in report["patterns"]:
        lines.append(f"- {p['pattern']}: {p['count']} ({', '.join(p['examples'])})")
    lines.append("worst days: " + ", ".join(f"{d}={n}" for d, n in report["worst_days"]))
    if report["missing"]:
        lines.append("missing artifacts: " + json.dumps(report["missing"], ensure_ascii=False))
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--day")
    group.add_argument("--all", action="store_true")
    ap.add_argument("--archive-root", type=Path, default=ARCHIVE_DEFAULT)
    ap.add_argument("--exports", type=Path, required=True)
    ap.add_argument("--json-out", type=Path)
    ap.add_argument("--text-out", type=Path)
    args = ap.parse_args(argv)
    days = [args.day] if args.day else list(days_between())
    report = run(days, args.archive_root, args.exports)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    text = render_text(report)
    if args.json_out: args.json_out.write_text(payload + "\n", encoding="utf-8")
    if args.text_out: args.text_out.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

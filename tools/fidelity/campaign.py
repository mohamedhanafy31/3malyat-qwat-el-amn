#!/usr/bin/env python3
"""Compare archived and exported «يومية الحملة» DOCX files.

The comparator deliberately treats the archive as evidence, not as a source
for mutating application data.  It reduces merged Word cells to one logical
cell and compares the four regions of the latest layout (checkpoints, delivery
lines, plate register) between the archive file and the system export — both
now share the same layout, so both are read with `read_archive`.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

from docx import Document

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARCHIVE = ROOT.parent.parent / "2026"
DEFAULT_SYSTEM = Path("/tmp/fidelity-campaign-20261020")
DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
DIACRITICS = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed]")
PLATE = re.compile(r"(?:\d{3,5})")
DAY_RE = re.compile(r"(\d{1,2})-(\d{1,2})-(20\d\d)")


def clean(text: object) -> str:
    text = unicodedata.normalize("NFC", str(text or "")).translate(DIGITS)
    text = text.replace("ـ", "")
    text = DIACRITICS.sub("", text).replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي")
    return " ".join(text.split())


def logical_cells(row):
    """Return one value per unique XML cell, preserving left-to-right order."""
    out, seen = [], set()
    for cell in row.cells:
        key = id(cell._tc)
        if key in seen:
            continue
        seen.add(key)
        out.append(clean(cell.text))
    return out


def archive_files(root: Path):
    chosen = {}
    for path in root.glob("*/*/*.docx"):
        name = path.name
        if name.startswith("~$") or name.endswith(".tmp"):
            continue
        if "يومية الحملة عن يوم" not in name or "ارتكازات" in name or "Copy" in name:
            continue
        hit = DAY_RE.search(name.translate(DIGITS))
        if not hit:
            continue
        day = f"{hit[3]}-{int(hit[2]):02d}-{int(hit[1]):02d}"
        # A day folder with the matching numeric name is the authoritative copy.
        if day not in chosen or path.parent.name == str(int(day[8:])):
            chosen[day] = path
    return dict(sorted((d, p) for d, p in chosen.items() if "2026-08-01" <= d <= "2026-09-29"))


def _is_plate_row(row):
    return bool(row) and len(row) >= 2 and all(
        (not value) or ("/" in value and any(ch.isdigit() for ch in value)) for value in row
    )


def read_archive(path: Path):
    table = Document(path).tables[0]
    rows = [logical_cells(row) for row in table.rows]
    divider = next((i for i, row in enumerate(rows) if "خط" in " ".join(row) and "توص" in " ".join(row)), None)
    if divider is None:
        divider = len(rows)
    plate_start = next((i for i, row in enumerate(rows[divider + 1:], divider + 1) if _is_plate_row(row)), len(rows))
    return {
        "path": str(path), "rows": rows,
        "title": rows[0] if rows else [],
        "checkpoint_header": rows[1] if len(rows) > 1 else [],
        "checkpoints": rows[2:divider],
        "divider": rows[divider] if divider < len(rows) else [],
        "delivery_header": rows[divider + 1] if divider + 1 < len(rows) else [],
        "delivery": rows[divider + 2:plate_start],
        "plates": rows[plate_start:],
    }


def read_system(path: Path):
    doc = Document(path)
    table = doc.tables[0]
    rows = [logical_cells(row) for row in table.rows]
    sections = defaultdict(list)
    current = ""
    headings = {clean(x): x for x in ("اللواري الأساسية", "الخدمات الطارئة", "الأقوال اليومية", "لواري التعيينات")}
    for row in rows[1:]:
        label = row[0] if row else ""
        if len(row) == 1 and (label in headings or label.startswith("الخدمات الطار")):
            current = headings.get(label, "الخدمات الطارئة")
        elif current:
            sections[current].append(row)
    title = [clean(p.text) for p in doc.paragraphs if clean(p.text)]
    return {"path": str(path), "rows": rows, "title": title, "sections": dict(sections)}


def name_key(text):
    text = clean(text)
    text = re.sub(r"\b(?:\d{1,2}\s*[صظمل])\b", "", text)
    text = text.replace("الإفطار", "الافطار").replace("المحكمه", "المحكمة")
    return " ".join(text.split())


def plate_key(text):
    nums = re.findall(r"\d+", clean(text))
    return nums[-1] if nums else clean(text)


def value_kind(col, archive, system):
    a, b = clean(archive), clean(system)
    if not a or not b:
        if col == 0 and (a.isdigit() or b.isdigit()):
            return "DATA-DIFFERENT:formatting-only"
        return "DATA-MISSING" if a else "DATA-EXTRA"
    if a == b:
        return None
    if col == 3 and plate_key(a) == plate_key(b):
        return "DATA-DIFFERENT:formatting-only"
    aliases = {("مايك", "ميك"), ("ميك", "مايك"), ("لوري", "لوري"),
               ("القول المكبر", "قول مكبر")}
    if (a, b) in aliases or (b, a) in aliases:
        return "DATA-DIFFERENT:abbreviation"
    if SequenceMatcher(None, a, b).ratio() >= 0.82:
        return "DATA-DIFFERENT:formatting-only"
    return "DATA-DIFFERENT:real-value"


def _row_diff(day, region, ar, sy, ar_index=None, sy_index=None):
    diffs = []
    n = max(len(ar), len(sy))
    for col in range(n):
        a, b = ar[col] if col < len(ar) else "", sy[col] if col < len(sy) else ""
        kind = value_kind(col, a, b)
        if kind:
            diffs.append({"day": day, "region": region, "row": ar_index, "system_row": sy_index,
                          "cell": col, "archive": a, "system": b, "category": kind})
    return diffs


def _unmatched(day, region, row, index, category):
    return [{"day": day, "region": region, "row": index, "cell": col,
             "archive": value if category == "DATA-MISSING" else "",
             "system": value if category == "DATA-EXTRA" else "", "category": category}
            for col, value in enumerate(row) if value]


def _compare_positional(day, region, archive_rows, system_rows):
    diffs = []
    for index in range(max(len(archive_rows), len(system_rows))):
        a = archive_rows[index] if index < len(archive_rows) else None
        b = system_rows[index] if index < len(system_rows) else None
        if a is not None and b is not None:
            diffs.extend(_row_diff(day, region, a, b, index, index))
        elif a is not None:
            diffs.extend(_unmatched(day, region, a, index, "DATA-MISSING"))
        else:
            diffs.extend(_unmatched(day, region, b, index, "DATA-EXTRA"))
    return diffs


def compare_day(day, archive_path: Path, system_path: Path):
    ar, sy = read_archive(archive_path), read_archive(system_path)
    diffs = []
    # الاتنين بنفس الشكل الأخير: العنوان ثم الارتكازات ثم الخطوط ثم السجل.
    if ar["title"] and sy["title"]:
        diffs.extend(_row_diff(day, "title", ar["title"], sy["title"], 0, 0))
    elif ar["title"]:
        diffs.append({"day": day, "region": "title", "category": "DATA-MISSING", "archive": ar["title"], "system": ""})
    diffs.extend(_compare_positional(day, "checkpoints", ar["checkpoints"], sy["checkpoints"]))
    diffs.extend(_compare_positional(day, "plates", ar["plates"], sy["plates"]))

    # خطوط التوصيل بتتطابق باسم الخدمة مش برقم الصف: الأرشيف فيه خدمات
    # مضافة يدوي، والمُصدِّر بيضيف لواري التعيينات.
    sys_rows = sy["delivery"]
    by_name = defaultdict(list)
    for i, row in enumerate(sys_rows):
        if len(row) > 1:
            by_name[name_key(row[1])].append((i, row))
    used = set()
    for i, row in enumerate(ar["delivery"], 15):
        key = name_key(row[1] if len(row) > 1 else "")
        candidates = [item for item in by_name.get(key, []) if item[0] not in used]
        if not candidates and "المحور" in key and "المحكمة" in key:
            candidates = [item for items in by_name.values() for item in items
                          if item[0] not in used and "المحور" in name_key(item[1][1]) and "المحكمة" in name_key(item[1][1])]
        if not candidates and key:
            fuzzy = []
            for candidate_key, items in by_name.items():
                for item in items:
                    if item[0] not in used:
                        fuzzy.append((SequenceMatcher(None, key, candidate_key).ratio(), item))
            if fuzzy:
                score, item = max(fuzzy, key=lambda pair: pair[0])
                if score >= 0.68:
                    candidates = [item]
        if candidates:
            si, srow = candidates[0]; used.add(si)
            diffs.extend(_row_diff(day, "delivery", row, srow, i, si))
        else:
            diffs.extend(_unmatched(day, "delivery", row, i, "DATA-MISSING"))
    for si, row in enumerate(sys_rows):
        if si not in used and any(row):
            diffs.extend(_unmatched(day, "delivery-extra", row, si, "DATA-EXTRA"))
    if len(ar["checkpoints"]) != len(sy["checkpoints"]):
        diffs.append({"day": day, "region": "checkpoints", "category": "STRUCTURE:row-count",
                      "archive": len(ar["checkpoints"]), "system": len(sy["checkpoints"])})
    return {"day": day, "archive": ar["path"], "system": sy["path"],
            "archive_shape": {"cols": max(map(len, ar["rows"]), default=0), "rows": len(ar["rows"]),
                              "checkpoints": len(ar["checkpoints"]), "delivery": len(ar["delivery"]), "plates": len(ar["plates"])},
            "system_shape": {"cols": max(map(len, sy["rows"]), default=0), "rows": len(sy["rows"]),
                             "checkpoints": len(sy["checkpoints"]), "delivery": len(sy["delivery"]), "plates": len(sy["plates"])},
            "diffs": diffs}


def summarize(results):
    counts = Counter(d["category"] for r in results for d in r["diffs"])
    by_day = Counter((r["day"],) for r in results for _ in r["diffs"])
    # القيم ممكن تكون قوايم (العنوان) فلازم تتحوّل لنص عشان تتعد
    flat = lambda value: " | ".join(map(str, value)) if isinstance(value, (list, tuple)) else value
    patterns = Counter((d["region"], d.get("cell", ""), d["category"],
                        flat(d.get("archive", "")), flat(d.get("system", "")))
                       for r in results for d in r["diffs"])
    return {"days": len(results), "counts": dict(counts),
            "worst_days": [{"day": day[0], "diffs": n} for day, n in by_day.most_common(10)],
            "top_patterns": [{"region": k[0], "cell": k[1], "category": k[2], "archive": k[3], "system": k[4], "count": n}
                             for k, n in patterns.most_common(30)], "results": results}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("days", nargs="*", help="YYYY-MM-DD; omitted means all discovered days")
    p.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE)
    p.add_argument("--system-root", type=Path, default=DEFAULT_SYSTEM)
    p.add_argument("--json-out", type=Path)
    p.add_argument("--text-out", type=Path)
    args = p.parse_args(argv)
    discovered = archive_files(args.archive_root)
    days = args.days or sorted(discovered)
    results = []
    for day in days:
        if day not in discovered:
            continue
        system = args.system_root / day / "campaign.docx"
        if system.exists():
            results.append(compare_day(day, discovered[day], system))
    report = summarize(results)
    text = [f"campaign fidelity: {report['days']} days"]
    text.append("counts: " + ", ".join(f"{k}={v}" for k, v in sorted(report["counts"].items())))
    text.append("worst: " + ", ".join(f"{x['day']}({x['diffs']})" for x in report["worst_days"]))
    for item in report["top_patterns"][:12]:
        text.append(f"{item['count']}x {item['category']} {item['region']} c{item['cell']}: {item['archive']} -> {item['system']}")
    rendered = "\n".join(text) + "\n"
    if args.json_out:
        args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.text_out:
        args.text_out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

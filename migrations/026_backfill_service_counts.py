#!/usr/bin/env python3
"""ترجع صفوف الأعداد اللي ضاعت من مستورد Excel، بإضافة محافظة فقط."""
from __future__ import annotations

import argparse
import re
import sys
from copy import deepcopy
from pathlib import Path

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import AlreadyDone, run  # noqa: E402
from backend.service_equivalence import services_equivalent  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BATCH = "counts-026"


def _options():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--archive-root", type=Path, default=ROOT.parent.parent / "2026")
    parser.add_argument("--from", dest="start", default="2026-08-01")
    parser.add_argument("--to", dest="end", default="2026-10-22")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/import-preview-counts-backfill.md")
    parser.add_argument("--write", action="store_true")
    return parser.parse_known_args(sys.argv[1:])[0]


def _read(path):
    book = load_workbook(path, data_only=True, read_only=True)
    rows = []
    try:
        for sheet in book.worksheets:
            block = ""
            for position, values in enumerate(sheet.iter_rows(values_only=True)):
                cells = ["" if value is None else str(value).strip() for value in values]
                joined = " ".join(cells)
                flat = joined.replace("إ", "ا").replace("أ", "ا")
                # نغيّر البلوك من العناوين فقط؛ اسم خدمة مثل «كنيسة ماري
                # جرجس الصباح» ماينفعش يقلب بقية الورقة لصباحية.
                if "خدم" in flat or "اعداد الخدمات" in flat:
                    if "طوار" in flat:
                        block = "طوارئ"
                    elif "ليل" in flat or "مسائي" in flat:
                        block = "ليلية"
                    elif "صباح" in flat:
                        block = "صباحية"
                for index in range(len(cells) - 1):
                    name, count = cells[index], cells[index + 1]
                    if not name or re.fullmatch(r"\d+", name) or not re.fullmatch(r"\d+", count):
                        continue
                    if name in {"الخدمة", "عدد المجندين", "المجموع", "الاجمالي", "إجمالي اعداد الخدمات"}:
                        continue
                    party = ""
                    match = re.search(r"\(([^)]+)\)\s*$", name)
                    if match:
                        party = match.group(1).strip()
                        name = name[:match.start()].strip()
                    rows.append({"name": name, "count": int(count), "block": block,
                                 "party": party, "weapon": "", "source_position": position})
    finally:
        book.close()
    return rows


def _archive_rows(root, day):
    folder = root / str(int(day[5:7])) / str(int(day[8:10]))
    paths = sorted(folder.glob("اعداد الخدمات*.xlsx"))
    return _read(paths[0]) if paths else []


def _day_result(data, day, archive):
    current = data.setdefault("service_counts", {}).setdefault(day, {}).setdefault("entries", [])
    added = []
    protected = _protected_names(data, day)
    protected_hits = 0
    # لا نعيد بناء الصفوف القائمة ولا نلمس عدد/اسم/ترتيب صف عدّله المشغّل.
    for wanted in archive:
        if any(services_equivalent(wanted["name"], name) for name in protected):
            protected_hits += 1
            continue
        if any(row.get("block") == wanted["block"] and services_equivalent(row.get("name"), wanted["name"])
               for row in current):
            continue
        identifier = f"CNT-026-{len(current) + len(added) + 1:04d}"
        row = {"id": identifier, "name": wanted["name"], "block": wanted["block"],
               "count": wanted["count"], "party": wanted["party"], "weapon": wanted["weapon"],
               "order": max([int(item.get("order") or 0) for item in current] + [0]) + len(added) + 1}
        # place after the last row from the same block; this preserves existing
        # values and keeps the added row in the Excel block order.
        indexes = [i for i, item in enumerate(current) if item.get("block") == wanted["block"]]
        insert_at = (indexes[-1] + 1) if indexes else len(current)
        current.insert(insert_at, row)
        added.append(row)
    before_services = sum(1 for row in current if row not in added)
    return added, before_services, len(current), sum(int(r.get("count") or 0) for r in current), protected_hits


def _protected_names(data, day):
    """أسماء لمسها المستخدم في سجل التغيير؛ الغموض هنا يتخطى الصف."""
    names = []
    for entry in data.get("change_log") or []:
        if entry.get("day") != day or entry.get("entity") not in {"counts", "service_counts", "service_count"}:
            continue
        for value in (entry.get("before"), entry.get("after")):
            if isinstance(value, dict) and value.get("name"):
                names.append(value["name"])
            elif isinstance(value, list):
                names.extend(item.get("name") for item in value if isinstance(item, dict) and item.get("name"))
    return [name for name in names if name]


def migrate(data, options=None):
    options = options or _options()
    working = data if options.write else deepcopy(data)
    changes = []
    totals = {"added": 0, "days": 0, "before": 0, "after": 0, "excel": 0, "protected": 0}
    from_day = options.start
    to_day = getattr(options, "end", None) or getattr(options, "to", None) or options.start
    for day in sorted((working.get("service_counts") or {})):
        if not from_day <= day <= to_day:
            continue
        archive = _archive_rows(options.archive_root, day)
        if not archive:
            continue
        before_rows = list((working.get("service_counts") or {}).get(day, {}).get("entries") or [])
        before_total = sum(int(row.get("count") or 0) for row in before_rows)
        added, _before_services, after_services, after_total, protected = _day_result(working, day, archive)
        totals["protected"] += protected
        if added:
            changes.append((day, added, len(before_rows), len(before_rows) + len(added), before_total,
                            after_total, len(archive), sum(row["count"] for row in archive)))
            totals["added"] += len(added); totals["days"] += 1
            totals["before"] += before_total; totals["after"] += after_total
            totals["excel"] += sum(row["count"] for row in archive)
    if not changes:
        raise AlreadyDone("مفيش صفوف أعداد ناقصة وآمنة للإضافة.")
    if options.write:
        from backend import changes as change_log
        change_log.record(data, "import", BATCH, "batch",
                          after={"days": totals["days"], "rows_added": totals["added"]},
                          text=f"استكمال صفوف الأعداد ({BATCH}): إضافة {totals['added']} صف")
    lines = [f"أيام اتعدلت: {totals['days']}", f"صفوف مضافة: {totals['added']}",
             f"صفوف اتخطت بسبب سجل تعديل: {totals['protected']}",
             f"إجمالي المجندين قبل/بعد الإضافة: {totals['before']} / {totals['after']}",
             f"إجمالي المجندين في Excel المقروء: {totals['excel']}"]
    preview = ["# معاينة استكمال صفوف «يومية الأعداد»", "",
               f"الوضع: {'تنفيذ' if options.write else 'عرض فقط'}", "",
               "| اليوم | الصفوف المضافة | الخدمات قبل | الخدمات بعد | المجندون قبل | المجندون بعد | Excel |", 
               "|---|---|---:|---:|---:|---:|---:|"]
    for day, added, before_n, after_n, before_t, after_t, excel_n, excel_t in changes:
        names = "، ".join(f"{r['name']} ({r['count']})" for r in added)
        preview.append(f"| {day} | {names} | {before_n} | {after_n} | {before_t} | {after_t} | {excel_n} خدمة / {excel_t} مجند |")
    options.report.parent.mkdir(parents=True, exist_ok=True)
    options.report.write_text("\n".join(preview) + "\n", encoding="utf-8")
    return lines + [f"تقرير المعاينة: {options.report}"]


if __name__ == "__main__":
    run(from_schema=6, to_schema=6, migrate=migrate, title="استكمال صفوف أعداد الخدمات")

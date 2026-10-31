#!/usr/bin/env python3
"""استيراد بيانات الأرشيف اللي المستورد التاريخي ما التقطهاش — dry-run افتراضيًا.

أربع حاجات (مراحل `importer/archive_gaps.py` و`importer/single_day.py`):

1. مدخلات «يومية انتظام الخدمات» (`<D>..docx`) -> `regularity_inputs[day]` في core:
   نص المدير/الوكيل الإضافي، مشرفي القول المكبر (صباحي/ليلي)، والملاحظات الحرة.
   اليوم من عنوان الملف «… الموافق D/M/YYYY» (مش من الفولدر).
2. نص «عمل بالإدارة» الحر لكل ضابط من اللوحة التفصيلية -> `admin_work_text` في حالة الضابط
   (وبينقل `note` لو نفس النص).
3. تقسيم تغطية الهدف بالوقت (`… حتى 4م` ثم `… من 4م`) -> `periods` + `officer_ids` على صف الهدف.
4. أيام الأرشيف اللي مالهاش ولا بيانات مخزّنة (2026-10-22) بتتستورد كاملة بنفس مراحل المستورد
   التاريخي جوه مجلد مؤقت (discover → … → verify) وتتطبّق بـ`verify.build_dataset`.

واعي بالتعارض: أي حقل ليه قيمة مخزّنة مختلفة عن الأرشيف **مابيتلمسش** ويتطبع كتعارض؛ الحقول
الفاضية بس هي اللي بتتملى. الأسماء/الصفوف اللي مش بتتحل بشكل مؤكد بتروح لـ«غير محلول».
إعادة التشغيل آمنة: ما فيش حاجة جديدة = خروج هادي. `--write` بياخد نسخة احتياطية الأول
(migrations/common.py) ويسجّل سطر استيراد في change_log.

    python3 migrations/023_import_archive_gaps.py                     # معاينة
    python3 migrations/023_import_archive_gaps.py --report docs/import-preview-archive-gaps.md
    python3 migrations/023_import_archive_gaps.py --write             # تنفيذ (والنظام واقف)

خيارات: --archive-root (الافتراضي ../../2026) و--from و--to و--no-day-import و--decisions.
"""
import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import AlreadyDone, run  # noqa: E402
from importer import archive_gaps  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BATCH = "archive-gaps-023"
PENDING_SOURCE_DOCS: list[tuple[str, str]] = []


def _options():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--archive-root", type=Path, default=ROOT.parent.parent / "2026")
    parser.add_argument("--from", dest="start", default="2026-08-01")
    parser.add_argument("--to", dest="end", default=None)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--no-day-import", action="store_true", help="ماتستوردش الأيام الناقصة بالكامل")
    parser.add_argument("--decisions", type=Path, default=None, help="مجلد قرارات الهويات/المرادفات (للاستيراد الكامل)")
    parser.add_argument("--after-rate", default=None, help="نص نسب التطابق بعد الاستيراد يتكتب في التقرير بس")
    return parser.parse_known_args(sys.argv[1:])[0]


def _decisions(options):
    from backend import store
    for candidate in (options.decisions, store.DATA_DIR / "import" / "decisions", ROOT / "data" / "import" / "decisions"):
        if candidate and Path(candidate).is_dir():
            return Path(candidate)
    return None


def migrate(data, options=None):
    options = options or _options()
    root = options.archive_root.resolve()
    report = archive_gaps.run_all(data, root, options.start, options.end, apply=True, batch=BATCH,
                                  decisions=_decisions(options), import_days=not options.no_day_import)
    imports = report["day_imports"]
    total = archive_gaps.totals(report, imports)
    mode = "write" if options.write else "dry-run"
    if options.report:
        options.report.parent.mkdir(parents=True, exist_ok=True)
        after = dict(item.split("=", 1) for item in (options.after_rate or "").split(";") if "=" in item)
        options.report.write_text(archive_gaps.render_preview(report, data, mode, imports, after or None),
                                  encoding="utf-8")
    if not total["add"]:
        raise AlreadyDone(f"فجوات الأرشيف متملية بالفعل — مفيش حقول جديدة (تعارضات متسابة: {total['conflict']}، "
                          f"غير محلول: {total['unresolved']}).")

    PENDING_SOURCE_DOCS[:] = [(item["source_doc"][0], item["source_doc"][1])
                              for item in imports if item["status"] == "import" and item.get("source_doc")]
    from backend import changes
    changes.record(
        data, "import", BATCH, "batch",
        after={"fields_added": {c: total[c]["add"] for c in archive_gaps.CATEGORIES},
               "days_imported": [x["day"] for x in imports if x["status"] == "import"],
               "conflicts_skipped": total["conflict"], "unresolved": total["unresolved"]},
        text=f"استيراد فجوات الأرشيف ({BATCH}): {total['regularity']['add']} مدخل انتظام، "
             f"{total['admin_work']['add']} نص عمل بالإدارة، {total['split_target']['add']} تقسيم هدف، "
             f"{total['day_imports']['days']} يوم كامل، {total['conflict']} تعارض اتسابوا")
    lines = [f"{total['days']} يوم فيه فجوات ({report['range'][0]} .. {report['range'][1]})، "
             f"{total['days_with_adds']} فيهم حقول جديدة.",
             f"حقول هتتضاف: {total['add']} (منها {total['overrides_inherited']} بتغيّر قيمة موروثة).",
             f"تعارضات اتسابت من غير لمس: {total['conflict']}. غير محلول (محتاج قرار): {total['unresolved']}."]
    for category in archive_gaps.CATEGORIES:
        b = total[category]
        lines.append(f"{archive_gaps.CATEGORY_LABELS[category]}: يضاف {b['add']}، مطابق {b['same']}، "
                     f"تعارض {b['conflict']}، غير محلول {b['unresolved']} ({b['days_add']} يوم).")
    for item in imports:
        lines.append(f"يوم {item['day']}: {item['status']} — {item['reason']}"
                     + (f" {item['stats']}" if item["stats"] else ""))
    return lines + ([f"تقرير المعاينة: {options.report}"] if options.report else [])


def _copy_source_docs():
    """نسخة الـWord الأصلي لكل يوم اتستورد كامل (زي STORE القديم) — بعد ما الكتابة تنجح بس."""
    from backend import store
    for source, name in PENDING_SOURCE_DOCS:
        target = store.DATA_DIR / "source_docs" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        print(f"اتنسخ الأصل: {target}")


if __name__ == "__main__":
    run(from_schema=6, to_schema=6, migrate=migrate, title="استيراد فجوات الأرشيف (انتظام/عمل بالإدارة/تقسيم أهداف/يوم ناقص)")
    if "--write" in sys.argv and PENDING_SOURCE_DOCS:
        _copy_source_docs()

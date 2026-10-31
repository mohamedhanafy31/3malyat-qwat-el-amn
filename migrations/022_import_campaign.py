#!/usr/bin/env python3
"""استيراد «يومية الحملة» من الأرشيف لـ`day_campaign` — dry-run افتراضيًا.

المستورد التاريخي كان بيتخطى ملفات الحملة (importer/discover.py)، فبيانات
2026-08-01..2026-10-22 ناقصة أو موروثة من أيام تانية. السكربت ده بيقرا
«يومية الحملة عن يوم …» لكل يوم (مرحلة `importer/campaign.py`) ويملّا:
الارتكازات (المركبة/اللوحة/النوع)، اللوريات + الخدمات الملحقة، الخدمات المباشرة
(سائق + مركبات بأفراد التكليف)، الأقوال اليومية (+ ربط الخدمة الأساسية)، وسجل اللوحات.

واعي بالتعارض: أي حقل ليه قيمة مخزّنة فعلًا في اليوم (دخلها مستخدم أو استيراد
سابق) وبتختلف عن الأرشيف **مابيتلمسش** ويتطبع كتعارض. الحقول الفاضية أو
الموروثة بس هي اللي بتتملى. إعادة التشغيل آمنة: ما فيش حاجة جديدة = خروج هادي.

    python3 migrations/022_import_campaign.py                       # معاينة
    python3 migrations/022_import_campaign.py --report docs/import-preview-campaign.md
    python3 migrations/022_import_campaign.py --write               # تنفيذ (والنظام واقف)

خيارات: --archive-root (الافتراضي ../../2026) و--from و--to.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import AlreadyDone, run  # noqa: E402
from importer import campaign  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BATCH = "campaign-022"


def _options():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--archive-root", type=Path, default=ROOT.parent.parent / "2026")
    parser.add_argument("--from", dest="start", default="2026-08-01")
    parser.add_argument("--to", dest="end", default=None)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--after-rate", default=None, help="نص نسبة التطابق بعد الاستيراد يتكتب في التقرير بس")
    return parser.parse_known_args(sys.argv[1:])[0]


def migrate(data, options=None):
    options = options or _options()
    report = campaign.run_import(data, options.archive_root.resolve(), options.start, options.end)
    if not report["plans"]:
        raise AlreadyDone("مفيش ملفات يومية حملة في النطاق.")
    total = campaign.totals(report)
    mode = "write" if options.write else "dry-run"
    if options.report:
        options.report.parent.mkdir(parents=True, exist_ok=True)
        options.report.write_text(campaign.render_preview(report, data, mode, options.after_rate), encoding="utf-8")
    if not total["fields_add"]:
        raise AlreadyDone(f"يومية الحملة متملية بالفعل — مفيش حقول جديدة (تعارضات متسابة: {total['fields_conflict']}).")

    from backend import changes
    changes.record(
        data, "import", BATCH, "batch",
        after={"days": total["days_with_adds"], "fields_added": total["fields_add"],
               "conflicts_skipped": total["fields_conflict"], "unresolved": total["unresolved"]},
        text=f"استيراد يومية الحملة ({BATCH}): {total['days_with_adds']} يوم، "
             f"{total['fields_add']} حقل، {total['fields_conflict']} تعارض اتسابوا")
    rate = campaign._pct
    return [
        f"{total['days']} يوم ({report['range'][0]} .. {report['range'][1]})، {total['days_with_adds']} فيهم حقول جديدة.",
        f"حقول هتتضاف: {total['fields_add']} (منها {total['overrides_inherited']} بتغيّر قيمة موروثة)، "
        f"مطابقة بالفعل: {total['fields_same']}.",
        f"تعارضات اتسابت من غير لمس: {total['fields_conflict']} في {total['days_with_conflicts']} يوم.",
        f"صفوف محلولة: {total['rows_resolved']}/{total['rows']} ({rate(total['rows_resolved'], total['rows'])})، "
        f"لوحات: {total['plates_resolved']}/{total['plates']} ({rate(total['plates_resolved'], total['plates'])}).",
        f"سائقين: مربوط {total['drivers_linked']}، نص {total['drivers_text']}، غامض {total['drivers_ambiguous']} "
        f"(من {total['drivers']}).",
        f"غير محلول (محتاج قرار): {total['unresolved']}.",
    ] + ([f"تقرير المعاينة: {options.report}"] if options.report else [])


if __name__ == "__main__":
    run(from_schema=6, to_schema=6, migrate=migrate, title="استيراد يومية الحملة من الأرشيف")

#!/usr/bin/env python3
"""تصحيح Class C بشكل محافظ — dry-run افتراضيًا.

    python3 migrations/024_correct_import_errors.py --report docs/import-preview-corrections.md
    python3 migrations/024_correct_import_errors.py --write

الهجرة بتعيد مراحل المستورد في temp، ومابتلمسش غير حقل لسه مساوي
لنسخة transform الأصلية ومفيش له edit لاحق في change_log. الكتابة بتاخد
نسخة احتياطية عن طريق migrations/common.py وبتسجل batch `correction-024`.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import AlreadyDone, run  # noqa: E402
from importer import corrections  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BATCH = "correction-024"


def _options():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--archive-root", type=Path, default=ROOT.parent.parent / "2026")
    parser.add_argument("--from", dest="start", default="2026-08-01")
    parser.add_argument("--to", dest="end", default="2026-10-22")
    parser.add_argument("--kinds", default=",".join(corrections.KINDS))
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--write", action="store_true")
    return parser.parse_known_args(sys.argv[1:])[0]


def migrate(data, options=None):
    options = options or _options()
    kinds = tuple(value.strip() for value in options.kinds.split(",") if value.strip())
    unknown = sorted(set(kinds) - set(corrections.KINDS))
    if unknown:
        raise SystemExit("أنواع غير معروفة: " + "، ".join(unknown))
    report = corrections.run_import(
        data, options.archive_root.resolve(), options.start, options.end, kinds,
        provenance_root=ROOT / "data" / "import", apply=True)
    total = corrections.totals(report)
    if options.report:
        options.report.parent.mkdir(parents=True, exist_ok=True)
        options.report.write_text(corrections.render_preview(
            report, "write" if options.write else "dry-run"), encoding="utf-8")
    if not total["correct"]:
        raise AlreadyDone(f"مفيش حقول آمنة للتصحيح (محمي: {total['protected']}، "
                          f"غير محسوم: {total['unresolved']}).")
    from backend import changes
    changes.record(
        data, "import", BATCH, "batch",
        after={"fields_corrected": total["correct"], "protected": total["protected"],
               "unresolved": total["unresolved"],
               "by_kind": {kind: dict(values) for kind, values in total["kinds"].items()}},
        text=f"تصحيح أخطاء الاستيراد ({BATCH}): {total['correct']} حقل، "
             f"{total['protected']} محمي، {total['unresolved']} غير محسوم")
    lines = [f"هيتصحح {total['correct']} حقل؛ {total['protected']} محمي لتعديل لاحق؛ "
             f"{total['unresolved']} غير محسوم."]
    for kind in kinds:
        row = total["kinds"][kind]
        lines.append(f"{corrections.KIND_LABELS[kind]}: تصحيح {row['correct']}، محمي {row['protected']}، "
                     f"غير محسوم {row['unresolved']}.")
    return lines + ([f"تقرير المعاينة: {options.report}"] if options.report else [])


if __name__ == "__main__":
    run(from_schema=6, to_schema=6, migrate=migrate,
        title="تصحيح آمن لأخطاء الاستيراد التاريخية")

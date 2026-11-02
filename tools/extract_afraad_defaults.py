#!/usr/bin/env python3
"""يستخرج قوام/تسليح/انتظام الخدمات من آخر كشف أفراد للافتراضيات."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import docx  # noqa: E402

from backend.afraad_ocr import _service_score  # noqa: E402
from backend.dated import afraad_basic_on  # noqa: E402
from backend.store import ALL_DAYS, load_data  # noqa: E402
from backend.text import core_service_name, norm  # noqa: E402
from tools.import_afraad_rosters import basic_rows, discover, field, roster_day  # noqa: E402

OUTPUT = ROOT / "backend" / "afraad_defaults.json"
MATCH_MIN = 0.72


def _identity(name: str) -> str:
    """فرعا كمين 109 مكتوبان في Word بنفس الاسم؛ الترتيب يفصلهما."""
    base = str(name or "").partition(" - ")[0]
    return norm(core_service_name(base))


def match_rows(rows, service_names):
    """مطابقة بالاسم المطبّع، وأقرب صورة وحيدة للاختلاف البسيط."""
    matched, used = {}, set()
    by_identity = {}
    for index, row in enumerate(rows):
        by_identity.setdefault(_identity(row["service"]), []).append(index)
    ours_by_identity = {}
    for name in service_names:
        ours_by_identity.setdefault(_identity(name), []).append(name)

    for identity, names in ours_by_identity.items():
        candidates = by_identity.get(identity, [])
        for name, index in zip(names, candidates):
            matched[name], used = rows[index], used | {index}

    for name in service_names:
        if name in matched:
            continue
        scored = sorted(((_service_score(name, row["service"]), index)
                         for index, row in enumerate(rows) if index not in used), reverse=True)
        if not scored or scored[0][0] < MATCH_MIN:
            continue
        best = scored[0][0]
        winners = [index for score, index in scored if score >= best - 0.02]
        if len(winners) == 1:
            matched[name] = rows[winners[0]]
            used.add(winners[0])
    return matched, [row for index, row in enumerate(rows) if index not in used]


def _defaults(row):
    """القوام والتسليح والانتظام زي ما اتكتبوا في كشف الأرشيف."""
    return {key: field(row[key]) for key in ("count", "weapon", "schedule")}


def _source_file(archive: Path, explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.resolve()
    scan = archive / "2026" if (archive / "2026").is_dir() else archive
    files, notes = discover(scan, "0001-01-01", None)
    for note in notes:
        print("note:", note)
    if not files:
        raise SystemExit("لم أجد أي كشف أفراد في الأرشيف.")
    return files[max(files)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=Path("../.."),
                        help="جذر الأرشيف (الافتراضي ../..)")
    parser.add_argument("--file", type=Path, help="ملف Word محدد بدل آخر ملف")
    args = parser.parse_args()

    archive = args.archive.resolve()
    source = _source_file(archive, args.file)
    document = docx.Document(source)
    day, _date_source = roster_day(source, document)
    service_names = [entry["name"] for entry in afraad_basic_on(load_data(ALL_DAYS), day)]
    rows = basic_rows(document)
    matched, unmatched_rows = match_rows(rows, service_names)
    services = {name: _defaults(matched[name])
                for name in service_names if name in matched}
    # الخدمة ممكن تتضاف للكتالوج بعد الاستخراج؛ نخزن صف الأرشيف باسمه كمان.
    for row in unmatched_rows:
        archive_name = " ".join(str(row.get("service") or "").split())
        if archive_name:
            services.setdefault(archive_name, _defaults(row))
    try:
        relative = source.relative_to(archive).as_posix()
    except ValueError:
        relative = source.as_posix()
    OUTPUT.write_text(json.dumps({"source": relative, "services": services},
                                 ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    unmatched_services = [name for name in service_names if name not in matched]
    print(f"source={relative}")
    print(f"matched={len(matched)}")
    for name in matched:
        print(f"  + {name} <- {matched[name]['service']}")
    print("unmatched_archive:")
    for row in unmatched_rows:
        print(f"  - {row['service']}")
    print("unmatched_services:")
    for name in unmatched_services:
        print(f"  - {name}")
    print(f"written={OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

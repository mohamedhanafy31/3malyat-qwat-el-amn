#!/usr/bin/env python3
"""First-run setup of the daily files folder (`data/daily_files`).

1. COPIES the operators' archive folders (2023 → 2026, exactly as they are:
   `<year>/<month>/<day>/...`) into the system's daily files root. It copies, never
   moves: the originals stay where they are. Resumable: a file that already exists
   with the same size is skipped; every copied file is verified by size.
2. Continues from `daily_files_managed_from` (default 2026-09-30, the first day
   the archive has no folder for): for each day up to today it makes sure the folder
   exists and holds everything from the previous day's folder (every file except the
   five daily files; an existing folder is only topped up with MISSING files, nothing
   is overwritten), then generates the five daily files — only for days that have
   data in the system. A day without data gets its folder and nothing else: the
   operator enters the data and presses «تحديث الملفات».
3. --prune-empty: removes the daily files the system generated earlier for days
   that have NO data (they have a null signature in the manifest).

Dry-run by default (counts, sizes, free space). --write needs the system stopped
(storage lock). Safe to re-run.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_ARCHIVE = ROOT.parent.parent
SKIP_NAMES = {"desktop.ini", "Thumbs.db"}


def skip(name: str) -> bool:
    return name.startswith("~$") or name.endswith(".tmp") or name in SKIP_NAMES


def walk_year(base: Path):
    for current, dirs, files in os.walk(base):
        dirs.sort()
        for name in sorted(files):
            if not skip(name):
                yield Path(current) / name


def copy_year(base: Path, dest_root: Path, write: bool, stats: dict):
    for source in walk_year(base):
        relative = source.relative_to(base.parent)
        target = dest_root / relative
        size = source.stat().st_size
        stats["files"] += 1
        stats["bytes"] += size
        if target.exists() and target.stat().st_size == size:
            stats["skipped"] += 1
            continue
        stats["to_copy"] += 1
        stats["to_copy_bytes"] += size
        if not write:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(f".{target.name}.part")
        shutil.copy2(source, temp)
        if temp.stat().st_size != size:
            temp.unlink(missing_ok=True)
            raise RuntimeError(f"حجم الملف بعد النسخ مختلف: {source}")
        os.replace(temp, target)
        stats["copied"] += 1
        if stats["copied"] % 500 == 0:
            print(f"  … {stats['copied']} ملف اتنسخ ({stats['to_copy']} مطلوب)", flush=True)


def human(count: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if count < 1024 or unit == "GB":
            return f"{count:.1f} {unit}"
        count /= 1024
    return f"{count:.1f} GB"


def prune_candidates(until):
    """ملفات اليوميات المتولّدة (توقيعها null في الـmanifest) لأيام بلا بيانات."""
    from backend import daily_files

    end = until or date.today().isoformat()
    found = []
    for day, row in sorted(daily_files._manifest().items()):
        if day > end or row.get("sig") is not None or daily_files.has_data(day):
            continue
        folder = daily_files.day_folder(day)
        for name in daily_files.file_names(day).values():
            if (folder / name).is_file():
                found.append(folder / name)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE,
                        help="الفولدر اللي فيه 2023 و2024 و2025 و2026")
    parser.add_argument("--years", nargs="+", default=["2023", "2024", "2025", "2026"])
    parser.add_argument("--until", default=None, help="آخر يوم يتولّد (افتراضيًا النهارده)")
    parser.add_argument("--no-copy", action="store_true", help="تخطّي نسخ الأرشيف")
    parser.add_argument("--no-chain", action="store_true", help="تخطّي إنشاء الأيام الجديدة وتوليد ملفاتها")
    parser.add_argument("--prune-empty", action="store_true",
                        help="امسح اليوميات المتولّدة لأيام مالهاش بيانات")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    from backend import daily_files, store

    dest = daily_files.daily_files_root()
    managed_from = daily_files.managed_from()
    print(f"الأرشيف: {args.archive_root}\nالوجهة: {dest}\nيكمّل النظام من: {managed_from}")
    free = shutil.disk_usage(dest.parent if dest.parent.exists() else ROOT).free
    print(f"المساحة الفاضية: {human(free)}")

    if not args.no_copy:
        stats = {"files": 0, "bytes": 0, "skipped": 0, "to_copy": 0, "to_copy_bytes": 0, "copied": 0}
        for year in args.years:
            base = args.archive_root / year
            if not base.is_dir():
                print(f"  تخطّي {year}: مش موجود")
                continue
            before = dict(stats)
            copy_year(base, dest, args.write, stats)
            print(f"  {year}: {stats['files'] - before['files']} ملف "
                  f"({human(stats['bytes'] - before['bytes'])})، "
                  f"المطلوب نسخه {stats['to_copy'] - before['to_copy']}")
        print(f"إجمالي: {stats['files']} ملف ({human(stats['bytes'])})، "
              f"اتخطّى الموجود {stats['skipped']}، "
              f"{'اتنسخ' if args.write else 'هيتنسخ'} {stats['copied'] if args.write else stats['to_copy']} "
              f"({human(stats['to_copy_bytes'])})")
        if stats["to_copy_bytes"] > free * 0.9:
            print("المساحة الفاضية مش كفاية.")
            return 2

    days = []
    if not args.no_chain:
        end = date.fromisoformat(args.until) if args.until else date.today()
        cursor = date.fromisoformat(managed_from)
        while cursor <= end:
            days.append(cursor.isoformat())
            cursor += timedelta(days=1)
        with_data = [day for day in days if daily_files.has_data(day)]
        print(f"أيام هتتنشأ فولدراتها: {len(days)} ({days[0] if days else '-'} → {days[-1] if days else '-'})؛ "
              f"منها {len(with_data)} فيها بيانات وهتتولّد ملفاتها، والباقي فولدر بس")

    stale = prune_candidates(args.until) if args.prune_empty else []
    if args.prune_empty:
        print(f"يوميات متولّدة لأيام فاضية: {len(stale)} ملف")
        for path in stale[:20]:
            print(f"  {path}")

    if not args.write:
        print("dry-run — أضف --write للتنفيذ.")
        return 0

    store.acquire_process_lock()
    for path in stale:
        path.unlink(missing_ok=True)
    started = time.time()
    failed = 0
    for day in days:
        folder, source, copied, folder_warnings = daily_files.sync_day_folder(day)
        result = daily_files.write_day_files(day, require_data=True)
        bad = {
            kind: row["error"]
            for kind, row in result.files.items()
            if not row["ok"]
        }
        failed += bool(bad)
        if result.skipped == "no_data":
            outcome = "فولدر بس (مفيش بيانات)"
        else:
            outcome = (f"{sum(1 for row in result.files.values() if row['ok'])}/"
                       f"{len(result.files)} ملف")
        warnings = list(folder_warnings) + list(result.warnings)
        print(f"  {day}: {'اتكمّل من ' + str(source) if copied else 'الفولدر كامل'}، {outcome}"
              f"{'، أخطاء: ' + str(bad) if bad else ''}"
              f"{'، تحذيرات: ' + str(len(warnings)) if warnings else ''}")
    print(f"تم في {time.time() - started:.0f} ثانية. أيام فيها أخطاء: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Repair the historical days (up to --until, default 2026-09-29) from the archive.

Why: ~130 days in the system are thinner than the archive (the importer skipped
them because the day already existed, and the campaign/emergency imports were never
applied), so the five dailies exported for those days don't match the archive.

Steps, in order (each one is the existing, tested tool; each keeps a pre-image):
  1. approve the importer's replacements for every day <= --until in
     `data/import/decisions/replace.csv` (days before 30/9 were never edited by hand);
  2. point the batch state at the current archive path (the mount path changed);
  3. importer `store --replace-existing`  -> rebuilds those days from the archive;
  4. import_campaign_daily  (lorries / daily rows / emergency services; the replace drops them);
  5. import_campaign_posts  (checkpoints + plate register);
  6. import_afraad_emergency + fix_emergency_columns  (personnel + the four columns);
  7. link_imported_names    (plain-text names -> people when unambiguous).

Dry-run by default (prints the plan). `--write` needs the system STOPPED (storage lock)
and takes a snapshot first (the importer and every tool also keep a pre-image).

    python3 tools/repair_history.py            # plan only
    python3 tools/repair_history.py --write
"""
from __future__ import annotations

import argparse
import csv
import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import store  # noqa: E402

TOOLS = ["import_campaign_daily", "import_campaign_posts", "import_afraad_emergency",
         "fix_emergency_columns", "link_imported_names"]


def server_is_running() -> bool:
    """True when another process holds the storage lock (the server is up)."""
    path = store.DATA_DIR / ".lock"
    if not path.exists():
        return False
    fd = os.open(path, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except OSError:
        return True
    finally:
        os.close(fd)


def approve_replacements(until: str, write: bool) -> int:
    path = store.DATA_DIR / "import" / "decisions" / "replace.csv"
    rows = list(csv.reader(path.open(encoding="utf-8-sig")))
    todo = [row for row in rows[1:] if row and row[0] <= until and (len(row) < 2 or row[1] != "yes")]
    if write and todo:
        for row in todo:
            row.extend([""] * (3 - len(row)))
            row[1], row[2] = "yes", "اعتماد: إصلاح الأيام التاريخية من الأرشيف"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            csv.writer(handle).writerows(rows)
    return len(todo)


def point_batch_at_archive(archive: Path, write: bool) -> None:
    path = store.DATA_DIR / "import" / "batches" / "archive-full.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    if state["params"].get("archive") != str(archive):
        print(f"  batch archive path: {state['params'].get('archive')} -> {archive}")
        if write:
            state["params"]["archive"] = str(archive)
            path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def run(cmd: list[str]) -> None:
    print("  $", " ".join(cmd), flush=True)
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode:
        raise SystemExit(f"الخطوة فشلت ({result.returncode}) — اتوقف هنا؛ كل خطوة سابقة محفوظة بنسخة قبل التعديل.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--until", default="2026-09-29")
    parser.add_argument("--archive", type=Path, default=ROOT.parent.parent)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    archive = args.archive.resolve()

    if args.write and server_is_running():
        print("السيرفر شغّال على نفس مجلد data/ — اقفله الأول وبعدين شغّل الأمر ده تاني.", file=sys.stderr)
        return 2
    print(f"{'WRITE' if args.write else 'DRY-RUN'} · data={store.DATA_DIR} · until={args.until}")
    print(f"1) days to approve for replacement: {approve_replacements(args.until, args.write)}")
    print("2) batch state")
    point_batch_at_archive(archive, args.write)
    if not args.write:
        # مفيش استدعاء للمستورد هنا: من غير ما مسار الأرشيف يتظبط الأول، بيصفّر حالة الدفعة
        print("3) importer store --replace-existing, then:", ", ".join(TOOLS))
        print("\nplan only — add --write to run every step (stop the server first).")
        return 0

    print(f"snapshot: {store.snapshot_now()}")
    run([sys.executable, "-m", "importer", "store", "--batch", "archive-full",
         "--data-dir", str(store.DATA_DIR), "--replace-existing", "--write", "--i-know"])
    for tool in TOOLS:
        run([sys.executable, f"tools/{tool}.py", "--write"])
    print("\nتم. شغّل السيرفر وافتح أي يوم قديم وقارنه بالأرشيف.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

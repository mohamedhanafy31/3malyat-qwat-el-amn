#!/usr/bin/env python3
"""Infer each officer's «الاسم المختصر» (`short_name`) from how the operators wrote
the officer in the archive's detailed daily logs («<d>.docx», 2026-08-01 onward).

For every cell line of the form «<rank>/ <name>» the written name is matched to an
officer when all its words are words of the officer's full name (tolerating small
spelling differences); the most frequent written form wins. Officers that never
appear (or already have a short_name) are reported; the fallback printed by the
exporters is the first two words of the full name, so nothing breaks.

Dry-run by default (prints a review table). --write sets `short_name` ONLY for
officers that do not have one yet. Needs the system stopped (storage lock).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import docx  # noqa: E402

from backend import store  # noqa: E402
from backend.text import norm_name  # noqa: E402

ARCHIVE = ROOT.parent.parent / "2026"
LINE = re.compile(r"^\s*([^/\\\d]{2,22}?)\s*[/\\]\s*(.+?)\s*$")
STOP = re.compile(r"[+،,(:]|\s-\s|\d")


def cell_lines(path):
    document = docx.Document(path)
    seen = set()
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell._tc in seen:
                    continue
                seen.add(cell._tc)
                for line in cell.text.splitlines():
                    yield " ".join(line.replace("ـ", "").split())


def written_names(path):
    for line in cell_lines(path):
        hit = LINE.match(line)
        if not hit:
            continue
        rank, name = hit[1].strip(), STOP.split(hit[2])[0].strip()
        if rank and name and len(name.split()) <= 4:
            yield rank, name


def tokens(text):
    return [t for t in norm_name(text).split() if len(t) > 1]


def similar(a, b):
    return a == b or SequenceMatcher(None, a, b).ratio() >= 0.86


def contains(full_tokens, wanted):
    return bool(wanted) and all(any(similar(w, f) for f in full_tokens) for w in wanted)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", default="2026-08-01")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    data = store.load_data(store.ALL_DAYS)
    officers = data.get("officers") or []
    index = [(o["id"], tokens(o.get("name", ""))) for o in officers]
    votes = defaultdict(Counter)
    files = 0
    for path in sorted(ARCHIVE.glob("*/*/*.docx")):
        if not re.fullmatch(r"\d{1,2}\.docx", path.name):
            continue
        month, day = int(path.parts[-3]), int(path.parts[-2])
        if f"2026-{month:02d}-{day:02d}" < args.start:
            continue
        files += 1
        for _rank, written in written_names(path):
            wanted = tokens(written)
            if len(wanted) < 2:
                continue
            hits = [oid for oid, full in index if contains(full, wanted)]
            if len(hits) == 1:
                votes[hits[0]][" ".join(written.split())] += 1

    plan, review = {}, []
    for officer in officers:
        oid, current = officer["id"], (officer.get("short_name") or "").strip()
        counter = votes.get(oid)
        proposal = counter.most_common(1)[0][0] if counter else ""
        if not proposal:
            proposal = " ".join(str(officer.get("name", "")).split()[:2])
            source = "fallback"
        else:
            source = f"archive×{counter[proposal]}" + (f" (+{len(counter) - 1} variants)" if len(counter) > 1 else "")
        review.append({"id": oid, "name": officer.get("name", ""), "role": officer.get("role", ""),
                       "current": current, "proposal": proposal, "source": source,
                       "status": officer.get("status", "")})
        if not current:
            plan[oid] = proposal
    print(f"boards read={files} officers={len(officers)} to_set={len(plan)} "
          f"from_archive={sum(1 for r in review if r['source'] != 'fallback')} "
          f"fallback={sum(1 for r in review if r['source'] == 'fallback')}")
    for row in review:
        print(f"  {row['id']} | {row['role'][:14]:14} | {row['name'][:34]:34} -> {row['proposal']}  [{row['source']}]"
              f"{'  (kept: ' + row['current'] + ')' if row['current'] else ''}")
    if args.report:
        args.report.write_text(json.dumps(review, ensure_ascii=False, indent=1), encoding="utf-8")
    if not args.write:
        print("dry-run — أضف --write للتنفيذ.")
        return 0

    store.acquire_process_lock()
    store.snapshot_now()
    for officer in data["officers"]:
        if officer["id"] in plan:
            officer["short_name"] = plan[officer["id"]]
    store.save_data(data)
    print(f"written={len(plan)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

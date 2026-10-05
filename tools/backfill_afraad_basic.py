#!/usr/bin/env python3
"""Add verified afraad_basic sections to existing days without replacing anything else."""
from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import store  # noqa: E402
from importer.apply import assign_ids, remap_day  # noqa: E402
from importer.ledger import Ledger, atomic_write_json  # noqa: E402
from importer.verify import load_target_days, transformed_days  # noqa: E402


def plan(batch):
    ledger = Ledger(store.DATA_DIR, batch)
    existing = load_target_days(store.DATA_DIR)
    source = transformed_days(ledger)
    selected = {day: blob for day, blob in source.items()
                if blob.get("afraad_basic") and not existing.get(day, {}).get("afraad_basic")}

    data = store.load_data(store.ALL_DAYS)
    delta_path = ledger.root / "staging" / ledger.batch / "transform" / "core_delta.json"
    delta = json.loads(delta_path.read_text(encoding="utf-8"))
    id_map = json.loads((ledger.root / "id_map.json").read_text(encoding="utf-8"))
    assigned = assign_ids(copy.deepcopy(data), delta, copy.deepcopy(id_map))
    known = {person["id"] for person in data.get("personnel") or []}
    rows, invalid = {}, []
    for day, blob in sorted(selected.items()):
        entries = remap_day(blob, assigned).get("afraad_basic") or {}
        for entry_id, entry in entries.items():
            for field in ("morning_person_id", "night_person_id"):
                if entry.get(field) and entry[field] not in known:
                    invalid.append({"date": day, "entry": entry_id,
                                    "field": field, "person_id": entry[field]})
                    # Keep the source name/phone, but never persist a dangling
                    # identity link. It can be linked later from the UI.
                    entry.pop(field, None)
        rows[day] = entries
    return data, rows, invalid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="apply the additive backfill")
    parser.add_argument("--batch", default="archive-full",
                        help="verified importer batch containing transformed days")
    args = parser.parse_args()
    data, rows, unlinked = plan(args.batch)
    print(f"days_to_fill={len(rows)} entries={sum(map(len, rows.values()))} "
          f"unlinked_unknown_personnel={len(unlinked)}")
    if not args.write or not rows:
        return 0

    store.acquire_process_lock()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    preimage = store.DATA_DIR / "import" / "preimage" / f"afraad-basic-{stamp}"
    for day in rows:
        source = store.day_path(day)
        target = preimage / "files" / source.relative_to(store.DATA_DIR)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    snapshot = store.snapshot_now()

    for day, entries in rows.items():
        data.setdefault("day_afraad", {})[day] = entries
    store.save_data(data)
    report = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "days": len(rows),
        "entries": sum(map(len, rows.values())),
        "dates": sorted(rows),
        "snapshot": str(snapshot or ""),
        "policy": "add missing afraad_basic only; preserve every existing day section",
        "batch": args.batch,
        "unlinked_unknown_personnel": unlinked,
    }
    atomic_write_json(preimage / "report.json", report)
    print(f"written={len(rows)} preimage={preimage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

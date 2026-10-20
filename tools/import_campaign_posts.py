#!/usr/bin/env python3
"""Seed «مركبات الارتكازات» and «سجل اللوحات» from the archive's
«يومية الحملة عن يوم …» sheets, from --start (default 2026-08-01).

Writes (additively, other campaign sections of the same days are untouched):
  * `reference_lists["campaign_posts"]` — the dated list of checkpoint posts
    (number + archive name + default driver text); a new version starts on the day
    the sheet's list of posts changes (e.g. 2026-08-11);
  * `day_campaign[day]["posts"][post_id]` — vehicle link by plate number plus the
    RAW archive plate/type text and a driver text only when it differs from the
    post's default;
  * `day_campaign[day]["plates"]["rows"]` — the plate register rows at the end of
    the sheet.
Run `migrations/017_seed_campaign.py` first (vehicle registry). Dry-run by default;
--write needs the system stopped and keeps a snapshot + pre-image of the touched day
files. Re-running rebuilds the posts list and the posts/plates of the same days.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import docx  # noqa: E402

from backend import store  # noqa: E402
from backend.repo import VehicleRepo  # noqa: E402
from tools.import_campaign_daily import DIGITS, cells, discover  # noqa: E402

PLATE_NUMBER = re.compile(r"(?<!\d)(\d{4,5})(?!\d)")
SQUASH = re.compile(r"\s+")


def clean(text):
    return SQUASH.sub(" ", str(text or "")).strip()


def sheet_regions(path):
    """-> (post_rows, plate_rows) of one sheet."""
    rows = [cells(r) for r in docx.Document(path).tables[0].rows]
    divider = next((i for i, c in enumerate(rows) if len(c) == 1 and "خطوط" in c[0]), None)
    header = next((i for i, c in enumerate(rows)
                   if c and c[0] in ("م", "م.") and "ارتكازات" in " ".join(c).replace("إ", "ا")), None)
    if divider is None or header is None:
        return [], []
    posts = [c for c in rows[header + 1:divider] if len(c) >= 5 and clean(c[1])]
    plates = []
    for c in rows[divider + 1:]:
        filled = [clean(x) for x in c if clean(x)]
        if len(c) >= 5 and filled and all(PLATE_NUMBER.search(x.translate(DIGITS)) for x in filled):
            plates.append(filled)
    return posts, plates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", default="2026-08-01")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    files = discover(args.start)
    if not files:
        print("لم أجد أي يومية حملة في النطاق.")
        return 1
    data = store.load_data(store.ALL_DAYS)
    if not data.get("vehicles"):
        print("سجل المركبات فاضي — شغّل migrations/017_seed_campaign.py الأول.")
        return 2
    vehicles = {}
    for vehicle in VehicleRepo(data).all():
        vehicles.setdefault(vehicle.plate_number, vehicle.id)

    versions, key_id, first_driver = [], {}, {}
    per_day, unlinked = {}, {}
    previous_keys = None
    for day, path in files.items():
        post_rows, plate_rows = sheet_regions(path)
        keys = [(clean(c[0]), clean(c[1])) for c in post_rows]
        for key, row in zip(keys, post_rows):
            if key not in key_id:
                key_id[key] = store.reserve_id(data, "CP", [{"id": i} for i in key_id.values()])
                first_driver[key] = clean(row[2])
        if keys != previous_keys:
            versions.append({"from": day, "items": [
                {"id": key_id[k], "number": k[0], "name": k[1], "driver_text": first_driver[k]} for k in keys]})
            previous_keys = keys
        entries = {}
        for key, row in zip(keys, post_rows):
            plate_text, type_text, driver = clean(row[3]), clean(row[4]), clean(row[2])
            entry = {}
            number = PLATE_NUMBER.search(plate_text.translate(DIGITS))
            if number and number[1] in vehicles:
                entry["vehicle_id"] = vehicles[number[1]]
            elif number:
                unlinked[number[1]] = unlinked.get(number[1], 0) + 1
            if plate_text:
                entry["plate_text"] = plate_text
            if type_text:
                entry["type_text"] = type_text
            if driver and driver != first_driver[key]:
                entry["driver_text"] = driver
            if entry:
                entries[key_id[key]] = entry
        per_day[day] = {"posts": entries, **({"plates": {"rows": plate_rows}} if plate_rows else {})}

    print(f"days={len(per_day)} range={min(per_day)}..{max(per_day)} versions={len(versions)} "
          f"posts_total={len(key_id)}")
    for version in versions:
        print(f"  from {version['from']}: {[(i['number'], i['name']) for i in version['items']]}")
    print(f"plate rows: {sum(len(d.get('plates', {}).get('rows', [])) for d in per_day.values())} "
          f"(days with a register: {sum(1 for d in per_day.values() if d.get('plates'))})")
    print(f"plates not in the vehicle registry (raw text kept): {unlinked}")
    if args.report:
        args.report.write_text(json.dumps({"versions": versions, "per_day": per_day, "unlinked": unlinked},
                                          ensure_ascii=False, indent=1), encoding="utf-8")
    if not args.write:
        print("dry-run — أضف --write للتنفيذ.")
        return 0

    store.acquire_process_lock()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    preimage = store.DATA_DIR / "import" / "preimage" / f"campaign-posts-{stamp}"
    for day in per_day:
        source = store.day_path(day)
        if source.exists():
            target = preimage / "files" / source.relative_to(store.DATA_DIR)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    snapshot = store.snapshot_now()
    data.setdefault("reference_lists", {})["campaign_posts"] = versions
    for day, section in per_day.items():
        sheet = data.setdefault("day_campaign", {}).setdefault(day, {})
        sheet.pop("posts", None)
        sheet.pop("plates", None)
        sheet.update({k: v for k, v in section.items() if v})
    store.save_data(data)
    preimage.mkdir(parents=True, exist_ok=True)
    (preimage / "report.json").write_text(json.dumps(
        {"at": datetime.now().isoformat(timespec="seconds"), "snapshot": str(snapshot or ""),
         "days": sorted(per_day), "versions": versions, "unlinked": unlinked},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"written={len(per_day)} preimage={preimage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

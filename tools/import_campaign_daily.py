#!/usr/bin/env python3
"""Seat «يومية الحملة» (driver + vehicle per row) from the archive's
«يومية الحملة عن يوم …» .docx files, from --start (default 2026-08-01) to the
latest file.

Per day it reads the «خطوط سير توصيل» table and maps each row to:
  * one of the 4 base lorries (المحور + المحكمة / القنصلية / فيصل / كـ109);
    extra parts after «+» («+ تفتيش فيصل») become attached services;
  * a fixed «الأقوال اليومية» row (التدخل السريع ×2، خط الغاز، القول المكبر،
    ارتكاز الاسعاف، سائق بورتوفيق، قول السلام) — the dated list is rebuilt from
    which of them each day's sheet actually has;
  * otherwise an emergency/custom service of that day's detailed log (matched
    by name; «a + b» rows seat both).
Vehicles are linked by plate number to the vehicle registry (run migration 017
first); drivers are linked to the personnel drivers / conscript drivers only when
the name matches exactly one of them, otherwise kept as typed text.
Nothing is invented: rows/plates/names that can't be matched are reported.

Dry-run by default; --write needs the system stopped, and keeps a snapshot and a
pre-image of the touched day files. Re-running replaces the campaign section of
the same days.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import docx  # noqa: E402

from backend import fleet, store  # noqa: E402
from backend.afraad import occasional_rows  # noqa: E402
from backend.campaign import campaign_daily_on  # noqa: E402
from backend.constants import CAMPAIGN_LORRIES  # noqa: E402
from backend.dated import record_campaign_daily_change  # noqa: E402
from backend.repo import VehicleRepo  # noqa: E402
from backend.text import norm, norm_name  # noqa: E402

ARCHIVE = ROOT.parent.parent / "2026"
DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
TIME = re.compile(r"\d{1,2}\s*(?:[صظملح]+)")
QUOTED = re.compile(r'["“”].*?["“”]')
PLATE_NUMBER = re.compile(r"(?<!\d)(\d{4,5})(?!\d)")
LORRY_WORDS = {"المحور": "LOR-1", "الافطار": "LOR-1", "المحكمه": "LOR-1"}
BASE_PARTS = {"المحور", "المحكمه", "الافطار"}
DAILY_NAMES = [("التدخل السريع", "التدخل السريع"), ("خط الغاز", "خط الغاز"),
               ("قول مكبر", "القول المكبر"), ("القول المكبر", "القول المكبر"),
               ("ارتكاز الاسعاف", "ارتكاز الاسعاف"), ("بورتوفيق", "سائق بورتوفيق"),
               ("قول السلام", "قول السلام")]
RANKS = re.compile(r"^(?:م\s*\.?\s*ش|ا\s*\.?\s*ش|اش|مش|رقيب|مندوب|عريف|شرطي)\s*[/\\]?\s*")


def cells(row):
    seen, out = set(), []
    for cell in row.cells:
        if cell._tc not in seen:
            seen.add(cell._tc)
            out.append(" ".join(cell.text.replace("ـ", "").split()))
    return out


def sheet_day(path: Path):
    hit = re.search(r"(\d{1,2})-(\d{1,2})-(20\d\d)", path.name.translate(DIGITS))
    return f"{hit[3]}-{int(hit[2]):02d}-{int(hit[1]):02d}" if hit else None


def discover(start):
    chosen = {}
    for path in sorted(ARCHIVE.glob("*/*/يومية الحملة عن يوم*.docx")):
        if path.name.startswith("~$") or "ارتكازات" in path.name:
            continue
        day = sheet_day(path)
        if not day or day < start:
            continue
        # نسخة اليوم الصح: اللي مجلدها هو رقم اليوم
        if day not in chosen or path.parent.name == str(int(day[8:])):
            chosen[day] = path
    return dict(sorted(chosen.items()))


# ───────────── reading a sheet ─────────────
def sheet_rows(path):
    table = docx.Document(path).tables[0]
    rows, on = [], False
    for row in table.rows:
        parts = cells(row)
        if len(parts) == 1 and "خطوط" in parts[0]:
            on = True
            continue
        if not on or len(parts) < 3 or parts[1] in ("الخدمة", ""):
            continue
        if re.fullmatch(r"ب?\s*\d*\s*/?\s*\d{3,5}", parts[1].translate(DIGITS)):
            continue  # صف لوحات في آخر الجدول
        driver, plate = (parts[2], parts[3]) if len(parts) >= 5 else (parts[2], "")
        rows.append({"name": parts[1], "driver": driver, "plate": plate})
    return rows


def plate_number(text):
    hit = PLATE_NUMBER.search(str(text or "").translate(DIGITS))
    return hit[1] if hit else None


def split_parts(text):
    """«فيصل + تفتيش فيصل» -> ["فيصل", "تفتيش فيصل"] (من غير ميعاد ولا جهة).
    التقسيم على «+» قبل التطبيع لأن التطبيع بيشيل العلامة."""
    text = TIME.sub(" ", QUOTED.sub(" ", text))
    parts = [re.sub(r"\bامن وطني\b", "الامن الوطني", " ".join(norm(p).split()))
             for p in text.split("+")]
    return [p for p in parts if p]


# ───────────── matching ─────────────
def service_score(a, b):
    left, right = set(norm(a).split()), set(norm(b).split())
    if not left or not right:
        return 0.0
    seq = SequenceMatcher(None, norm(a), norm(b)).ratio()
    contain = len(left & right) / min(len(left), len(right))
    smaller = min(left, right, key=len)
    if len(smaller) >= 2:
        return max(seq, 0.95 * contain)
    # كلمة واحدة طويلة («عسكرية»، «العاشر») بتكفي لو هي جزء من اسم الخدمة
    if len(smaller) == 1 and len(next(iter(smaller))) >= 5:
        return max(seq, 0.82 * contain)
    return seq


def classify(name):
    """-> ("lorry", "LOR-n") | ("daily", canonical) | ("service", None)."""
    flat = norm(name)
    first = split_parts(name)[0] if split_parts(name) else flat
    if any(word in flat.split() or word in first for word in BASE_PARTS) or "الافطار" in flat:
        return "lorry", "LOR-1"
    if first.startswith("القنصليه"):
        return "lorry", "LOR-2"
    if first.startswith("فيصل"):
        return "lorry", "LOR-3"
    if re.match(r"^ك\s*109|^كمين\s*109", first):
        return "lorry", "LOR-4"
    for key, canonical in DAILY_NAMES:
        if first.startswith(norm(key)) or (key == "بورتوفيق" and key in first):
            return "daily", canonical
    return "service", None


def attached_parts(name, lorry_id):
    parts = split_parts(name)
    out = []
    for part in parts:
        words = set(part.split())
        if lorry_id == "LOR-1" and (words & BASE_PARTS or part in ("المحور", "الافطار")):
            continue
        if lorry_id == "LOR-2" and part.startswith("القنصليه"):
            continue
        if lorry_id == "LOR-3" and part == "فيصل":
            continue
        if lorry_id == "LOR-4" and re.match(r"^(ك\s*109|كمين\s*109)$", part):
            continue
        out.append(part)
    return out


def shift_hint(name):
    text = name.translate(DIGITS)
    if re.search(r"1[02]\s*[لم]", text) or "ليل" in text:
        return "ليلية"
    if re.search(r"\d\s*ص|1[02]\s*ظ|صباح", text):
        return "صباحية"
    return None


def match_service(part, log_rows, used, hint=None):
    ranked = sorted(((service_score(part, r["name"]), i) for i, r in enumerate(log_rows)),
                    reverse=True)
    if not ranked or ranked[0][0] < 0.8:
        return None
    best = [i for s, i in ranked if s >= ranked[0][0] - 0.02]
    pool = [i for i in best if i not in used] or []
    if hint:
        pool = [i for i in pool if log_rows[i].get("shift") == hint] or pool
    return pool[0] if pool else None


class Resolver:
    def __init__(self, data):
        self.vehicles = {}
        for vehicle in VehicleRepo(data).all():
            self.vehicles.setdefault(vehicle.plate_number, vehicle.id)
        self.data = data

    def vehicle(self, text):
        number = plate_number(text)
        return (self.vehicles.get(number), number)

    def driver(self, day, text, pools):
        text = " ".join(str(text or "").split())
        if not text or re.fullmatch(r"[ـ\-–—_.\s]*", text):
            return None
        wanted = norm_name(RANKS.sub("", text)).split()
        if not wanted:
            return None
        hits = []
        for kind, items in pools:
            for item in items:
                have = norm_name(item["name"]).split()
                if len(have) >= len(wanted) and all(
                        SequenceMatcher(None, w, h).ratio() >= 0.85 for w, h in zip(wanted, have)):
                    hits.append({"kind": kind, "id": item["id"]})
        if len(hits) == 1 and len(wanted) >= 2:
            return hits[0]
        return {"kind": "text", "name": text}


# ───────────── one day ─────────────
def build_day(data, day, path, resolver, report):
    log = [r for r in occasional_rows(data, day)]
    drivers = fleet.drivers_on(data, day)
    pools = [("personnel", drivers["personnel"]), ("conscript", drivers["conscripts"])]
    lorries, services, daily_rows = {}, {}, []
    used = set()
    daily_seen = Counter()

    def seat(target, row):
        vehicle_id, number = resolver.vehicle(row["plate"])
        if number and not vehicle_id:
            report["missing_plates"][number] += 1
        if vehicle_id:
            target["vehicle_id"] = vehicle_id
        driver = resolver.driver(day, row["driver"], pools)
        if driver:
            target["driver"] = driver
            report["drivers_linked" if driver["kind"] != "text" else "drivers_text"] += 1

    for row in sheet_rows(path):
        if not plate_number(row["plate"]) and not row["driver"].strip():
            continue  # صف من غير سائق ولا مركبة — مفيش حاجة تتسكّن
        kind, key = classify(row["name"])
        if kind == "lorry":
            target = lorries.setdefault(key, {})
            seat(target, row)
            for part in attached_parts(row["name"], key):
                index = match_service(part, log, used)
                if index is not None:
                    used.add(index)
                    target.setdefault("attached", []).append({"assignment_id": log[index]["id"]})
                else:
                    target.setdefault("attached", []).append({"name": part})
        elif kind == "daily":
            daily_seen[key] += 1
            entry = {}
            seat(entry, row)
            daily_rows.append((key, daily_seen[key], entry))
        else:
            matched = False
            for part in split_parts(row["name"]):
                index = match_service(part, log, used, shift_hint(row["name"]))
                if index is None:
                    continue
                used.add(index)
                entry = {}
                seat(entry, row)
                services[log[index]["id"]] = entry
                matched = True
            if not matched:
                report["unmatched_rows"].append({"day": day, "row": row["name"]})
    return {"lorries": lorries, "services": services}, daily_rows


def reconcile_daily_rows(data, day, desired_names):
    """Make the dated «الأقوال اليومية» list match what the sheet shows (ids stay
    stable by name); returns the id list in sheet order."""
    items = campaign_daily_on(data, day)
    pool = {}
    for item in items:
        pool.setdefault(item["name"], []).append(item["id"])
    known = {i["id"]: i["name"] for versions in
             (data.get("reference_lists") or {}).get("campaign_daily") or []
             for i in versions.get("items") or []}
    by_name = {}
    for ident, name in known.items():
        by_name.setdefault(name, []).append(ident)
    chosen, taken = [], set()
    for name in desired_names:
        ids = [i for i in pool.get(name, []) if i not in taken] \
            or [i for i in by_name.get(name, []) if i not in taken]
        if ids:
            ident = ids[0]
        else:
            ident = store.reserve_id(data, "CD", [{"id": i} for i in known])
            known[ident] = name
            by_name.setdefault(name, []).append(ident)
        taken.add(ident)
        chosen.append((ident, name))
    current = [(i["id"], i["name"]) for i in items]
    if current != chosen:
        record_campaign_daily_change(data, day, [{"id": i, "name": n} for i, n in chosen])
    return [i for i, _ in chosen]


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
    resolver = Resolver(data)
    report = {"missing_plates": Counter(), "unmatched_rows": [], "drivers_linked": 0, "drivers_text": 0}
    plan = {}
    for day, path in files.items():
        section, daily_rows = build_day(data, day, path, resolver, report)
        ids = reconcile_daily_rows(data, day, [name for name, _n, _e in daily_rows])
        section["daily"] = {ident: entry for ident, (_n, _k, entry) in zip(ids, daily_rows) if entry}
        for key in ("lorries", "services", "daily"):
            section[key] = {k: v for k, v in section[key].items() if v}
        plan[day] = {k: v for k, v in section.items() if v}

    print(f"days={len(files)} range={min(files)}..{max(files)} "
          f"lorry_rows={sum(len(p.get('lorries', {})) for p in plan.values())} "
          f"service_rows={sum(len(p.get('services', {})) for p in plan.values())} "
          f"daily_rows={sum(len(p.get('daily', {})) for p in plan.values())}")
    print(f"drivers: linked={report['drivers_linked']} text={report['drivers_text']}")
    print(f"missing plates (not in registry): {dict(report['missing_plates'].most_common(20))}")
    print(f"unmatched rows: {len(report['unmatched_rows'])}")
    for name, count in Counter(r["row"] for r in report["unmatched_rows"]).most_common(25):
        print(f"   {count}× {name}")
    if args.report:
        args.report.write_text(json.dumps({"plan": plan, "missing_plates": report["missing_plates"],
                                           "unmatched": report["unmatched_rows"]},
                                          ensure_ascii=False, indent=1), encoding="utf-8")
    if not args.write:
        print("dry-run — أضف --write للتنفيذ.")
        return 0

    store.acquire_process_lock()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    preimage = store.DATA_DIR / "import" / "preimage" / f"campaign-daily-{stamp}"
    for day in plan:
        source = store.day_path(day)
        if source.exists():
            target = preimage / "files" / source.relative_to(store.DATA_DIR)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    snapshot = store.snapshot_now()
    for day, section in plan.items():
        data.setdefault("day_campaign", {})[day] = section
    store.save_data(data)
    preimage.mkdir(parents=True, exist_ok=True)
    (preimage / "report.json").write_text(json.dumps(
        {"at": datetime.now().isoformat(timespec="seconds"), "snapshot": str(snapshot or ""),
         "days": sorted(plan), "missing_plates": report["missing_plates"],
         "unmatched": report["unmatched_rows"]}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"written={len(plan)} preimage={preimage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Seat the *personnel* (أفراد) listed under «الخدمات الطارئة» in the daily
«افراد» .docx into the detailed daily log (`day_assignments`).

For every roster from --start (default 2026-08-01) to the latest one found:
  * each emergency row (service + القائم بها) is read; officers (مقدم/رائد/نقيب/
    ملازم/…) and empty «ـــــ» cells are skipped — personnel only;
  * the service is matched by name to the day's emergency/custom rows in the
    detailed log and the person is *added* to `personnel_ids` (nothing existing
    is removed or replaced);
  * if no row matches, a new emergency row is created from the sheet
    (count/weapon/time) — disable with --no-create.

Dry-run by default; --write needs the system stopped (storage lock) and keeps a
snapshot + pre-image of the touched day files.
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
from backend.afraad_ocr import _person_match, _service_score  # noqa: E402
from backend.assignments import blank, new_id, peek_day  # noqa: E402
from backend.board import ASSIGNMENT_SECTIONS  # noqa: E402
from backend.constants import SECTION_OCCASIONAL  # noqa: E402
from backend.repo import PeopleRepo  # noqa: E402
from backend.text import norm  # noqa: E402
from tools.import_afraad_rosters import (  # noqa: E402
    DEFAULT_ROOT, DIGITS, PHONE, PLACEHOLDER, clean, discover, unique_cells,
)

OFFICER_RANKS = ("مقدم", "رائد", "نقيب", "ملازم", "عقيد", "عميد", "لواء", "ملازم اول", "م اول")
MATCH_MIN = 0.72


def is_officer_text(text: str) -> bool:
    rank = norm(re.split(r"[/\\]", text, maxsplit=1)[0]) if re.search(r"[/\\]", text) else ""
    return any(rank == norm(r) or rank.startswith(norm(r) + " ") for r in OFFICER_RANKS)


def emergency_rows(document):
    """[{service, leader, count, weapon, time}] after «الخدمات الطارئة»."""
    for table in document.tables:
        header = next((i for i, row in enumerate(table.rows)
                       if "الخدمه الصباحيه" in norm(" ".join(unique_cells(row)))), None)
        if header is None:
            continue
        rows, on = [], False
        for row in table.rows[header + 1:]:
            cells = unique_cells(row)
            if "الخدمات الطاريه" in norm(" ".join(cells)):
                on = True
                continue
            filled = [c for c in cells if c.strip()]
            if not on or len(filled) < 2:
                continue
            if len(cells) >= 5:
                # القوام/التسليح/الانتظام دايمًا آخر ثلاث خلايا؛ لو القائم بها اتنين
                # (خلية زيادة) ياخدوا كل اللي بين اسم الخدمة وآخر ثلاث خلايا.
                leader = "\n".join(cells[1:-3])
                count, weapon, time = cells[-3], cells[-2], cells[-1]
            else:
                leader, count, weapon, time = (cells + [""] * 5)[1:5]
            rows.append({"service": clean(cells[0]), "leader": leader, "count": clean(count),
                         "weapon": clean(weapon),
                         # الاقتباس «"عتاقة"» هو الجهة — ما ينفعش يتشال هنا
                         "time": " ".join(time.split())})
        return rows
    return []


def leaders(text):
    """Person lines of a leader cell (a cell may hold several people)."""
    out = []
    for line in str(text or "").translate(DIGITS).splitlines():
        line = clean(line)
        if line and not PLACEHOLDER.match(line) and re.search(r"[؀-ۿ]", line):
            out.append(line)
    return out


def find_person(line, personnel):
    phone = re.sub(r"\D", "", (PHONE.search(line) or [""])[0])
    by_phone = [p for p in personnel if len(phone) >= 10 and
                re.sub(r"\D", "", p.get("phone") or "").endswith(phone[-10:])]
    if len(by_phone) == 1:
        return by_phone[0], None
    match = _person_match(line, personnel)
    if match.get("matched"):
        return next(p for p in personnel if p["id"] == match["id"]), None
    return None, match


def candidates(rows, service):
    scored = sorted(((_service_score(service, r.get("name", "")), i) for i, r in enumerate(rows)),
                    reverse=True)
    if not scored or scored[0][0] < MATCH_MIN:
        return []
    return [i for s, i in scored if s >= max(MATCH_MIN, scored[0][0] - 0.02)]


def plan_day(data, day, path, create):
    personnel = [p.as_dict() for p in PeopleRepo(data).on_force(day, "personnel")]
    log = [a for a in peek_day(data, day)
           if (a.get("section") or SECTION_OCCASIONAL) == SECTION_OCCASIONAL
           or (a.get("section") not in ASSIGNMENT_SECTIONS)]
    actions, notes = [], []
    claimed = set()
    for row in emergency_rows(docx.Document(path)):
        for line in leaders(row["leader"]):
            if is_officer_text(line):
                notes.append(("ضابط — تخطي", row["service"], line))
                continue
            person, miss = find_person(line, personnel)
            if person is None:
                notes.append(("فرد غير محدد", row["service"], line))
                continue
            idx = candidates(log, row["service"])
            if idx and any(person["id"] in (log[i].get("personnel_ids") or []) for i in idx):
                continue  # already seated
            target = next((i for i in idx if not (log[i].get("personnel_ids") or [])
                           and (day, i) not in claimed), None)
            if target is not None:
                claimed.add((day, target))
                actions.append({"op": "add", "id": log[target]["id"], "service": log[target]["name"],
                                "person": person["id"], "who": person["name"]})
            elif idx:
                notes.append(("الخانة مشغولة بفرد آخر", row["service"], line))
            elif create:
                actions.append({"op": "create", "service": row["service"], "person": person["id"],
                                "who": person["name"], "count": row["count"],
                                "weapon": row["weapon"], "time": row["time"]})
            else:
                notes.append(("لا توجد خانة", row["service"], line))
    return actions, notes


def apply_day(data, day, actions):
    rows = data.setdefault("day_assignments", {}).setdefault(day, [])
    for act in actions:
        if act["op"] == "add":
            row = next(r for r in rows if r.get("id") == act["id"])
            row.setdefault("personnel_ids", []).append(act["person"])
            continue
        count = re.search(r"\d+", act["count"].translate(DIGITS))
        quoted = re.search(r'["“](.+?)["”]', act["time"])
        time = re.sub(r'["“].+?["”]', "", act["time"]).strip()
        name = re.sub(r"\s+\d+\s*(ص|ظ|م)$", "", act["service"]).strip()
        night = bool(re.match(r"^\d+\s*م", time.translate(DIGITS)))
        rows.append(blank(new_id(data, day, rows), name, SECTION_OCCASIONAL,
                          kind="خارجية", shift="ليلية" if night else "صباحية",
                          personnel_ids=[act["person"]], weapon=act["weapon"], time=time,
                          party=quoted[1].strip() if quoted else "",
                          conscripts=[{"class": "مج", "count": int(count[0])}] if count else [],
                          conscript_count=int(count[0]) if count else 0))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--start", default="2026-08-01")
    parser.add_argument("--end", default=None)
    parser.add_argument("--no-create", action="store_true", help="لا تنشئ خانات ناقصة")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    files, notes = discover(args.root, args.start, args.end)
    if not files:
        print("لم أجد أي يومية أفراد في النطاق.")
        return 1
    data = store.load_data(store.ALL_DAYS)
    plan, report = {}, {}
    for day, path in files.items():
        if day not in (data.get("day_assignments") or {}) and not store.day_path(day).exists():
            print(f"{day}: لا يوجد ملف يومية تفصيلية — تخطي")
            continue
        actions, skipped = plan_day(data, day, path, not args.no_create)
        report[day] = {"file": str(path), "actions": actions, "skipped": skipped}
        if actions:
            plan[day] = actions
    adds = sum(a["op"] == "add" for v in plan.values() for a in v)
    news = sum(a["op"] == "create" for v in plan.values() for a in v)
    print(f"days={len(report)} days_to_change={len(plan)} seat_in_existing={adds} new_rows={news}")
    for day, info in report.items():
        print(f"{day} +{sum(a['op']=='add' for a in info['actions'])} "
              f"new={sum(a['op']=='create' for a in info['actions'])} "
              f"skipped={len(info['skipped'])}")
    for note in notes:
        print("note:", note)
    if args.report:
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print("report:", args.report)
    if not args.write:
        print("dry-run — أضف --write للتنفيذ.")
        return 0

    store.acquire_process_lock()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    preimage = store.DATA_DIR / "import" / "preimage" / f"afraad-emergency-{stamp}"
    for day in plan:
        source = store.day_path(day)
        if source.exists():
            target = preimage / "files" / source.relative_to(store.DATA_DIR)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    snapshot = store.snapshot_now()
    for day, actions in plan.items():
        apply_day(data, day, actions)
    store.save_data(data)
    preimage.mkdir(parents=True, exist_ok=True)
    (preimage / "report.json").write_text(json.dumps(
        {"at": datetime.now().isoformat(timespec="seconds"), "snapshot": str(snapshot or ""),
         "days": report}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"written={len(plan)} preimage={preimage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

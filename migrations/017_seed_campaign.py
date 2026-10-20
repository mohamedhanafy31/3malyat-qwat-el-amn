#!/usr/bin/env python3
"""بذر وحدة «الحملة»: سجل المركبات + سجل المجندين السواقين + «الأقوال اليومية».

البيانات من `017_campaign_seed.json` (مولَّد بـ`tools/build_campaign_seed.py` من
ملف «اضافات» في الأرشيف). المجندين أسماء فقط — مفيش دفعة ولا رديف ولا أي بيانات.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import AlreadyDone, run  # noqa: E402
from backend.store import reserve_id  # noqa: E402

SEED = Path(__file__).with_name("017_campaign_seed.json")
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def earliest_day(data):
    found = []
    for value in data.values():
        if isinstance(value, dict):
            found.extend(key for key in value if DAY.match(str(key)))
    if found:
        return min(found)
    joins = [p.get("join_date") for cat in ("officers", "personnel")
             for p in (data.get(cat) or []) if DAY.match(str(p.get("join_date") or ""))]
    return min(joins) if joins else "1970-01-01"


def migrate(data):
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    refs = data.setdefault("reference_lists", {})
    if data.get("vehicles") or data.get("conscripts") or refs.get("campaign_daily"):
        raise AlreadyDone("بيانات الحملة موجودة بالفعل.")
    vehicles, conscripts = data.setdefault("vehicles", []), data.setdefault("conscripts", [])
    for item in seed["vehicles"]:
        vehicles.append({"id": reserve_id(data, "VEH", vehicles), **item})
    for item in seed["conscripts"]:
        conscripts.append({"id": reserve_id(data, "CON", conscripts), **item})
    start = earliest_day(data)
    refs["campaign_daily"] = [{"from": start, "items": [
        {"id": f"CD-{index:03d}", "name": name} for index, name in enumerate(seed["campaign_daily"], 1)]}]
    report = seed.get("report") or {}
    lines = [f"سُجّلت {len(vehicles)} مركبة و{len(conscripts)} مجند سواق و{len(seed['campaign_daily'])} قول يومي."]
    for item in report.get("conflicts", []):
        lines.append(f"تعارض نوع: {item['plate']} في الإضافات «{item['addendum']}» وفي اليوميات «{item['daily']}».")
    unlisted = report.get("unlisted_plates_seen_in_daily") or []
    if unlisted:
        shown = "، ".join(f"{u['plate_number']} ({u['type']}، {u['days']} يوم)" for u in unlisted[:8])
        lines.append(f"{len(unlisted)} لوحة ظهرت في اليوميات ومش في الإضافات (ما اتضافتش): {shown} …")
    return lines


if __name__ == "__main__":
    run(from_schema=6, to_schema=6, migrate=migrate, title="بذر وحدة الحملة")

#!/usr/bin/env python3
"""تحويل مركبة خدمة الحملة المفردة إلى قايمة مركبات مرتبة."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import AlreadyDone, run  # noqa: E402


def _assignment_people(data, day, assignment_id):
    row = next((item for item in (data.get("day_assignments") or {}).get(day, [])
                if item.get("id") == assignment_id), {})
    return {"personnel_ids": list(dict.fromkeys(row.get("personnel_ids") or [])),
            "officer_ids": list(dict.fromkeys(row.get("officer_ids") or []))}


def migrate(data):
    marker = "021_campaign_vehicles"
    if marker in data.setdefault("_migrations", []):
        raise AlreadyDone("هجرة مركبات خدمات الحملة اتعملت قبل كده.")
    converted = 0
    for day, sheet in (data.get("day_campaign") or {}).items():
        for assignment_id, entry in ((sheet or {}).get("services") or {}).items():
            if not isinstance(entry, dict) or not entry.get("vehicle_id"):
                continue
            people = _assignment_people(data, day, assignment_id)
            entry["vehicles"] = [{"vehicle_id": entry["vehicle_id"], **people}]
            entry.pop("vehicle_id", None)
            converted += 1
    data["_migrations"].append(marker)
    return [f"حوّلت {converted} خدمة من مركبة مفردة إلى vehicles."]


if __name__ == "__main__":
    run(from_schema=6, to_schema=6, migrate=migrate, title="تعدد مركبات خدمات الحملة")

#!/usr/bin/env python3
"""ربط تعريف الإسعاف في الأفراد بصفّه اليومي في الحملة."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import AlreadyDone, run  # noqa: E402
from backend.afraad import BASIC_SERVICES  # noqa: E402
from backend.text import norm  # noqa: E402


COUNT_RE = re.compile(r"\((\d+)\s*مجند\)")


def _basic_index(data):
    by_name = {}
    for item in BASIC_SERVICES:
        by_name.setdefault(norm(item["name"]), set()).add(item["id"])
    for version in ((data.get("reference_lists") or {}).get("afraad_basic") or []):
        for item in version.get("items") or []:
            if isinstance(item, dict) and item.get("id") and item.get("name"):
                by_name.setdefault(norm(item["name"]), set()).add(item["id"])
    return by_name


def _ambulance_ids(data):
    return {ident for name, ids in _basic_index(data).items() if name == norm("الإسعاف") for ident in ids}


def migrate(data):
    marker = "020_link_ambulance"
    if marker in data.setdefault("_migrations", []):
        raise AlreadyDone("هجرة ربط الإسعاف اتعملت قبل كده.")

    basics = data.setdefault("reference_lists", {}).setdefault("afraad_basic", [])
    index = _basic_index(data)
    ambulance_ids = _ambulance_ids(data)
    reports = []
    changed_defs = 0
    for version in basics:
        for item in version.get("items") or []:
            if item.get("id") not in ambulance_ids:
                continue
            if not item.get("location_text"):
                item["location_text"] = "الحماية المدنية"
                changed_defs += 1
            if item.get("conscript_count") is None:
                texts = [str(value) for value in item.values() if isinstance(value, str)]
                for day_values in (data.get("day_afraad") or {}).values():
                    override = day_values.get(item["id"], {}) if isinstance(day_values, dict) else {}
                    texts.extend(str(value) for value in override.values() if isinstance(value, str))
                found = {int(match) for text in texts for match in COUNT_RE.findall(text)}
                if len(found) == 1:
                    item["conscript_count"] = found.pop()
                    changed_defs += 1

    linked = 0
    for version in ((data.get("reference_lists") or {}).get("campaign_daily") or []):
        for item in version.get("items") or []:
            if item.get("basic_entry_id"):
                continue
            wanted = norm(item.get("name"))
            matches = index.get(wanted, set()) or index.get(norm(str(item.get("name") or "").removeprefix("ارتكاز ")), set())
            if len(matches) == 1:
                item["basic_entry_id"] = next(iter(matches))
                linked += 1

    data["_migrations"].append(marker)
    reports.append(f"تحديث {changed_defs} قيمة في تعريف الإسعاف.")
    reports.append(f"ربط {linked} صفًا يوميًا بمعرّف خدمة أساسية.")
    return reports


if __name__ == "__main__":
    run(from_schema=6, to_schema=6, migrate=migrate, title="ربط الإسعاف بين الأفراد والحملة")

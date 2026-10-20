#!/usr/bin/env python3
"""ربط يومية الاعداد والقوائم المؤرخة بدليل الخدمات وخطوط السير."""
import csv
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import AlreadyDone, run  # noqa: E402
from backend.clocktime import parse_shift_pair  # noqa: E402
from backend.constants import CAMPAIGN_LORRIES  # noqa: E402
from backend.service_catalog import catalog, new_id  # noqa: E402
from backend.service_links import resolve_service_id, service_for_counts_entry  # noqa: E402


RUN_DAY = date.today().isoformat()
unmatched_rows = []


def _link(data, source, ident, name, rows):
    service_id = resolve_service_id(data, name)
    if service_id is None:
        rows.append({"source": source, "id": ident, "name": str(name or "")})
    return service_id


def _latest(items):
    return max(items or [], key=lambda item: item.get("from") or "") if items else None


def _add_catalog_entries(data):
    entries = catalog(data)
    wanted = [
        ("قول الكورنيش", 1, "آلي", "", ""),
        ("حملة الأمن الوطني", 4, "آلي", "12:00", ""),
    ]
    added = 0
    for name, count, weapon, report_am, report_pm in wanted:
        if any(resolve_service_id({"service_catalog": entries}, name) == e.get("id")
               for e in entries):
            continue
        entries.append({"id": new_id(data), "name": name, "period": "صباحية بس", "kind": "",
                        "post_type": "قول", "has_command": False, "command_officers": 0,
                        "command_individuals": 0, "count": count, "weapon": weapon,
                        "instructions": "", "location_text": "", "location_images": [],
                        "tags": [], "report_am": report_am, "report_pm": report_pm,
                        "order": len(entries)})
        added += 1
    return added


def _merge_tags(data):
    changed = 0
    for entry in catalog(data):
        tags = entry.get("tags") or []
        if "الدخلي" in tags:
            entry["tags"] = ["الداخلي" if tag == "الدخلي" else tag for tag in tags]
            changed += 1
    tags = data.setdefault("service_tags", [])
    if "الدخلي" in tags:
        data["service_tags"] = ["الداخلي" if tag == "الدخلي" else tag for tag in tags]
        changed += 1
    return changed


def _seed_lines(data):
    lines = data.setdefault("service_lines", [])
    if lines:
        return 0
    seed = [("خط فيصل", "فيصل", "LOR-3"), ("خط الخارجي (كـ109)", "الخارجي", "LOR-4"),
            ("خط المحور والمحكمة", "المحكمة والمحور", "LOR-1"),
            ("خط الداخلي (القنصلية)", "الداخلي", "LOR-2")]
    lines.extend({"id": f"LN-{i}", "name": name, "tag": tag, "lorry_id": lorry,
                  "order": [], "depart_am": "", "depart_pm": ""}
                 for i, (name, tag, lorry) in enumerate(seed, 1))
    return len(seed)


def migrate(data):
    global unmatched_rows
    if "018_link_services" in data.setdefault("_migrations", []):
        raise AlreadyDone("هجرة ربط الخدمات اتعملت قبل كده.")
    unmatched_rows = []
    added = _add_catalog_entries(data)
    merged = _merge_tags(data)
    seeded = _seed_lines(data)
    linked = 0

    template = (data.get("counts_template") or {}).get("entries") or []
    for entry in template:
        service_id = _link(data, "counts_template", entry.get("id"), entry.get("name"), unmatched_rows)
        if service_id:
            entry["service_id"] = service_id
            linked += 1
    for day, sheet in (data.get("service_counts") or {}).items():
        if str(day) < RUN_DAY:
            continue
        for entry in (sheet or {}).get("entries") or []:
            service_id = _link(data, f"service_counts[{day}]", entry.get("id"),
                               entry.get("name"), unmatched_rows)
            if service_id:
                entry["service_id"] = service_id
                linked += 1

    refs = data.setdefault("reference_lists", {})
    ref_links = {}
    for key in ("afraad_basic", "campaign_daily"):
        row = _latest(refs.get(key) or [])
        for item in (row or {}).get("items") or []:
            service_id = _link(data, key, item.get("id"), item.get("name"), unmatched_rows)
            if service_id:
                item["service_id"] = service_id
                ref_links[item.get("id")] = service_id
                linked += 1

    by_id = {entry.get("id"): entry for entry in catalog(data)}
    filled = 0
    for day in sorted((data.get("day_afraad") or {}), reverse=True):
        for item_id, value in ((data.get("day_afraad") or {}).get(day) or {}).items():
            service_id = ref_links.get(item_id)
            if not service_id or service_id not in by_id or not isinstance(value, dict):
                continue
            am, pm = parse_shift_pair(value.get("schedule"))
            target = by_id[service_id]
            if not target.get("report_am") and am:
                target["report_am"] = am
                filled += 1
            if not target.get("report_pm") and pm:
                target["report_pm"] = pm
                filled += 1
    data["_migrations"].append("018_link_services")
    return [f"أضيفت {added} خدمة، واتدمج {merged} وسم، واتزرعت {seeded} خطوط سير.",
            f"اتربط {linked} صف، واتملت {filled} مواعيد، والصافي {len(unmatched_rows)} اسم."]


def _write_report():
    path = Path(__file__).resolve().parent.parent / "reports" / "service-links-unmatched.csv"
    path.parent.mkdir(exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["source", "id", "name"])
        writer.writeheader()
        writer.writerows(unmatched_rows)
    print(f"اتكتب تقرير الأسماء غير المربوطة: {path} ({len(unmatched_rows)}).")


if __name__ == "__main__":
    run(from_schema=6, to_schema=6, migrate=migrate, title="ربط الخدمات وخطوط السير")
    if "--write" in sys.argv:
        _write_report()

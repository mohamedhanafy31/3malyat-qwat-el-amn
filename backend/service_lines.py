"""خطوط السير — عضوية الخط تُستنتج من وسم الخدمة وقت القراءة."""
from .constants import CAMPAIGN_LORRIES
from .service_catalog import catalog


def lines(data):
    return data.setdefault("service_lines", [])


def _members(data, line):
    entries = [e for e in catalog(data) if line.get("tag") in (e.get("tags") or [])]
    by_id = {e.get("id"): e for e in entries}
    ordered = [by_id[i] for i in line.get("order") or [] if i in by_id]
    listed = {e.get("id") for e in ordered}
    ordered.extend(e for e in catalog(data) if e in entries and e.get("id") not in listed)
    return ordered


def line_for_service(data, svc_id):
    return next((line for line in lines(data) if any(e.get("id") == svc_id
                                                     for e in _members(data, line))), None)


def members(data, line_id):
    line = next((line for line in lines(data) if line.get("id") == line_id), None)
    return _members(data, line) if line else []


def lorry_name(lorry_id):
    return next((x["name"] for x in CAMPAIGN_LORRIES if x["id"] == lorry_id), "")

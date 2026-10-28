"""خطوط السير — عضوية الخط تُستنتج من وسم الخدمة وقت القراءة."""
from .clocktime import format_time, parse_time
from .constants import CAMPAIGN_LORRIES
from .service_catalog import catalog
from .store import reserve_id
from .utils import MAX_LEN


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


def new_id(data):
    return reserve_id(data, "LN", lines(data), width=1)


def _catalog_tags(data):
    """وسوم الخطوط هي الوسوم المسجلة في إعدادات الدليل، مش أي نص حر."""
    return list(dict.fromkeys(str(tag).strip() for tag in data.get("service_tags") or []
                              if str(tag).strip()))


def _canonical_time(value, field):
    raw = str(value or "").strip()
    if not raw:
        return "", None
    parsed = parse_time(raw)
    if not parsed:
        return None, f"ميعاد {field} غير صحيح."
    try:
        format_time(parsed)
    except ValueError:
        return None, f"ميعاد {field} غير صحيح."
    return parsed, None


def _line_payload(data, payload, existing=None):
    source = dict(existing or {})
    if "name" in payload or existing is None:
        name = str(payload.get("name", "")).strip()
        if not name:
            return None, "اسم خط السير مطلوب."
        if len(name) > MAX_LEN["name"]:
            return None, f"اسم خط السير أطول من الحد المسموح ({MAX_LEN['name']} حرف)."
        source["name"] = name
    if "tag" in payload or existing is None:
        tag = str(payload.get("tag", "")).strip()
        if not tag:
            return None, "وسم خط السير مطلوب."
        if tag not in _catalog_tags(data):
            return None, "وسم خط السير لازم يكون من وسوم دليل الخدمات."
        source["tag"] = tag
    if "lorry_id" in payload or existing is None:
        lorry_id = str(payload.get("lorry_id") or "").strip()
        if lorry_id and lorry_id not in {x["id"] for x in CAMPAIGN_LORRIES}:
            return None, "اللوري لازم يكون من لواري الحملة."
        source["lorry_id"] = lorry_id
    if "order" in payload or existing is None:
        order = payload.get("order") or []
        if not isinstance(order, list):
            return None, "ترتيب خدمات الخط غير صحيح."
        if any(not isinstance(service_id, str) or not service_id.strip() for service_id in order):
            return None, "ترتيب خدمات الخط يحتوي معرفًا غير صحيح."
        if len(order) != len(set(order)):
            return None, "ترتيب خدمات الخط فيه خدمة مكررة."
        service_by_id = {e.get("id"): e for e in catalog(data)}
        tag = source.get("tag")
        for service_id in order:
            entry = service_by_id.get(service_id)
            if not entry or tag not in (entry.get("tags") or []):
                return None, "ترتيب الخط يحتوي خدمة غير موجودة أو لا تحمل وسم الخط."
        source["order"] = list(order)
    for field, label in (("depart_am", "الصباحي"), ("depart_pm", "المسائي")):
        if field in payload or existing is None:
            value, error = _canonical_time(payload.get(field), label)
            if error:
                return None, error
            source[field] = value
    return source, None


def validate_lines(data, candidate_lines):
    seen_tags = {}
    seen_lorries = {}
    for line in candidate_lines:
        tag = line.get("tag")
        if tag in seen_tags:
            return f"الوسم مستخدم في خطي سير: «{seen_tags[tag]}» و«{line.get('name', '')}»."
        seen_tags[tag] = line.get("name", "")
        lorry = line.get("lorry_id")
        if lorry:
            if lorry in seen_lorries:
                return f"اللوري مستخدم في خطي سير: «{seen_lorries[lorry]}» و«{line.get('name', '')}»."
            seen_lorries[lorry] = line.get("name", "")

    memberships = {}
    by_id = {e.get("id"): e for e in catalog(data)}
    for line in candidate_lines:
        for entry in by_id.values():
            if line.get("tag") in (entry.get("tags") or []):
                memberships.setdefault(entry.get("id"), []).append(line.get("name", ""))
    conflicts = [f"{by_id[service_id].get('name', service_id)} ({' و'.join(names)})"
                 for service_id, names in memberships.items() if len(names) > 1]
    if conflicts:
        return "الخدمة مرتبطة بأكثر من خط سير: " + "، ".join(conflicts) + "."
    return None


def apply_line(data, payload, existing=None):
    """ينشئ أو يطبّق خطًا بعد تطبيع حقوله والتحقق من كل الخطوط."""
    line, error = _line_payload(data, payload, existing)
    if error:
        return None, error
    if existing is None:
        line["id"] = new_id(data)
    candidate = ([line if item.get("id") == existing.get("id") else item for item in lines(data)]
                 if existing is not None else [*lines(data), line])
    error = validate_lines(data, candidate)
    return (line, None) if not error else (None, error)

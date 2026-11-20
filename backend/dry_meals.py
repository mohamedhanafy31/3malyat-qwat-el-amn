"""بيانات «أمر صرف وجبات جافة» اليومي.

الوجبات الجافة ليست عرضًا محسوبًا من اللوحة: الخدمات الثابتة والطوارئ التي
اختارها المشغّل وأعدادها اليدوية محفوظة في قسم يومي مستقل، بينما قائمة
الاختيار وعدّاداتها مجرد اقتراحات من بيانات اليوم.
"""
from copy import deepcopy
from datetime import date, timedelta

from . import service_catalog
from .afraad import occasional_rows
from .assignments import peek_day
from .assignments_roster import WEEKDAYS, _day_date
from .board import _people_index, _row
from .day_open import needs_prepare, prepare
from .repo import PeopleRepo
from .service_equivalence import service_key, services_equivalent
from .signatures import signatories
from .special_formation import build as build_special, sections as special_sections
from .store import load_data, revision
from .text import norm
from .utils import canonical_day

DAY_KEY = "day_dry_meals"
MAX_FIXED_ROWS = 12
MAX_EMERGENCY_ROWS = 8
MAX_NAME = 80
MAX_NOTES = 120
SOURCES = {"أساسية", "طوارئ", "طوارئ خاصة"}


def scope(day):
    """نطاق اليوم + آخر الأيام التي تحفظ إعدادات وجبات جافة.

    هذا يحقق الترحيل الافتراضي من غير تحميل كل أرشيف الأيام في كل طلب.
    """
    value = date.fromisoformat(day)

    def _scope(view):
        previous = view.index.days_with(DAY_KEY, end=day)
        previous = previous[-400:]
        return {day, (value - timedelta(days=1)).isoformat(), *previous}

    return _scope


def _clean_name(value):
    return " ".join(str(value or "").split())


def _count(value):
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _row_value(item):
    return {
        "name": _clean_name(item.get("name")),
        "officers": _count(item.get("officers")),
        "personnel": _count(item.get("personnel")),
        "conscripts": _count(item.get("conscripts")),
        "notes": str(item.get("notes") or "").strip(),
    }


def _emergency_value(item):
    result = _row_value(item)
    result["source"] = str(item.get("source") or "").strip()
    return result


# الخدمات الثابتة الافتراضية (من أمر الوجبات الجافة الورقي). تُستخدم فقط
# لما ما يبقاش فيه يوم سابق محفوظ؛ بعد كده كل يوم يرث آخر يوم محفوظ كما هو.
DEFAULT_FIXED_ROWS = [
    {"name": "تمشيط حنيفة", "officers": 0, "personnel": 0, "conscripts": 1, "notes": ""},
    {"name": "تمشيط أم القمر", "officers": 0, "personnel": 0, "conscripts": 2, "notes": ""},
    {"name": "محور 30 يوليو", "officers": 0, "personnel": 2, "conscripts": 2, "notes": ""},
    {"name": "قول 36 لاسلكي", "officers": 0, "personnel": 0, "conscripts": 3, "notes": ""},
    {"name": "مكتب امن وطن بالسخنة", "officers": 0, "personnel": 1, "conscripts": 0, "notes": ""},
]


def _empty_config():
    return {
        "fixed_rows": [{"name": "", "officers": 0, "personnel": 0,
                        "conscripts": 0, "notes": ""}],
        "emergency_enabled": False,
        "emergency_rows": [],
        "ops_signer_id": "",
    }


def _stored_config(data, day):
    raw = (data.get(DAY_KEY) or {}).get(day)
    if not isinstance(raw, dict):
        return _empty_config(), False
    fixed = raw.get("fixed_rows")
    emergency = raw.get("emergency_rows")
    fixed = [_row_value(item) for item in fixed[:MAX_FIXED_ROWS]
             if isinstance(item, dict)] if isinstance(fixed, list) else []
    emergency = [_emergency_value(item) for item in emergency[:MAX_EMERGENCY_ROWS]
                 if isinstance(item, dict)] if isinstance(emergency, list) else []
    return {
        "fixed_rows": fixed,
        "emergency_enabled": bool(raw.get("emergency_enabled")),
        "emergency_rows": emergency,
        "ops_signer_id": str(raw.get("ops_signer_id") or ""),
    }, True


def _carry_forward(data, day):
    candidates = sorted(str(item) for item in (data.get(DAY_KEY) or {})
                        if str(item) < day)
    for source_day in reversed(candidates):
        value = (data.get(DAY_KEY) or {}).get(source_day)
        if not isinstance(value, dict) or not isinstance(value.get("fixed_rows"), list):
            continue
        rows = [_row_value(item) for item in value["fixed_rows"][:MAX_FIXED_ROWS]
                if isinstance(item, dict)]
        return rows or []
    return []


def _operations_members(data, day):
    members = []
    for person in PeopleRepo(data).on_force(day, "personnel"):
        raw = person.as_dict() if hasattr(person, "as_dict") else dict(person)
        if "عمليات" not in norm((raw.get("post") or "")):
            continue
        members.append({"id": raw.get("id", ""),
                        "rank": raw.get("role") or "",
                        "role": raw.get("role") or "",
                        "name": raw.get("name") or "",
                        "short_name": raw.get("short_name") or
                        " ".join(str(raw.get("name") or "").split()[:4])})
    return members


def _signer(data, day, config):
    members = _operations_members(data, day)
    ids = {item["id"] for item in members}
    roster_saved = (data.get("day_roster") or {}).get(day) or {}
    shared = str(roster_saved.get("ops_signer_id") or "")
    selected = config.get("ops_signer_id") if config.get("ops_signer_id") in ids else ""
    if not selected and shared in ids:
        selected = shared
    if not selected and members:
        selected = members[0]["id"]
    return members, selected, next((item for item in members if item["id"] == selected), None)


def _assignment_rows(data, day):
    people = _people_index(data)
    return [_row(item, people, day) for item in peek_day(data, day)]


def _match(candidate, row, section_name=""):
    if section_name and norm(candidate) == norm(section_name):
        return True
    return (services_equivalent(candidate, row.get("name"))
            or services_equivalent(candidate, row.get("label")))


def _suggested_counts(data, day, candidate, section_name=""):
    officers = personnel = conscripts = 0
    for row in _assignment_rows(data, day):
        if not _match(candidate, row, section_name):
            continue
        officers += len(row.get("officers") or [])
        personnel += len(row.get("personnel") or [])
        conscripts += _count(row.get("conscript_count"))
    return {"officers": officers, "personnel": personnel, "conscripts": conscripts}


def _candidate(name, source, data, day, section_name=""):
    name = _clean_name(name)
    counts = _suggested_counts(data, day, name, section_name)
    return {"name": name, "source": source, **counts}


def pickable_services(data, day):
    groups = {"أساسية": [], "طوارئ": [], "طوارئ خاصة": []}
    seen = {key: set() for key in groups}

    def add(group, item, section_name=""):
        name = _clean_name(item)
        key = service_key(name) or norm(name)
        if not name or key in seen[group]:
            return
        seen[group].add(key)
        groups[group].append(_candidate(name, group, data, day, section_name))

    for item in service_catalog.catalog(data):
        if isinstance(item, dict):
            add("أساسية", item.get("name"))
    for row in occasional_rows(data, day):
        add("طوارئ", row.get("name") or row.get("label"))
    for event in special_sections(data, day):
        section = _clean_name(event.get("name"))
        add("طوارئ خاصة", section, section)
        try:
            detail = build_special(data, day, section)
        except (LookupError, TypeError, ValueError):
            detail = {"posts": []}
        for post in detail.get("posts") or []:
            add("طوارئ خاصة", post.get("name"), section)
    return groups


def _normal_config(data, day):
    stored, saved = _stored_config(data, day)
    if not saved:
        carried = _carry_forward(data, day)
        if carried:
            stored["fixed_rows"] = carried
        else:
            stored["fixed_rows"] = [dict(row) for row in DEFAULT_FIXED_ROWS]
    members, signer_id, signer = _signer(data, day, stored)
    stored["ops_signer_id"] = signer_id
    chief = signatories(data, day).get("operations") or {"rank": "رائد", "name": "محمد بحر"}
    return stored, saved, members, signer, chief


def build(data, day):
    config, saved, members, signer, chief = _normal_config(data, day)
    fixed = deepcopy(config["fixed_rows"])
    emergency = deepcopy(config["emergency_rows"])
    fixed_total = sum(row["officers"] + row["personnel"] + row["conscripts"] for row in fixed)
    emergency_total = sum(row["officers"] + row["personnel"] + row["conscripts"] for row in emergency)
    parsed = _day_date(day)
    return {
        "date": day,
        "weekday": WEEKDAYS[parsed.weekday()] if parsed else "",
        "fixed_rows": fixed,
        "emergency_rows": emergency,
        "emergency_enabled": bool(config["emergency_enabled"]),
        "fixed_total": fixed_total,
        "emergency_total": emergency_total,
        "total": fixed_total + emergency_total,
        "config": config,
        "saved": saved,
        "operations_members": members,
        "ops_signer": signer,
        "chief": chief,
        "signatories": {"operations": signer or {"rank": "", "name": ""},
                        "operations_chief": chief},
        "pickable_services": pickable_services(data, day),
    }


def prepare_view(day):
    day = canonical_day(day)
    if not day:
        return None, None, None
    data = load_data(scope(day))
    preview = deepcopy(data)
    if needs_prepare(data, day, include_inspections=True):
        prepare(preview, day, include_inspections=True)
    return data, preview, build(preview, day)


def current_revision(day):
    return revision(load_data(scope(day)), [day])


def view(data, day):
    payload = build(data, day)
    payload["revision"] = revision(data, [day])
    return payload


def store_config(data, day, value):
    data.setdefault(DAY_KEY, {})[day] = {
        "fixed_rows": deepcopy(value["fixed_rows"]),
        "emergency_enabled": bool(value["emergency_enabled"]),
        "emergency_rows": deepcopy(value["emergency_rows"]),
        "ops_signer_id": str(value.get("ops_signer_id") or ""),
    }

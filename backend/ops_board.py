"""لوحة تشغيل الخدمات — حالة القيام والعودة اليومية، من غير أي عرض HTML."""
import re
from copy import deepcopy
from datetime import datetime, date, timedelta

from . import campaign, counts, day_status
from .afraad import basic_rows
from .dated import afraad_basic_on
from .assignments import peek_day
from .clocktime import format_time, parse_shift_pair, parse_time
from .constants import (SECTION_BASIC, SECTION_GREAT, SECTION_SECURITY,
                        SECTION_SUBCAMP, SECTION_TARGETS)
from .service_catalog import catalog
from .service_lines import line_for_service, lorry_name
from . import service_links
from .service_links import resolve_service_id, service_for_counts_entry
from .settings import get_setting
from .text import norm
from .repo import PeopleRepo

_EXCLUDED = {SECTION_TARGETS, SECTION_SUBCAMP, SECTION_GREAT, SECTION_SECURITY}
_SHIFTS = {"صباحية": "am", "ليلية": "pm", "صباح": "am", "ليل": "pm",
           "am": "am", "pm": "pm"}


def _shift(value):
    return _SHIFTS.get(str(value or "").strip(), "am" if "ص" in str(value) else "pm")


def _when(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.now()


def _catalog(data):
    return {e.get("id"): e for e in catalog(data) if e.get("id")}


class _BuildContext:
    """كاش محلي للّقطة؛ عمره طلب بناء واحد بس عشان البيانات متتسرّبش بين المعاملات."""
    def __init__(self, data):
        self.data = data
        self.cats = _catalog(data)
        self.service_index = {}
        for position, entry in enumerate(catalog(data)):
            if not entry.get("id"):
                continue
            for key in service_links._keys(entry.get("name")):
                self.service_index.setdefault(key, (position, entry.get("id")))
        self.campaigns = {}
        self.service_ids = {}

    def service_id(self, name):
        key = str(name or "")
        if key not in self.service_ids:
            self.service_ids[key] = resolve_service_id(
                self.data, key, index=self.service_index)
        return self.service_ids[key]

    def campaign(self, day):
        if day not in self.campaigns:
            self.campaigns[day] = campaign.build_campaign(self.data, day)
        return self.campaigns[day]


def _record(data, day, key):
    try:
        return ((data.get("day_service_runs") or {}).get(day) or {}).get(key) or {}
    except Exception:
        return {}


def _records(data, day, key):
    days = [day]
    try:
        base = date.fromisoformat(day)
        days += [(base - timedelta(days=i)).isoformat() for i in range(1, 4)]
    except ValueError:
        pass
    for item in days:
        value = _record(data, item, key)
        if value:
            return value, item
    return {}, day


def _campaign_line(data, day, assignment_id, ctx=None):
    view = ctx.campaign(day) if ctx else campaign.build_campaign(data, day)
    for row in view.get("lorries", []) + view.get("appointments", []):
        if any(x.get("assignment_id") == assignment_id for x in row.get("attached") or []):
            return row
    return None


def _line_info(data, day, service_id, assignment_id=None, ctx=None):
    line = line_for_service(data, service_id) if service_id else None
    lorry = _campaign_line(data, day, assignment_id, ctx) if assignment_id else None
    if not line and lorry:
        # خدمة طوارئ ملحقة بلوري من غير وسم خط: اللوري نفسه هو الخط الظاهر.
        line = {"id": lorry.get("id"), "name": lorry.get("name", ""),
                "lorry_id": lorry.get("id")}
        line_id = line["id"]
    else:
        line_id = (line or {}).get("id")
    if not line_id:
        return None
    warning = None
    attached_lorry_id = (lorry or {}).get("id") if lorry else None
    configured_lorry_id = (line or {}).get("lorry_id") or (line or {}).get("lorry")
    if line and attached_lorry_id and configured_lorry_id and attached_lorry_id != configured_lorry_id:
        warning = "الخدمة مرتبطة بلوري مختلف عن لوري الخط"
    if not lorry:
        lorry_id = configured_lorry_id
        camp = ctx.campaign(day) if ctx else campaign.build_campaign(data, day)
        lorry = next((x for x in camp.get("lorries", []) + camp.get("appointments", [])
                      if x.get("id") == lorry_id), None)
    lorry_id = configured_lorry_id
    return {"id": line_id, "line": line.get("name") or line.get("label") or line.get("title") or line_id,
            "lorry": (lorry or {}).get("name") or lorry_name(lorry_id),
            "driver": (lorry or {}).get("driver"), "vehicle": (lorry or {}).get("vehicle"),
            "warning": warning}


def _run(key, name, group, shift, *, report=None, report_text=None, line=None,
         head="", count=None, weapon="", source="", assignment_id=None, catalog_id=None):
    return {"key": key, "name": name, "group": group, "shift": shift,
            "report_time": report, "report_text": report_text or "", "state": "upcoming",
            "hint": None, "out_at": None, "out_by": None, "back_at": None,
            "back_by": None, "line_id": (line or {}).get("id"), "head": head,
            "line": (line or {}).get("line"), "count": count, "weapon": weapon,
            "warning": (line or {}).get("warning"),
            "catalog_id": catalog_id,
            "sources": [source] if source else [],
            "_groups": {group}, "_line": line, "_assignment_id": assignment_id,
            "_line_name": (line or {}).get("line"), "_lorry": (line or {}).get("lorry"),
            "_driver": (line or {}).get("driver"), "_vehicle": (line or {}).get("vehicle"),
            "_line_warning": (line or {}).get("warning")}


def _afraad_service_map(data, day, ctx=None):
    """ربط صفوف يومية الأفراد بالخدمة؛ 018 خزّن الرابط، والقديم يعتمد الاسم."""
    result = {}
    reference = ((data.get("reference_lists") or {}).get("afraad_basic") or [])
    applicable = [row for row in reference if (row.get("from") or "") <= day]
    version = max(applicable, key=lambda row: row.get("from") or "") if applicable else {}
    linked = {item.get("id"): item.get("service_id") for item in version.get("items") or []
              if item.get("id") and item.get("service_id")}
    for row in basic_rows(data, day):
        service_id = linked.get(row.get("id")) or (ctx.service_id(row.get("name")) if ctx else resolve_service_id(data, row.get("name")))
        if service_id:
            result[service_id] = row
    return result


def _normalise_count_sources(data, day, cats, ctx=None):
    """يكمل حقول الأعداد الناقصة من الكتالوج على النسخة الداخلية فقط."""
    stored = (data.get("service_counts") or {}).get(day)
    entries = stored.get("entries") if stored is not None else (data.get("counts_template") or {}).get("entries")
    for entry in entries or []:
        service_id = service_for_counts_entry(data, entry, index=ctx.service_index if ctx else None)
        service = cats.get(service_id) or {}
        if entry.get("count") in (None, "") and service.get("count") not in (None, ""):
            entry["count"] = service["count"]
        if entry.get("weapon") in (None, "") and service.get("weapon"):
            entry["weapon"] = service["weapon"]


def _add(pool, item):
    old = pool.get(item["key"])
    if not old:
        pool[item["key"]] = item
        return
    for field in ("head", "report_text", "weapon"):
        if not old.get(field) and item.get(field):
            old[field] = item[field]
    if old.get("count") in (None, "") and item.get("count") not in (None, ""):
        old["count"] = item["count"]
    old["sources"] = list(dict.fromkeys(old["sources"] + item["sources"]))
    old["_groups"] |= item.get("_groups", set())
    old["_line"] = old.get("_line") or item.get("_line")
    old["line_id"] = old.get("line_id") or item.get("line_id")
    old["warning"] = old.get("warning") or item.get("warning")
    old["_line_warning"] = old.get("_line_warning") or item.get("_line_warning")


def _apply_state(data, day, item, now):
    record, source_day = _record(data, day, item["key"]), day
    item["out_at"] = record.get("out_at")
    item["out_by"] = record.get("out_by")
    item["back_at"] = record.get("back_at")
    item["back_by"] = record.get("back_by")
    if record.get("report_override"):
        item["report_time"] = record["report_override"]
        item["report_text"] = format_time(record["report_override"])
    if record.get("back_at"):
        item["state"] = "back"
    elif record.get("out_at"):
        item["state"] = "out"
    if item["state"] == "upcoming" and item.get("report_time"):
        current = now.hour * 60 + now.minute
        hh, mm = (int(x) for x in item["report_time"].split(":"))
        delta = hh * 60 + mm - current
        prep = int(get_setting("ops_prep_minutes", 90) or 90)
        item["hint"] = "prep" if 0 <= delta <= prep else ("late" if delta < 0 else None)
    item["_source_day"] = source_day


def build_ops(data, day, now=None, _carry=True):
    """يبني لقطة تشغيل؛ النسخة الداخلية تمنع أي دالة مصدر من تعديل `data`."""
    internal = deepcopy(data)
    return _build_ops(internal, day, now, _carry, _BuildContext(internal))


def _build_ops(data, day, now=None, _carry=True, ctx=None):
    # السياق والنسخة الداخلية بيتعملوا مرة واحدة؛ الاستدعاءات المترحّلة بتشاركهم.
    if ctx is None:
        ctx = _BuildContext(data)
    now_dt = _when(now)
    cats = ctx.cats
    rows = {r.get("id"): r for r in peek_day(data, day)}
    af_by_service = _afraad_service_map(data, day, ctx)
    pool = {}

    def add_source(name, group, shift, entry_id, svc_id=None, raw_time=None,
                   schedule=None, head="", count=None, weapon="", source="", assignment_id=None):
        svc = cats.get(svc_id)
        default = (svc or {}).get("report_am" if shift == "am" else "report_pm") or ""
        # معاد يومية الأفراد بيكتب الفترتين «8 ص / 8 م»؛ وكتابة فترة واحدة
        # («8 ص فترة صباحة») تخص الصباحي بس. الفترة اللي مالهاش معاد هناك
        # بترجع لمعاد اللوحة ثم معاد الدليل.
        from_schedule = None
        if schedule:
            from_schedule = parse_shift_pair(schedule)[0 if shift == "am" else 1]
        raw_report = raw_time or default
        report = from_schedule or parse_time(raw_report)
        report_text = format_time(report) if report else str(raw_report or "")
        key = f"{svc_id}:{shift}" if svc_id else f"{entry_id}:{shift}"
        line = _line_info(data, day, svc_id, assignment_id, ctx)
        catalog_count = (svc or {}).get("count")
        catalog_weapon = (svc or {}).get("weapon")
        if count in (None, ""):
            count = catalog_count
        if weapon in (None, ""):
            weapon = catalog_weapon or ""
        _add(pool, _run(key, name, group, shift, report=report, report_text=report_text,
                        line=line, head=head, count=count, weapon=weapon,
                        source=source, assignment_id=assignment_id, catalog_id=svc_id))

    for row in peek_day(data, day):
        section = row.get("section") or ""
        if section != SECTION_BASIC:
            continue
        shift = _shift(row.get("shift"))
        svc_id = ctx.service_id(row.get("name"))
        officers = "، ".join(str(x.get("name") or x.get("full_name") or x)
                             for x in row.get("officers", []) if isinstance(x, dict))
        if not officers:
            names = []
            for ident in row.get("officer_ids") or []:
                person, _category, _bucket = PeopleRepo(data).locate(ident)
                if person:
                    names.append(f"{person.get('role', '')}/ {person.get('name', '')}".strip("/ "))
            officers = "، ".join(names or row.get("officer_names") or [])
        add_source(row.get("name", ""), "officers", shift, row.get("id"), svc_id,
                   raw_time=row.get("time"), head=officers, source="officers",
                   assignment_id=row.get("id"))

    _normalise_count_sources(data, day, cats, ctx)
    built = counts.build(data, day)
    for block, shift in (("basic_am", "am"), ("basic_pm", "pm")):
        for entry in built.get(block, []):
            svc_id = service_for_counts_entry(data, entry, index=ctx.service_index)
            afrow = af_by_service.get(svc_id)
            slot = (afrow or {}).get("morning" if shift == "am" else "night") or {}
            add_source(entry.get("name", ""), "basic", shift, entry.get("id"), svc_id,
                       schedule=(afrow or {}).get("schedule"),
                       head=slot.get("full_name") or slot.get("name", ""),
                       count=entry.get("count"), weapon=entry.get("weapon", ""), source=block)

    emergency = list(built.get("recurring", [])) + list(built.get("emergency", []))
    emergency += [row for section in built.get("custom_sections", []) for row in section.get("rows", [])]
    for entry in emergency:
        # صفوف الاعداد المتكررة ليها `id` (CNT-…)؛ صفوف الطوارئ المحسوبة من
        # اللوحة جاية من counts بـ`assignment_id` بس — من غيره كلهم كانوا
        # بياخدوا نفس المفتاح «None:am» ويفقدوا معادهم وفترتهم.
        ident = entry.get("id") or entry.get("assignment_id")
        raw = rows.get(ident, {})
        svc_id = service_for_counts_entry(data, entry, index=ctx.service_index)
        add_source(entry.get("name", ""), "emergency", _shift(raw.get("shift") or "am"), ident,
                   svc_id, raw_time=raw.get("time"), count=entry.get("count"),
                   weapon=entry.get("weapon", ""), source="emergency", assignment_id=ident)

    for item in pool.values():
        _apply_state(data, day, item, now_dt)
    runs = list(pool.values())
    # لو اليوم الجديد لسه مافيش له صف مقابل، ما نضيّعش تشغيل الأمس: نعيد
    # نفس البطاقة من مصدرها السابق في قائمة «مترحّلة».
    carried = []
    seen_refs = set()
    try:
      if _carry:
        base_day = date.fromisoformat(day)
        for offset in range(1, 4):
            previous = (base_day - timedelta(days=offset)).isoformat()
            previous_view = _build_ops(data, previous, now_dt, _carry=False, ctx=ctx)
            for candidate in previous_view.get("carried", []) + _flatten_runs(previous_view.get("groups", {})):
                origin = candidate.get("day") or previous
                ref = f"{origin}/{candidate.get('key')}"
                if ref in seen_refs:
                    continue
                record = _record(data, origin, candidate.get("key"))
                if record.get("out_at") and not record.get("back_at"):
                    _apply_state(data, origin, candidate, now_dt)
                    if candidate.get("state") == "out":
                        candidate["day"] = origin
                        candidate["ref"] = ref
                        carried.append(candidate)
                        seen_refs.add(ref)
    except (ValueError, KeyError):
        pass
    def sort_key(item):
        return item.get("report_time") or "99:99"
    groups = {"officers": [], "basic": {"am": {"lines": [], "single": []}, "pm": {"lines": [], "single": []}},
              "emergency": {"lines": [], "single": []}}
    for item in runs:
        for group_name in item.get("_groups", {item["group"]}):
            target = groups[group_name] if group_name == "officers" else groups["basic"][item["shift"]] if group_name == "basic" else groups["emergency"]
            if item.get("line_id") and group_name != "officers":
                target["lines"].append(item)
            elif group_name == "officers":
                target.append(item)
            else:
                target["single"].append(item)
    for target in (groups["basic"]["am"], groups["basic"]["pm"], groups["emergency"]):
        target["lines"] = _line_groups(data, target["lines"])
        target["single"].sort(key=sort_key)
    groups["officers"].sort(key=sort_key)
    for item in carried:
        item["source_day"] = item.get("_source_day")
    for item in runs + carried:
        for field in ("_groups", "_line", "_assignment_id", "_source_day", "_line_name", "_lorry", "_driver", "_vehicle", "_line_warning"):
            item.pop(field, None)
    upcoming = [r for r in runs if r["state"] == "upcoming"]
    now_minutes = now_dt.hour * 60 + now_dt.minute
    def next_key(run):
        hh, mm = (int(part) for part in run["report_time"].split(":"))
        return (hh * 60 + mm, 0 if run.get("line_id") else 1)
    next_run = min((r for r in upcoming if r.get("report_time")
                    and int(r["report_time"][:2]) * 60 + int(r["report_time"][3:]) >= now_minutes),
                   key=next_key, default=None)
    minutes_left = None
    if next_run:
        minutes_left = (int(next_run["report_time"][:2]) * 60 + int(next_run["report_time"][3:])
                        - now_dt.hour * 60 - now_dt.minute)
    next_value = dict(next_run) if next_run else None
    if next_value is not None:
        next_value["minutes_left"] = minutes_left
        if next_value.get("line_id"):
            next_value["line"] = next_value.get("line") or next_value["line_id"]
    return {"date": day, "now": now_dt.isoformat(timespec="minutes"),
            "prep_minutes": int(get_setting("ops_prep_minutes", 90) or 90),
            "next": next_value,
            "counters": {"upcoming": sum(r["state"] == "upcoming" for r in runs),
                         "prep": sum(r["hint"] == "prep" for r in runs), "late": sum(r["hint"] == "late" for r in runs),
                         "out": sum(r["state"] == "out" for r in runs), "back": sum(r["state"] == "back" for r in runs),
                         "carried": len(carried)}, "groups": groups, "carried": carried}


def _line_groups(data, items):
    grouped = {}
    for item in items:
        line = item.get("line_id")
        group = grouped.setdefault(line, {"line_id": line, "line": "", "lorry": None, "driver": None,
                                          "vehicle": None, "warning": None, "runs": []})
        group["runs"].append(item)
        group["line"] = item.get("_line_name") or line
        group["lorry"] = item.get("_lorry")
        group["driver"] = item.get("_driver")
        group["vehicle"] = item.get("_vehicle")
        group["warning"] = group.get("warning") or item.get("_line_warning")
    for value in grouped.values():
        run = value["runs"][0]
        value["line"] = value.get("line") or run.get("line_id")
        value["_order"] = {service_id: index for index, service_id in enumerate(
            next((line.get("order") or [] for line in data.get("service_lines") or []
                  if line.get("id") == value.get("line_id")), []))}
        # line_id is enough for the lookup above; the fallback keeps emergency-only lines stable.
        value["runs"].sort(key=lambda run: (value["_order"].get(run.get("key", "").rsplit(":", 1)[0], 10**6),
                                      run.get("report_time") or "99:99"))
        value.pop("_order", None)
    line_order = {line.get("id"): index for index, line in enumerate(data.get("service_lines") or [])}
    return sorted(grouped.values(), key=lambda value: line_order.get(value["runs"][0].get("line_id"), 10**6))


def _flatten_runs(groups):
    out = list(groups.get("officers") or [])
    for block in (groups.get("basic", {}).get("am", {}), groups.get("basic", {}).get("pm", {}), groups.get("emergency", {})):
        out.extend(block.get("single") or [])
        out.extend(run for line in block.get("lines") or [] for run in line.get("runs") or [])
    return out


def _check_key(data, day, key):
    origin = day
    plain_key = key
    if isinstance(key, str) and "/" in key:
        origin, plain_key = key.split("/", 1)
    value, stored_day = _record(data, origin, plain_key), origin
    if not value:
        if origin != day:
            raise ValueError("الخدمة المترحّلة غير موجودة.")
        view = build_ops(data, day)
        known = {run.get("key") for run in _flatten_runs(view.get("groups", {}))}
        if plain_key in known:
            return {}, day, plain_key
        raise ValueError("الخدمة غير موجودة.")
    return value, stored_day, plain_key


def depart(data, day, keys, actor, now):
    ok, error = day_status.check_open(data, day)
    if not ok:
        raise ValueError(error)
    at = _when(now).isoformat(timespec="seconds")
    for key in keys:
        record, stored, plain_key = _check_key(data, day, key)
        if record.get("out_at"):
            raise ValueError("تم تسجيل القيام بالفعل")
        target = data.setdefault("day_service_runs", {}).setdefault(stored, {}).setdefault(plain_key, {})
        target.update(out_at=at, out_by=actor, state="out")
        target.setdefault("history", []).append({"action": "depart", "at": at, "by": actor})


def return_(data, day, keys, actor, now):
    at = _when(now).isoformat(timespec="seconds")
    for key in keys:
        record, stored, plain_key = _check_key(data, day, key)
        if record.get("back_at"):
            raise ValueError("تم تسجيل العودة بالفعل")
        if not record.get("out_at"):
            raise ValueError("لا يمكن تسجيل العودة قبل القيام")
        target = data.setdefault("day_service_runs", {}).setdefault(stored, {}).setdefault(plain_key, {})
        target.update(back_at=at, back_by=actor, state="back")
        target.setdefault("history", []).append({"action": "return", "at": at, "by": actor})


def undo(data, day, key, actor, now):
    record, stored, plain_key = _check_key(data, day, key)
    history = record.get("history") or []
    if not history or (_when(now) - _when(history[-1].get("at"))).total_seconds() > 300:
        raise ValueError("لا يمكن التراجع بعد مرور 5 دقائق")
    last = history.pop()
    if last.get("action") == "return":
        record.pop("back_at", None); record.pop("back_by", None); record["state"] = "out"
    else:
        record.pop("out_at", None); record.pop("out_by", None); record["state"] = "upcoming"
    return stored


def _time_run(data, day, key):
    """بيجيب الحد الأدنى من بيانات التشغيل من المصدر، من غير بناء لوحة كاملة."""
    origin, plain_key = (key.split("/", 1) if isinstance(key, str) and "/" in key
                         else (day, key))
    base, _, raw_shift = plain_key.rpartition(":")
    shift = raw_shift if raw_shift in ("am", "pm") else "am"
    entries = catalog(data)
    entry = next((item for item in entries if item.get("id") == base), None)
    rows = peek_day(data, origin)
    row = next((item for item in rows if item.get("id") == base), None)
    found_source = row is not None
    if row is None:
        stored = (data.get("service_counts") or {}).get(origin) or {}
        count_entries = stored.get("entries") if stored else (data.get("counts_template") or {}).get("entries")
        count_entry = next((item for item in count_entries or []
                            if (item.get("id") or item.get("assignment_id")) == base), None)
        if count_entry:
            row = count_entry
            found_source = True
    if row is None and entry:
        # مفتاح الدليل لازم يكون له مصدر فعلي في التشغيل؛ وجوده في الدليل
        # لوحده ماكانش كفاية في النسخة القديمة اللي كانت بتدور في build_ops.
        built = counts.build(data, origin)
        for block in ("basic_am", "basic_pm", "recurring", "emergency"):
            for item in built.get(block, []):
                if service_for_counts_entry(data, item) == base:
                    row = item
                    found_source = True
                    break
            if found_source:
                break
    if row is not None:
        row_shift = _shift(row.get("shift") or ("صباحية" if shift == "am" else "ليلية"))
        shift = row_shift
        if not entry:
            name = row.get("name") or row.get("label") or ""
            resolved = resolve_service_id(data, name)
            entry = next((item for item in entries if item.get("id") == resolved), None)
    if not entry and not row or (entry and not found_source):
        return None
    return {"shift": shift, "catalog_id": (entry or {}).get("id"),
            "base": base, "row": row, "origin": origin, "key": plain_key}


def set_time(data, day, key, hhmm, scope, actor):
    """تعديل معاد الانتظام من الرئيسية.

    «day»: صف اليومية التفصيلية (أساسي ضباط أو طارئ) بيتكتب في خانة `time`
    نفسها اللي الوورد بيطبعها؛ صف الاعداد ملوش خانة معاد، فبيتخزن override
    على سجل التشغيل لليوم ده بس. «default»: معاد الدليل نفسه بصيغة HH:MM.
    """
    raw = str(hhmm or "").strip()
    parsed = raw if re.fullmatch(r"\d{2}:\d{2}", raw) else parse_time(raw)
    if not parsed or parse_time(parsed) != parsed:
        raise ValueError("الوقت غير صحيح.")
    ok, error = day_status.check_open(data, day)
    if not ok:
        raise ValueError(error)
    run = _time_run(data, day, key)
    if not run:
        raise ValueError("الخدمة غير موجودة.")
    base = run["base"]
    if scope == "default":
        entry = next((e for e in catalog(data) if e.get("id") == run.get("catalog_id")), None)
        if not entry:
            raise ValueError("الخدمة دي مش موجودة في دليل الخدمات، فالتعديل لليوم بس.")
        entry["report_am" if run["shift"] == "am" else "report_pm"] = parsed
    elif scope == "day":
        rows = peek_day(data, run["origin"])
        # تشغيل مبني على صف لوحة بعينه (AS-…) — أساسي ضباط أو طارئ
        row = next((r for r in rows if r.get("id") == base), None)
        if row is None and base in {e.get("id") for e in catalog(data)}:
            row = next((r for r in rows
                        if r.get("section") == SECTION_BASIC
                        and resolve_service_id(data, r.get("name")) == base
                        and _shift(r.get("shift")) == run["shift"]), None)
        if row is not None:
            row["time"] = format_time(parsed)
        else:
            data.setdefault("day_service_runs", {}).setdefault(run["origin"], {}).setdefault(run["key"], {})["report_override"] = parsed
    else:
        raise ValueError("نطاق المعاد غير صحيح.")

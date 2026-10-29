"""بناء payload يومية انتظام الخدمات من بيانات اليوم الخام.

الملف ده مقصود يبقى طبقة قراءة مستقلة عن ``ops_board``: لوحة التشغيل بتدمج
التكليفات لأغراض العرض، بينما اليومية الرسمية لازم تفضل أمينة لكل صف محفوظ.
"""
import re
from datetime import date

from .afraad import _time_key, basic_rows
from .assignments import officer_state, peek_day
from .board import _people_index
from .campaign import build_campaign, service_vehicles
from .constants import (SECTION_ADMIN_WORK, SECTION_BASIC, SECTION_GREAT,
                        SECTION_NET, SECTION_OUTSIDERS, SECTION_PRISON,
                        SECTION_RESTS, SECTION_SECURITY, SECTION_SUBCAMP,
                        SECTION_TARGETS, SECTION_TAQSEERA, canonical_section_name)
from .dated import command_on
from .duty import officer_row
from .labels import officer_label, personnel_label
from .leaves import leave_on
from .people import effective, officers_on
from .repo import ConscriptRepo, PeopleRepo
from .text import core_service_name, norm
from .board_export import WEEKDAY_BY_INDEX


PLACEHOLDER = "ــــــــــــ"
_STRUCTURAL = {SECTION_BASIC, SECTION_TARGETS, SECTION_SUBCAMP, SECTION_GREAT,
               SECTION_SECURITY, SECTION_ADMIN_WORK, SECTION_NET,
               SECTION_RESTS, SECTION_TAQSEERA, SECTION_OUTSIDERS}
DEFAULT_NOTES = [
    "عدد 10 مجند حفظ نظام لتأمين محكمه والباب الرئيسي الساعه 8ص بالمديرية",
    "تعزيز المجمع الطبي (2مجند) الساعة 2 م وحتي انتهاء زيارات المرضي",
    "عدد (1) مجند قول كورنيش مسلح خرطوش من 7م : الانصراف",
]


def _text(value):
    return str(value or "").strip()


def _value(value, warning=None, warnings=None):
    value = _text(value)
    if value:
        return value
    if warning and warnings is not None:
        warnings.append(warning)
    return PLACEHOLDER


def _compact_time(value):
    from .clocktime import compact_time
    return compact_time(value)


def _people(data, day, assignment):
    repo = PeopleRepo(data)
    out = []
    for ident in assignment.get("officer_ids") or []:
        raw, category, _ = repo.locate(str(ident))
        if raw is not None and category == "officers":
            out.append({**raw, **effective(raw, day), "id": ident, "category": category,
                        "short_name": raw.get("short_name", "")})
    for ident in assignment.get("personnel_ids") or []:
        raw, category, _ = repo.locate(str(ident))
        if raw is not None and category == "personnel":
            out.append({**raw, **effective(raw, day), "id": ident, "category": category})
    for ident in assignment.get("conscripts") or []:
        raw = ConscriptRepo(data).find(str(ident))
        if raw:
            out.append({"id": ident, "name": raw.name, "phone": raw.phone,
                        "role": "", "category": "personnel"})
    return out


def _labels(people):
    labels, phones = [], []
    for person in people:
        labels.append(personnel_label(person) if person.get("category") == "personnel"
                       else officer_label(person))
        phones.append(_text(person.get("phone")))
    return " + ".join(labels), " + ".join(phones)


def _vehicle_label(vehicles):
    return " + ".join(_text(item.get("label") or item.get("plate")) for item in vehicles
                       if _text(item.get("label") or item.get("plate")))


def _assignment_row(data, day, assignment, order):
    warnings = []
    people = _people(data, day, assignment)
    vehicles = service_vehicles(data, day, assignment.get("id"))
    # في الشكل القديم المركبة الواحدة ماكانش بيتحفظ عليها توزيع الأشخاص،
    # وبالتالي الصف الرسمي لازم يضم كل قائمين الخدمة.
    if len(vehicles) == 1 and not vehicles[0].get("people"):
        vehicles[0] = {**vehicles[0], "people": people}
    variants = vehicles or [None]
    people_by_id = {person.get("id"): person for person in people}
    rows = []
    for vehicle in variants:
        vehicle_people = vehicle.get("people") if vehicle else None
        row_people = ([people_by_id.get(item.get("id"), item) for item in vehicle_people]
                      if vehicle_people else people)
        labels, phones = _labels(row_people)
        if not row_people:
            warnings.append("لا يوجد قائم للخدمة.")
        row_warnings = []
        place = _value(assignment.get("party"), "مكان الانتظام غير مسجل.", row_warnings)
        time = _value(_compact_time(assignment.get("time") or assignment.get("clocktime")),
                      "ساعة الانتظام غير مسجلة.", row_warnings)
        count = assignment.get("conscript_count")
        count = str(count) if count is not None and count != "" else PLACEHOLDER
        if count == PLACEHOLDER:
            row_warnings.append("عدد المجندين غير مسجل.")
        if not labels:
            row_warnings.append("لا يوجد قائم للخدمة.")
        if not phones:
            row_warnings.append("رقم الهاتف غير مسجل.")
        if not vehicle:
            row_warnings.append("المركبة غير مسجلة.")
        rows.append({"service": _text(assignment.get("name")),
                     "people": labels or PLACEHOLDER,
                     "phone": phones or PLACEHOLDER,
                     "vehicle": (_vehicle_label([vehicle]) if vehicle else PLACEHOLDER),
                     "place": place, "time": time, "count": count,
                     "warnings": list(dict.fromkeys(warnings + row_warnings)),
                     "order": order, "time_key": _time_key(assignment.get("time"))})
    return rows


def _ambulance_row(data, day, rows):
    basic = next((row for row in basic_rows(data, day)
                  if "اسعاف" in norm(row.get("name"))), None)
    if not basic:
        return
    campaign = build_campaign(data, day)
    daily = next((row for row in campaign.get("daily") or []
                  if row.get("basic_entry_id") == basic.get("id")
                  or "اسعاف" in norm(row.get("name"))), None)
    person = basic.get("morning") or {}
    label = _text(person.get("full_name"))
    if label:
        raw, category, _ = PeopleRepo(data).locate(person.get("person_id", ""))
        label = personnel_label({**(raw or {}), "name": raw.get("name", label) if raw else label,
                                 "role": (raw or {}).get("role", person.get("role", ""))})
    phones = _text(person.get("phone"))
    warnings = []
    if not label: warnings.append("لا يوجد قائم للخدمة.")
    if not phones: warnings.append("رقم الهاتف غير مسجل.")
    vehicle = (daily or {}).get("vehicle") or {}
    if not vehicle: warnings.append("المركبة غير مسجلة.")
    rows.append({"service": _text((daily or {}).get("name") or basic.get("name")), "people": label or PLACEHOLDER,
                 "phone": phones or PLACEHOLDER,
                 "vehicle": _text(vehicle.get("plate")) or PLACEHOLDER,
                 "place": _value(basic.get("location_text"), "مكان الانتظام غير مسجل.", warnings),
                 "time": _value(_compact_time(basic.get("schedule")), "ساعة الانتظام غير مسجلة.", warnings),
                 "count": str(basic.get("conscript_count")) if basic.get("conscript_count") is not None else PLACEHOLDER,
                 "warnings": list(dict.fromkeys(warnings)), "order": -1,
                 "time_key": _time_key(basic.get("schedule"))})


def _officer(data, day, ident):
    raw, category, _ = PeopleRepo(data).locate(str(ident or ""))
    if raw is None or category != "officers":
        return None
    return {**raw, **effective(raw, day), "id": ident, "category": category,
            "short_name": raw.get("short_name", "")}


def _officer_rows(data, day, inputs):
    command = command_on(data, day)
    director = _officer(data, day, command.get("مدير الإدارة"))
    deputy = _officer(data, day, command.get("وكيل الإدارة"))
    def unavailable(person):
        if not person:
            return True
        row = officer_row(data, day, person)
        return bool(row.get("leave") or row.get("group") == "خوارج")
    supervisor = deputy if unavailable(director) else director
    extra = inputs.get("officer_extra") or {}
    result = []
    if supervisor:
        text = "المتابعة الاشرافية علي جميع خدمات قوات الامن"
        if _text(extra.get(supervisor["id"])):
            text += " + " + _text(extra[supervisor["id"]])
        result.append({"rank": supervisor.get("role", ""), "name": supervisor.get("short_name") or supervisor.get("name", ""),
                       "service": text, "id": supervisor["id"], "kind": "supervisory"})
    other = deputy if supervisor is director else director
    if other and _text(extra.get(other["id"])):
        result.append({"rank": other.get("role", ""), "name": other.get("short_name") or other.get("name", ""),
                       "service": _text(extra[other["id"]]), "id": other["id"], "kind": "command-extra"})

    basic = []
    for assignment in peek_day(data, day):
        if canonical_section_name(assignment.get("section")) != SECTION_BASIC:
            continue
        for ident in assignment.get("officer_ids") or []:
            person = _officer(data, day, ident)
            if not person:
                continue
            core = core_service_name(assignment.get("name") or "")
            shift = assignment.get("shift") or ""
            # مدى الساعات بين علامتي تنصيص للقول المكبر والتدخل السريع بس؛ المواقع
            # الثابتة (الحي الحكومي…) الأصل بيكتبها «فترة صباحية» من غير مدى.
            rotating = "قول مكبر" in norm(core) or "تدخل" in norm(core)
            if rotating and shift == "صباحية":
                hours = '"8 ص الي 8 م"'
            elif rotating and shift == "ليلية":
                hours = '"8 م الي 8 ص"'
            else:
                hours = ""
            prefix = "مشرف القول المكبر" if "قول مكبر" in norm(core) else core
            text = f"{prefix} فترة {'صباحية' if shift == 'صباحية' else 'ليلية' if shift == 'ليلية' else ''} {hours}".strip()
            basic.append((assignment.get("pos", 10**6), core, shift, person, text))
    basic.sort(key=lambda x: (0 if "قول مكبر" in norm(x[1]) else 1 if "تدخل" in norm(x[1]) else 2,
                             0 if x[2] == "صباحية" else 1, x[0]))
    for _pos, _core, _shift, person, text in basic:
        name = person.get("short_name") or person.get("name", "")
        if person.get("phone"):
            name = f"{name} ({person['phone']})"
        result.append({"rank": person.get("role", ""), "name": name, "service": text,
                       "id": person["id"], "kind": "basic"})
    overrides = inputs.get("big_column_supervisors") or {}
    override_people = {key: _officer(data, day, ident)
                       for key, ident in overrides.items() if ident}
    if override_people:
        # مدخلات اليومية هي override حقيقي، مش fallback فقط: نشيل صف القول
        # المكبر لنفس الفترة من اللوحة ونضع الضابط المحدد في inputs مكانه.
        kept = []
        for row in result:
            service = norm(row.get("service"))
            if "مشرف القول المكبر" not in service:
                kept.append(row)
                continue
            if norm("صباحية") in service and override_people.get("am"):
                continue
            if norm("ليلية") in service and override_people.get("pm"):
                continue
            kept.append(row)
        result = kept
    existing = set()
    for shift, key, hours in (("صباحية", "am", '"8 ص الي 8 م"'), ("ليلية", "pm", '"8 م الي 8 ص"')):
        person = _officer(data, day, overrides.get(key))
        if person and person["id"] not in existing:
            result.insert(2 if key == "am" else 3,
                          {"rank": person.get("role", ""),
                           "name": f"{person.get('short_name') or person.get('name', '')} ({person.get('phone', '')})" if person.get("phone") else person.get("short_name") or person.get("name", ""),
                           "service": f"مشرف القول المكبر فترة {shift} {hours}",
                           "id": person["id"], "kind": "big-column"})
            existing.add(person["id"])
    return result


def build(data, day, inputs=None):
    inputs = inputs or {}
    rows = []
    excluded = _STRUCTURAL | {SECTION_PRISON}
    for order, assignment in enumerate(peek_day(data, day)):
        section = canonical_section_name(assignment.get("section"))
        if section in excluded:
            continue
        rows.extend(_assignment_row(data, day, assignment, order))
    _ambulance_row(data, day, rows)
    rows.sort(key=lambda row: (row["time_key"], row["order"]))
    warnings = [warning for row in rows for warning in row.get("warnings") or []]
    signatories = {}
    command = command_on(data, day)
    for key, ident in (("director", command.get("مدير الإدارة")), ("deputy", command.get("وكيل الإدارة"))):
        person = _officer(data, day, ident)
        signatories[key] = {"rank": person.get("role", "") if person else "عقيد",
                            "name": (person.get("short_name") or " ".join(person.get("name", "").split()[:2])) if person else PLACEHOLDER}
    chief = _officer(data, day, inputs.get("operations_chief"))
    if chief is None:
        for person in officers_on(data, day):
            if "رئيس قسم العمليات" in _text(effective(person, day).get("post")):
                chief = {**person, **effective(person, day)}
                break
    signatories["operations"] = {"rank": chief.get("role", "رائد") if chief else "رائد",
                                  "name": ((chief.get("short_name") or " ".join(chief.get("name", "").split()[:2])) if chief else "محمد بحر")}
    d = date.fromisoformat(day)
    title = f"يومية انتظام الخدمات عن يوم {WEEKDAY_BY_INDEX[d.weekday()]} الموافق {d.day}/{d.month}/{d.year}م"
    return {"title": title, "service_rows": rows,
            "officer_rows": _officer_rows(data, day, inputs),
            "notes": list(inputs.get("notes") or DEFAULT_NOTES), "signatories": signatories,
            "warnings": list(dict.fromkeys(warnings))}

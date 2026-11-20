"""منطق backend ليومية الحملة."""
from copy import deepcopy
from datetime import date, timedelta

from . import changes, fleet
from .afraad import occasional_rows
from .assignments import peek_day
from .constants import APPOINTMENT_LORRIES, CAMPAIGN_LORRIES, VEHICLE_TYPES
from .dated import (afraad_basic_on, campaign_daily_on, campaign_lorries_on, campaign_posts_on,
                    record_campaign_daily_change, record_campaign_lorries_change, remember_campaign_lorry, record_campaign_posts_change)
from .repo import ConscriptRepo, PeopleRepo, VehicleRepo
from .store import reserve_id
from .text import norm


ALL_LORRIES = CAMPAIGN_LORRIES + APPOINTMENT_LORRIES
LORRY_NAMES = {item["id"]: item["name"] for item in ALL_LORRIES}


def referenced_vehicle_days(data, vehicle_id):
    days = []
    for day, sheet in (data.get("day_campaign") or {}).items():
        for section in ("lorries", "services", "daily", "posts"):
            if any(_entry_vehicle_ids(entry) and vehicle_id in _entry_vehicle_ids(entry)
                   for entry in ((sheet or {}).get(section) or {}).values()
                   if isinstance(entry, dict)):
                days.append(day)
                break
        else:
            if any(vehicle_id in _entry_vehicle_ids(group)
                   for group in (sheet or {}).get("groups") or []):
                days.append(day)
    return days


def referenced_conscript_days(data, conscript_id):
    return [day for day, sheet in (data.get("day_campaign") or {}).items()
            if any((entry.get("driver") or {}).get("kind") == "conscript" and
                   (entry.get("driver") or {}).get("id") == conscript_id
                   for section in (sheet or {}).values() if isinstance(section, dict)
                   for entry in section.values())
            or any((group.get("driver") or {}).get("kind") == "conscript" and
                   (group.get("driver") or {}).get("id") == conscript_id
                   for group in (sheet or {}).get("groups") or [])]


def _raw(data, day):
    days = data.setdefault("day_campaign", {})
    return days.setdefault(day, {})


# أقصى رجوع (بالأيام التقويمية) لوراثة قيمة الصف من يوم أقدم. اليوم الناقص
# (صف أو أكتر من غير مركبة/سائق) مايقطعش الوراثة عن اللي بعده، لكن مفيش
# توريث مفتوح لقيمة عمرها شهور.
INHERIT_WINDOW_DAYS = 31
_INHERITED_KEYS = ("vehicle_id", "driver", "driver_text", "plate_text", "type_text", "basic_entry_id")


# أيام قبل التاريخ ده (كلها مقفولة) بتفضل على التوريث القديم: من آخر يوم سابق
# محفوظ بس، عشان اللي اتعرض واتطبع قبل كده مايتغيرش من غير موافقة. القاعدة
# بتعتمد على تاريخ ثابت مش على حالة القفل، فاليوم مايتغيّرش شكله وقت ما يتقفل.
# لتصحيح أيام أقدم يتم تقديم التاريخ ده بقرار صريح.
INHERIT_WALK_FROM = "2026-10-21"


def inheritance_days(campaign_days, day):
    """الأيام السابقة اللي يوم `day` بيورّث منها، من الأقدم للأحدث.
    `campaign_days`: كل الأيام اللي ليها حملة (الـindex يكفي، من غير تحميل ملفات)."""
    earlier = sorted(d for d in campaign_days if d < day)
    if day < INHERIT_WALK_FROM:
        return earlier[-1:]
    try:
        start = (date.fromisoformat(day) - timedelta(days=INHERIT_WINDOW_DAYS)).isoformat()
    except ValueError:
        return earlier[-1:]
    return [d for d in earlier if d >= start]


def _chain(data, day):
    return inheritance_days(data.get("day_campaign") or {}, day)


def _prior(data, chain, section, ident):
    """قيمة الصف الموروثة: كل مفتاح من أحدث يوم سابق محفوظ فيه المفتاح ده.
    المفتاح الموجود فاضي (`"driver": {}`) مسح صريح وبيقطع الرجوع."""
    prior = {}
    for d in chain:
        entry = (((data.get("day_campaign") or {}).get(d) or {}).get(section) or {}).get(ident)
        if isinstance(entry, dict):
            if any(key in entry for key in ("vehicle_id", "plate_text", "type_text")):
                for key in ("vehicle_id", "plate_text", "type_text"):
                    prior.pop(key, None)
            for key in (*_INHERITED_KEYS, "vehicles"):
                if key in entry:
                    prior[key] = entry[key]
    return prior


def _prior_with_sources(data, chain, section, ident):
    """القيمة الموروثة ويوم مصدر كل مفتاح فعلي فيها."""
    prior, sources = {}, {}
    for d in chain:
        entry = (((data.get("day_campaign") or {}).get(d) or {}).get(section) or {}).get(ident)
        if isinstance(entry, dict):
            if any(key in entry for key in ("vehicle_id", "plate_text", "type_text")):
                for key in ("vehicle_id", "plate_text", "type_text"):
                    prior.pop(key, None)
                    sources.pop(key, None)
            for key in (*_INHERITED_KEYS, "vehicles"):
                if key in entry:
                    prior[key] = deepcopy(entry[key])
                    sources[key] = d
    return prior, sources


def _prior_plates(data, chain):
    for d in reversed(chain):
        plates = ((data.get("day_campaign") or {}).get(d) or {}).get("plates")
        if plates is not None:
            return plates
    return None


def _prior_plates_with_source(data, chain):
    for d in reversed(chain):
        plates = ((data.get("day_campaign") or {}).get(d) or {}).get("plates")
        if plates is not None:
            return plates, d
    return None, None


def _driver(data, value):
    if not value:
        return None
    kind = value.get("kind")
    ident = str(value.get("id") or "")
    if kind == "personnel":
        raw, category, _ = PeopleRepo(data).locate(ident)
        if raw is None or category != "personnel":
            return None
        return {"kind": kind, "id": ident, "name": raw.get("name", ""), "phone": raw.get("phone", ""),
                "role": raw.get("role", ""), "display": str(value.get("display") or "").strip()}
    if kind == "conscript":
        person = ConscriptRepo(data).find(ident)
        if not person:
            return None
        return {"kind": kind, "id": ident, "name": person.name, "phone": person.phone,
                "display": str(value.get("display") or "").strip()}
    return {"kind": "text", "id": "", "name": str(value.get("name") or "").strip(), "phone": ""}


def _vehicle(data, vehicle_id):
    vehicle = VehicleRepo(data).find(vehicle_id) if vehicle_id else None
    if not vehicle:
        return None
    return {"id": vehicle.id, "plate": vehicle.plate, "type": vehicle.type,
            "model": vehicle.model, "status": vehicle.status, "fault": vehicle.fault,
            "origin": vehicle.origin, "party": vehicle.party, "archived": vehicle.archived}


def _entry_vehicle_ids(entry):
    """بيجمع مراجع المركبات القديمة والجديدة عشان الحذف يفضل آمن."""
    if not isinstance(entry, dict):
        return []
    values = []
    if entry.get("vehicle_id"):
        values.append(str(entry["vehicle_id"]))
    for item in entry.get("vehicles") or []:
        if isinstance(item, dict) and item.get("vehicle_id"):
            values.append(str(item["vehicle_id"]))
    return list(dict.fromkeys(values))


def _assignment(data, day, assignment_id):
    return next((row for row in peek_day(data, day)
                 if row.get("id") == assignment_id), None)


def _assignment_people(assignment):
    assignment = assignment or {}
    return {
        "personnel_ids": list(dict.fromkeys(str(value).strip() for value in
                                            assignment.get("personnel_ids") or [] if str(value).strip())),
        "officer_ids": list(dict.fromkeys(str(value).strip() for value in
                                          assignment.get("officer_ids") or [] if str(value).strip())),
    }


def _direct_service_entries(data, day, assignment_id, raw=None):
    """بيوحّد الشكل القديم والجديد للقراءة، من غير ما يكتب في البيانات."""
    raw = raw or {}
    people = _assignment_people(_assignment(data, day, assignment_id))
    if isinstance(raw.get("vehicles"), list):
        return [dict(item) for item in raw["vehicles"] if isinstance(item, dict)]
    if raw.get("vehicle_id"):
        return [{"vehicle_id": raw["vehicle_id"], **people,
                 **({"driver": deepcopy(raw["driver"])} if raw.get("driver") else {})}]
    return []


def _person_view(data, ident, category):
    raw, found, _ = PeopleRepo(data).locate(ident)
    if raw is None or found != category:
        return None
    return {"id": ident, "name": raw.get("name", ""), "role": raw.get("role", ""),
            "category": category}


def _vehicle_people(data, item, assignment_people):
    people = []
    for category, key in (("personnel", "personnel_ids"), ("officers", "officer_ids")):
        allowed = set(assignment_people[key])
        for ident in item.get(key) or []:
            ident = str(ident).strip()
            if ident in allowed:
                person = _person_view(data, ident, category)
                if person:
                    people.append(person)
    return people


def service_vehicles(data, day, assignment_id, *, include_empty_lorries=False):
    """المركبات الفعلية للخدمة بترتيبها: المباشر الأول ثم لوري الإلحاق."""
    assignment = _assignment(data, day, assignment_id)
    if not assignment:
        return []
    assignment_people = _assignment_people(assignment)
    sheet = (data.get("day_campaign") or {}).get(day) or {}
    chain = _chain(data, day)
    group = group_of(data, day, assignment_id)
    if group:
        # العضو بياخد مركبة وسائق المجموعة؛ بيانات العضو الأصلية بتفضل محفوظة لحد فك التجميع.
        vehicle = _vehicle(data, group.get("vehicle_id"))
        if not vehicle:
            return []
        return [{"vehicle": vehicle, "vehicle_id": vehicle["id"], "plate": vehicle["plate"],
                 "label": fleet.vehicle_label(VehicleRepo(data).find(vehicle["id"])),
                 "people": [person for category, key in (("personnel", "personnel_ids"),
                                                         ("officers", "officer_ids"))
                            for ident in assignment_people[key]
                            for person in [_person_view(data, ident, category)] if person],
                 "source": "group", "group_id": group.get("id"),
                 "driver": _driver(data, group.get("driver"))}]
    result = []
    raw = (sheet.get("services") or {}).get(assignment_id) or {}
    direct_entries = _direct_service_entries(data, day, assignment_id, raw)
    for item in direct_entries:
        vehicle = _vehicle(data, item.get("vehicle_id"))
        fallback_driver = raw.get("driver") if len(direct_entries) == 1 else None
        driver = _driver(data, item.get("driver") or fallback_driver)
        type_text = str(item.get("type_text") or "").strip()
        group_key, group_label, group_rank = _vehicle_group(
            (vehicle or {}).get("type") or type_text)
        result.append({"vehicle": vehicle, "vehicle_id": vehicle["id"] if vehicle else "",
                       "plate": vehicle["plate"] if vehicle else "",
                       "label": fleet.vehicle_label(VehicleRepo(data).find(vehicle["id"])) if vehicle else "",
                       "type_text": type_text,
                       "vehicle_group": group_key,
                       "vehicle_group_label": group_label,
                       "vehicle_group_rank": group_rank,
                       "people": _vehicle_people(data, item, assignment_people),
                       "source": "direct", "driver": driver})
    for lorry_id, lorry in ((sheet.get("lorries") or {}).items()):
        if not any(item.get("assignment_id") == assignment_id
                   for item in (lorry or {}).get("attached") or []):
            continue
        effective = _merge_inherited(_prior(data, chain, "lorries", lorry_id), lorry)
        vehicle = _vehicle(data, effective.get("vehicle_id"))
        if not vehicle and not include_empty_lorries:
            continue
        group_key, group_label, group_rank = _vehicle_group("لوري" if not vehicle else vehicle.get("type"))
        result.append({"vehicle": vehicle, "vehicle_id": vehicle["id"] if vehicle else "",
                       "plate": vehicle["plate"] if vehicle else "",
                       "label": fleet.vehicle_label(VehicleRepo(data).find(vehicle["id"])) if vehicle else "",
                       "type_text": "" if vehicle else "لوري",
                       "vehicle_group": group_key,
                       "vehicle_group_label": group_label,
                       "vehicle_group_rank": group_rank,
                       "people": [_person_view(data, ident, category)
                                  for category, key in (("personnel", "personnel_ids"),
                                                        ("officers", "officer_ids"))
                                  for ident in assignment_people[key]
                                  if _person_view(data, ident, category)],
                       "source": "lorry", "lorry_id": lorry_id,
                       "lorry_name": next((item["name"] for item in
                                            campaign_lorries_on(data, day) + APPOINTMENT_LORRIES
                                            if item["id"] == lorry_id), lorry_id),
                       "driver": _driver(data, effective.get("driver"))})
    return result


def _validate_driver(data, value):
    if value in (None, ""):
        return None, None
    if not isinstance(value, dict):
        return None, "السائق غير صحيح."
    kind = value.get("kind")
    if kind not in {"personnel", "conscript", "text"}:
        return None, "نوع السائق غير صحيح."
    if kind == "text":
        name = str(value.get("name") or "").strip()
        if not name:
            return None, "اسم السائق مطلوب."
        if len(name) > 200:
            return None, "اسم السائق أطول من الحد المسموح (200 حرف)."
        return {"kind": "text", "id": "", "name": name}, None
    ident = str(value.get("id") or "").strip()
    if kind == "personnel":
        raw, category, _ = PeopleRepo(data).locate(ident)
        if raw is None or category != "personnel":
            return None, "الفرد السائق غير موجود."
    elif not ConscriptRepo(data).find(ident):
        return None, "المجند السائق غير موجود."
    return {"kind": kind, "id": ident}, None


def _apply(data, target, payload):
    if "vehicle_id" in payload:
        vid = str(payload.get("vehicle_id") or "").strip()
        if vid and not VehicleRepo(data).find(vid):
            return "المركبة غير موجودة."
        target["vehicle_id"] = vid
    if "driver" in payload:
        value, error = _validate_driver(data, payload.get("driver"))
        if error:
            return error
        target["driver"] = value or {}
    if "type_text" in payload:
        value = str(payload.get("type_text") or "").strip()
        if len(value) > 200:
            return "نص نوع المركبة أطول من الحد المسموح (200 حرف)."
        target["type_text"] = value
    return None


def _validate_service_vehicles(data, day, assignment_id, values):
    if not isinstance(values, list):
        return None, "قائمة مركبات الخدمة غير صحيحة."
    assignment = _assignment(data, day, assignment_id)
    allowed = _assignment_people(assignment)
    allowed_all = {"personnel": set(allowed["personnel_ids"]),
                   "officers": set(allowed["officer_ids"])}
    seen_people, cleaned = set(), []
    for item in values:
        if not isinstance(item, dict):
            return None, "بيانات مركبة الخدمة غير صحيحة."
        vehicle_id = str(item.get("vehicle_id") or "").strip()
        if vehicle_id and not VehicleRepo(data).find(vehicle_id):
            return None, "المركبة غير موجودة."
        clean = {"vehicle_id": vehicle_id}
        if "type_text" in item:
            type_text = str(item.get("type_text") or "").strip()
            if len(type_text) > 200:
                return None, "نص نوع المركبة أطول من الحد المسموح (200 حرف)."
            clean["type_text"] = type_text
        for category, key in (("personnel", "personnel_ids"), ("officers", "officer_ids")):
            ids = item.get(key) or []
            if not isinstance(ids, list):
                return None, "قائمة أفراد المركبة غير صحيحة."
            ids = list(dict.fromkeys(str(value).strip() for value in ids if str(value).strip()))
            if any(ident not in allowed_all[category] for ident in ids):
                return None, "الشخص المحدد ليس ضمن أفراد الخدمة."
            if any(ident in seen_people for ident in ids):
                return None, "لا يمكن توزيع الشخص على أكثر من مركبة في الخدمة."
            seen_people.update(ids)
            if ids:
                clean[key] = ids
        if "driver" in item:
            driver, error = _validate_driver(data, item.get("driver"))
            if error:
                return None, error
            if driver:
                clean["driver"] = driver
        cleaned.append(clean)
    return cleaned, None


def _post_apply(data, target, payload):
    if "vehicle_id" in payload:
        vid = str(payload.get("vehicle_id") or "").strip()
        if vid and not VehicleRepo(data).find(vid):
            return "المركبة غير موجودة."
        target["vehicle_id"] = vid
    for key in ("driver_text", "plate_text", "type_text"):
        if key in payload:
            value = str(payload.get(key) or "").strip()
            if len(value) > 200:
                return "النص طويل أكثر من اللازم."
            target[key] = value
    return None


def _clean(data, day):
    value = data.get("day_campaign", {}).get(day)
    if not value:
        data.get("day_campaign", {}).pop(day, None)
        return
    for key in ("lorries", "services", "daily"):
        kept = {}
        for ident, entry in (value.get(key) or {}).items():
            if not entry:
                continue
            if (entry.get("attached") or "vehicle_id" in entry or "vehicles" in entry
                    or "driver" in entry or "type_text" in entry):
                kept[ident] = entry
        value[key] = kept
    posts = {}
    for ident, entry in (value.get("posts") or {}).items():
        if isinstance(entry, dict) and any(key in entry for key in
                                          ("vehicle_id", "driver_text", "plate_text", "type_text")):
            posts[ident] = entry
    if "posts" in value:
        value["posts"] = posts
    if "plates" in value and isinstance(value.get("plates"), dict):
        value["plates"] = {"rows": value["plates"].get("rows", [])}
    live = {row.get("id") for row in occasional_rows(data, day)}
    value["removed_services"] = [ident for ident in dict.fromkeys(value.get("removed_services") or [])
                                  if ident in live]
    if not value["removed_services"]:
        value.pop("removed_services", None)
    if not any(value.get(k) for k in ("lorries", "services", "daily", "posts", "plates", "groups", "removed_services")):
        data["day_campaign"].pop(day, None)


def remove_service(data, day, assignment_id):
    assignments = {row.get("id"): row for row in occasional_rows(data, day)}
    if assignment_id not in assignments:
        _clean(data, day)
        return "الخدمة غير موجودة في هذا اليوم.", 404
    if group_of(data, day, assignment_id):
        return "الخدمة ضمن مجموعة؛ فك التجميع أولًا", 409
    value = _raw(data, day)
    value["removed_services"] = list(dict.fromkeys(
        [*(value.get("removed_services") or []), assignment_id]))
    _clean(data, day)
    return None, None


def restore_service(data, day, assignment_id):
    if not any(row.get("id") == assignment_id for row in occasional_rows(data, day)):
        _clean(data, day)
        return "الخدمة غير موجودة في هذا اليوم.", 404
    value = _raw(data, day)
    value["removed_services"] = [ident for ident in value.get("removed_services") or []
                                 if ident != assignment_id]
    _clean(data, day)
    return None, None


def set_lorry(data, day, lorry_id, payload):
    if lorry_id not in {x["id"] for x in campaign_lorries_on(data, day) + APPOINTMENT_LORRIES}:
        return "اللوري غير موجود.", 404
    target = _raw(data, day).setdefault("lorries", {}).setdefault(lorry_id, {})
    error = _apply(data, target, payload)
    if error:
        return error, 400
    _clean(data, day)
    return None, None


def set_service(data, day, assignment_id, payload):
    if not any(r.get("id") == assignment_id for r in occasional_rows(data, day)):
        return "الخدمة غير موجودة في هذا اليوم.", 404
    if group_of(data, day, assignment_id):
        return "الخدمة ضمن مجموعة؛ عدّل مركبة المجموعة أو فك التجميع أولًا.", 409
    target = _raw(data, day).setdefault("services", {}).setdefault(assignment_id, {})
    if "vehicles" in payload:
        vehicles, error = _validate_service_vehicles(data, day, assignment_id, payload.get("vehicles"))
        if error:
            return error, 400
        previous = _direct_service_entries(data, day, assignment_id, target)
        if len(vehicles) == 1 and not vehicles[0].get("driver") and "driver" not in payload:
            old_driver = (previous[0].get("driver") if previous else None) or target.get("driver")
            if old_driver:
                vehicles[0]["driver"] = deepcopy(old_driver)
        target.pop("vehicle_id", None)
        target["vehicles"] = vehicles
        if "driver" in payload:
            value, error = _validate_driver(data, payload.get("driver"))
            if error:
                return error, 400
            target["driver"] = value or {}
        elif len(vehicles) == 1:
            target["driver"] = deepcopy(vehicles[0].get("driver") or {})
        else:
            target.pop("driver", None)
        _clean(data, day)
        return None, None

    direct = _direct_service_entries(data, day, assignment_id, target)
    if len(direct) > 1 and "vehicles" not in payload and "vehicle_index" not in payload and any(
            key in payload for key in ("vehicle_id", "driver")):
        return "حدد رقم المركبة لتعديل السطر المطلوب.", 400
    if "vehicle_index" in payload:
        try:
            index = int(payload.get("vehicle_index"))
        except (TypeError, ValueError):
            return "رقم مركبة الخدمة غير صحيح.", 400
        if index < 0 or index > len(direct) or (index == len(direct) and direct):
            return "مركبة الخدمة غير موجودة.", 404
        current = deepcopy(direct)
        if index == 0 and not current:
            current.append({"vehicle_id": "", **_assignment_people(_assignment(data, day, assignment_id))})
        item = current[index]
        if "vehicle_id" in payload:
            vehicle_id = str(payload.get("vehicle_id") or "").strip()
            if vehicle_id and not VehicleRepo(data).find(vehicle_id):
                return "المركبة غير موجودة.", 400
            item["vehicle_id"] = vehicle_id
        if "driver" in payload:
            driver, error = _validate_driver(data, payload.get("driver"))
            if error:
                return error, 400
            if driver:
                item["driver"] = driver
            else:
                item.pop("driver", None)
        vehicles, error = _validate_service_vehicles(data, day, assignment_id, current)
        if error:
            return error, 400
        target.pop("vehicle_id", None)
        target["vehicles"] = vehicles
        _clean(data, day)
        return None, None

    driver = None
    if "driver" in payload:
        driver, error = _validate_driver(data, payload.get("driver"))
        if error:
            return error, 400

    if "vehicle_id" in payload:
        vehicle_id = str(payload.get("vehicle_id") or "").strip()
        if vehicle_id and not VehicleRepo(data).find(vehicle_id):
            return "المركبة غير موجودة.", 400
        current = deepcopy(direct[0]) if direct else {
            **_assignment_people(_assignment(data, day, assignment_id))}
        # لو السائق كان محفوظًا داخل المركبة فقط، ننقله للصف قبل مسح المركبة.
        effective_driver = driver if "driver" in payload else current.get("driver") or target.get("driver")
        if effective_driver:
            target["driver"] = deepcopy(effective_driver)
        elif "driver" in payload:
            target["driver"] = {}
        if vehicle_id:
            current["vehicle_id"] = vehicle_id
            if "driver" in payload:
                if driver:
                    current["driver"] = deepcopy(driver)
                else:
                    current.pop("driver", None)
            target.pop("vehicle_id", None)
            target["vehicles"] = [current]
        else:
            target.pop("vehicle_id", None)
            target["vehicles"] = []
    elif "driver" in payload:
        target["driver"] = deepcopy(driver) if driver else {}
        if direct:
            current = deepcopy(direct[0])
            if driver:
                current["driver"] = deepcopy(driver)
            else:
                current.pop("driver", None)
            target.pop("vehicle_id", None)
            target["vehicles"] = [current]
    _clean(data, day)
    return None, None


# ───────────────────── تجميع الخدمات الطارئة ─────────────────────
# المجموعة بتتخزن في day_campaign[day]["groups"] = [{id, title, members, vehicle_id?, driver?}]
# وهي خاصة بيوم واحد (ما بتتوارثش لليوم التالي). الخدمة في مجموعة واحدة على الأكثر،
# وبيانات الأعضاء الأصلية (services[id]) بتفضل زي ما هي عشان فك التجميع يرجّعها.
MAX_GROUP_TITLE = 200


def day_groups(data, day):
    return ((data.get("day_campaign") or {}).get(day) or {}).get("groups") or []


def group_of(data, day, assignment_id):
    return next((g for g in day_groups(data, day) if assignment_id in (g.get("members") or [])), None)


def _find_group(data, day, group_id):
    return next((g for g in day_groups(data, day) if g.get("id") == group_id), None)


def _group_snapshot(group):
    return deepcopy(group) if group else None


def _clean_ids(values):
    if not isinstance(values, list):
        return None
    return list(dict.fromkeys(str(v).strip() for v in values if str(v).strip()))


def _check_title(title):
    title = " ".join(str(title or "").split())
    if not title:
        return None, "عنوان المجموعة مطلوب."
    if len(title) > MAX_GROUP_TITLE:
        return None, "عنوان المجموعة أطول من الحد المسموح."
    return title, None


def _check_members(data, day, ids, ignore_group=None):
    """الأعضاء لازم خدمات طارئة ظاهرة في اليوم، مش في مجموعة تانية ولا ملحقة بلوري."""
    available = {r.get("id") for r in occasional_rows(data, day)}
    lorry_attached = {item.get("assignment_id")
                      for lorry in ((data.get("day_campaign") or {}).get(day, {}).get("lorries") or {}).values()
                      for item in (lorry or {}).get("attached") or []}
    for ident in ids:
        if ident not in available:
            return "الخدمة غير موجودة في هذا اليوم.", 404
        other = group_of(data, day, ident)
        if other and other is not ignore_group:
            return "الخدمة ضمن مجموعة أخرى بالفعل.", 409
        if ident in lorry_attached:
            return "الخدمة ملحقة بلوري؛ أزل الإلحاق أولًا.", 409
    return None, None


def _seed_group(data, day, members):
    """المجموعة الجديدة بتبدأ بمركبة وسائق أول عضو عنده تسكين (نسخة، من غير ما نمسّ الأعضاء)."""
    services = (data.get("day_campaign") or {}).get(day, {}).get("services") or {}
    for ident in members:
        raw = services.get(ident) or {}
        entries = _direct_service_entries(data, day, ident, raw)
        if entries and entries[0].get("vehicle_id"):
            seed = {"vehicle_id": str(entries[0]["vehicle_id"])}
            driver = entries[0].get("driver") or raw.get("driver")
            if driver:
                seed["driver"] = deepcopy(driver)
            return seed
    return {}


def create_group(data, day, title, members, out=None):
    title, error = _check_title(title)
    if error:
        return error, 400
    ids = _clean_ids(members)
    if ids is None:
        return "قائمة الخدمات غير صحيحة.", 400
    if len(ids) < 2:
        return "اختر خدمتين على الأقل للتجميع.", 400
    error, status = _check_members(data, day, ids)
    if error:
        return error, status
    existing = [{"id": g.get("id")} for sheet in (data.get("day_campaign") or {}).values()
                for g in (sheet or {}).get("groups") or []]
    group = {"id": reserve_id(data, "CG", existing), "title": title, "members": ids,
             **_seed_group(data, day, ids)}
    _raw(data, day).setdefault("groups", []).append(group)
    if out is not None:
        out["group_id"] = group["id"]
    changes.record(data, "campaign_group", group["id"], "create", after=_group_snapshot(group), day=day,
                   text=f"تجميع {len(ids)} خدمات في «{title}»")
    return None, None


def update_group(data, day, group_id, body):
    """إعادة تسمية وإضافة/إزالة أعضاء: title / add / remove."""
    group = _find_group(data, day, group_id)
    if not group:
        return "المجموعة غير موجودة.", 404
    before = _group_snapshot(group)
    members = list(group.get("members") or [])
    title = group.get("title", "")
    if "title" in body:
        title, error = _check_title(body.get("title"))
        if error:
            return error, 400
    add, remove = _clean_ids(body.get("add") or []), _clean_ids(body.get("remove") or [])
    if add is None or remove is None:
        return "قائمة الخدمات غير صحيحة.", 400
    if any(ident not in members for ident in remove):
        return "الخدمة ليست ضمن المجموعة.", 404
    add = [ident for ident in add if ident not in members]
    error, status = _check_members(data, day, add, ignore_group=group)
    if error:
        return error, status
    members = [m for m in members if m not in remove] + add
    if len(members) < 2:
        return "المجموعة لا تقل عن خدمتين؛ استخدم «فك التجميع» بدلًا من ذلك.", 400
    group["title"], group["members"] = title, members
    changes.record(data, "campaign_group", group_id, "update", before=before,
                   after=_group_snapshot(group), day=day, text=f"تعديل المجموعة «{title}»")
    return None, None


def set_group(data, day, group_id, payload):
    """مركبة وسائق المجموعة (نفس شكل PUT للخدمة)."""
    group = _find_group(data, day, group_id)
    if not group:
        return "المجموعة غير موجودة.", 404
    before = _group_snapshot(group)
    error = _apply(data, group, {k: v for k, v in payload.items()
                                 if k in ("vehicle_id", "driver", "type_text")})
    if error:
        return error, 400
    for key in ("vehicle_id", "driver", "type_text"):
        if key in group and not group[key]:
            del group[key]
    changes.record(data, "campaign_group", group_id, "assign", before=before,
                   after=_group_snapshot(group), day=day, text=f"تسكين المجموعة «{group.get('title', '')}»")
    return None, None


def ungroup(data, day, group_id):
    sheet = (data.get("day_campaign") or {}).get(day) or {}
    group = _find_group(data, day, group_id)
    if not group:
        return "المجموعة غير موجودة.", 404
    sheet["groups"] = [g for g in sheet["groups"] if g.get("id") != group_id]
    changes.record(data, "campaign_group", group_id, "delete", before=_group_snapshot(group), day=day,
                   text=f"فك تجميع «{group.get('title', '')}»")
    _clean(data, day)
    return None, None


def set_daily(data, day, row_id, payload):
    if row_id not in {x["id"] for x in campaign_daily_on(data, day)}:
        return "القول اليومي غير موجود.", 404
    target = _raw(data, day).setdefault("daily", {}).setdefault(row_id, {})
    if "basic_entry_id" in payload:
        linked, error = _resolve_basic_entry(data, day, payload.get("basic_entry_id"), target.get("name"))
        if error:
            return error, 400
        target["basic_entry_id"] = linked
    error = _apply(data, target, payload)
    if error:
        return error, 400
    _clean(data, day)
    return None, None


def attach_service(data, day, lorry_id, item):
    if lorry_id not in {x["id"] for x in campaign_lorries_on(data, day) + APPOINTMENT_LORRIES}:
        return "اللوري غير موجود.", 404
    assignment_id = str(item.get("assignment_id") or "").strip()
    name = str(item.get("name") or "").strip()
    if assignment_id:
        row = next((r for r in occasional_rows(data, day) if r.get("id") == assignment_id), None)
        if not row:
            return "الخدمة غير موجودة في هذا اليوم.", 404
        if group_of(data, day, assignment_id):
            return "الخدمة ضمن مجموعة؛ فك التجميع أولًا لإلحاقها بلوري.", 409
        for other_id, value in ((_raw(data, day).get("lorries") or {}).items()):
            if other_id != lorry_id and any(item.get("assignment_id") == assignment_id
                                             for item in value.get("attached") or []):
                return "الخدمة ملحقة بلوري آخر في هذا اليوم.", 409
        entry = {"assignment_id": assignment_id}
    elif name:
        entry = {"name": name}
    else:
        return "حدد التكليف أو اسم الخدمة.", 400
    value = _raw(data, day).setdefault("lorries", {}).setdefault(lorry_id, {})
    attached = value.setdefault("attached", [])
    if entry not in attached:
        attached.append(entry)
    return None, None


def detach_service(data, day, lorry_id, item):
    value = (data.get("day_campaign") or {}).get(day, {}).get("lorries", {}).get(lorry_id)
    if lorry_id not in {x["id"] for x in campaign_lorries_on(data, day) + APPOINTMENT_LORRIES}:
        return "اللوري غير موجود.", 404
    if not value:
        return "الخدمة الملحقة غير موجودة.", 404
    aid, name = str(item.get("assignment_id") or "").strip(), str(item.get("name") or "").strip()
    before = len(value.get("attached") or [])
    value["attached"] = [x for x in value.get("attached") or []
                          if not ((aid and x.get("assignment_id") == aid) or (name and x.get("name") == name))]
    if len(value["attached"]) == before:
        return "الخدمة الملحقة غير موجودة.", 404
    _clean(data, day)
    return None, None


def _resolve_basic_entry(data, day, entry_id, name):
    basics = afraad_basic_on(data, day)
    if entry_id:
        ident = str(entry_id).strip()
        if any(item.get("id") == ident for item in basics):
            return ident, None
        return None, "الخدمة الأساسية المرتبطة غير موجودة في هذا اليوم."
    wanted = norm(name)
    matches = [item for item in basics
               if norm(item.get("name")) == wanted
               or norm(str(name or "").removeprefix("ارتكاز ")) == norm(item.get("name"))]
    return (matches[0]["id"], None) if len(matches) == 1 else ("", None)


def add_daily_row(data, day, name, basic_entry_id=None):
    name = str(name or "").strip()
    if not name:
        return None, "اسم القول مطلوب.", 400
    items = campaign_daily_on(data, day)
    existing = [{"id": i.get("id")} for versions in ((data.get("reference_lists") or {}).get("campaign_daily") or []) for i in versions.get("items") or []]
    ident = reserve_id(data, "CD", existing)
    linked, error = _resolve_basic_entry(data, day, basic_entry_id, name)
    if error:
        return None, error, 400
    item = {"id": ident, "name": name}
    if linked:
        item["basic_entry_id"] = linked
    items.append(item)
    record_campaign_daily_change(data, day, items)
    return ident, None, None


def remove_daily_row(data, day, row_id):
    items = campaign_daily_on(data, day)
    if row_id not in {x["id"] for x in items}:
        return "القول اليومي غير موجود.", 404
    record_campaign_daily_change(data, day, [x for x in items if x["id"] != row_id])
    sheet = (data.get("day_campaign") or {}).get(day)
    if sheet:
        (sheet.get("daily") or {}).pop(row_id, None)
        _clean(data, day)
    return None, None


def add_lorry(data, day, name):
    name = str(name or "").strip()
    if not name:
        return None, "اسم اللوري مطلوب.", 400
    if len(name) > 120:
        return None, "اسم اللوري أطول من الحد المسموح (120 حرف).", 400
    items = campaign_lorries_on(data, day)
    if any(norm(item.get("name")) == norm(name) for item in items):
        return None, "اسم اللوري موجود بالفعل.", 400
    existing = [item for version in ((data.get("reference_lists") or {}).get("campaign_lorries") or []) for item in version.get("items") or []]
    existing += CAMPAIGN_LORRIES + APPOINTMENT_LORRIES
    ident = reserve_id(data, "LOR", existing)
    items.append({"id": ident, "name": name})
    remember_campaign_lorry(data, {"id": ident, "name": name})
    record_campaign_lorries_change(data, day, items)
    changes.record(data, "campaign_lorry", ident, "create", after={"id": ident, "name": name}, day=day,
                   text=f"إضافة لوري «{name}» إلى يومية الحملة من يوم {day}")
    return ident, None, None


def remove_lorry(data, day, lorry_id):
    items = campaign_lorries_on(data, day)
    item = next((row for row in items if row["id"] == lorry_id), None)
    if not item:
        return "اللوري غير موجود.", 404
    record_campaign_lorries_change(data, day, [row for row in items if row["id"] != lorry_id])
    sheet = (data.get("day_campaign") or {}).get(day) or {}
    raw = (sheet.get("lorries") or {}).pop(lorry_id, None)
    # فك الارتباط يزيل مرجع الخدمة من اللوري؛ بيانات الخدمة المحفوظة تفضل كما هي.
    _clean(data, day)
    changes.record(data, "campaign_lorry", lorry_id, "delete", before=dict(item), day=day,
                   text=f"حذف لوري «{item['name']}» من يومية الحملة من يوم {day}")
    return None, None


def add_post(data, day, name, number=None, driver_text=None):
    name = str(name or "").strip()
    if not name:
        return None, "اسم الارتكاز مطلوب.", 400
    if len(name) > 200 or len(str(number or "").strip()) > 20 or len(str(driver_text or "").strip()) > 200:
        return None, "بيانات الارتكاز أطول من الحد المسموح.", 400
    items = campaign_posts_on(data, day)
    existing = [{"id": item.get("id")} for versions in
                ((data.get("reference_lists") or {}).get("campaign_posts") or [])
                for item in versions.get("items") or []]
    ident = reserve_id(data, "CP", existing)
    if number is None or str(number).strip() == "":
        labels = []
        for item in items:
            match = str(item.get("number") or "").strip().rstrip(".")
            if match.isdigit():
                labels.append(int(match))
        number = f"{max(labels or [0]) + 1}."
    item = {"id": ident, "number": str(number).strip(), "name": name,
            "driver_text": str(driver_text or "").strip()}
    items.append(item)
    record_campaign_posts_change(data, day, items)
    return ident, None, None


def update_post(data, day, post_id, name, number=None):
    """يعدّل بيانات الارتكاز ابتداءً من اليوم المحدد مع إبقاء الأيام السابقة كما هي."""
    name = str(name or "").strip()
    number = str(number or "").strip()
    if not name:
        return "اسم الارتكاز مطلوب.", 400
    if len(name) > 200 or len(number) > 20:
        return "بيانات الارتكاز أطول من الحد المسموح.", 400
    items = campaign_posts_on(data, day)
    target = next((item for item in items if item.get("id") == post_id), None)
    if target is None:
        return "الارتكاز غير موجود.", 404
    target["name"] = name
    target["number"] = number
    record_campaign_posts_change(data, day, items)
    return None, None


def remove_post(data, day, post_id):
    items = campaign_posts_on(data, day)
    if post_id not in {item.get("id") for item in items}:
        return "الارتكاز غير موجود.", 404
    record_campaign_posts_change(data, day, [item for item in items if item.get("id") != post_id])
    sheet = (data.get("day_campaign") or {}).get(day)
    if sheet:
        (sheet.get("posts") or {}).pop(post_id, None)
        _clean(data, day)
    return None, None


def set_post(data, day, post_id, payload):
    if post_id not in {item.get("id") for item in campaign_posts_on(data, day)}:
        return "الارتكاز غير موجود.", 404
    target = _raw(data, day).setdefault("posts", {}).setdefault(post_id, {})
    error = _post_apply(data, target, payload)
    if error:
        return error, 400
    _clean(data, day)
    return None, None


def set_plates(data, day, rows):
    if not isinstance(rows, list) or len(rows) > 6:
        return "سجل اللوحات لا يزيد عن 6 صفوف.", 400
    cleaned = []
    for row in rows:
        if not isinstance(row, list) or len(row) > 12:
            return "كل صف في سجل اللوحات لا يزيد عن 12 خانة.", 400
        values = [str(cell or "").strip() for cell in row]
        if any(len(cell) > 40 for cell in values):
            return "نص اللوحة لا يزيد عن 40 حرفًا.", 400
        values = [cell for cell in values if cell]
        if values:
            cleaned.append(values)
    _raw(data, day)["plates"] = {"rows": cleaned}
    _clean(data, day)
    return None, None


def _merge_inherited(previous_entry, current_entry):
    previous_entry = previous_entry or {}
    current_entry = current_entry or {}
    merged = {
        key: deepcopy(previous_entry[key])
        for key in ("vehicle_id", "driver", "driver_text", "plate_text", "type_text", "basic_entry_id")
        if key in previous_entry
    }
    vehicle_fields = ("vehicle_id", "plate_text", "type_text")
    if any(key in current_entry for key in vehicle_fields):
        for key in vehicle_fields:
            merged.pop(key, None)
    for key in ("vehicle_id", "driver", "driver_text", "plate_text", "type_text", "basic_entry_id"):
        if key in current_entry:
            merged[key] = deepcopy(current_entry[key])
    if "vehicles" in previous_entry:
        merged["vehicles"] = deepcopy(previous_entry["vehicles"])
    if "vehicles" in current_entry:
        merged["vehicles"] = deepcopy(current_entry["vehicles"])
    if "attached" in current_entry:
        merged["attached"] = deepcopy(current_entry["attached"])
    return merged


def _inherited(previous_entry, current_entry, previous_day):
    if not previous_day:
        return False
    previous_entry = previous_entry or {}
    current_entry = current_entry or {}
    vehicle_keys = ("vehicle_id", "plate_text", "type_text")
    return (any(key in previous_entry for key in vehicle_keys)
            and not any(key in current_entry for key in vehicle_keys)) or any(
                key in previous_entry and key not in current_entry
                for key in ("vehicles", "driver", "driver_text"))


def _inherited_from(sources, current_entry):
    """يوم المصدر لكل قيمة ظاهرة موروثة، بأسماء حقول مفهومة للواجهة."""
    current_entry = current_entry or {}
    result = {}
    vehicle_set = {"vehicles", "vehicle_id", "plate_text", "type_text"}
    vehicle_set_here = bool(vehicle_set.intersection(current_entry))
    groups = {
        "vehicle": ("vehicles", "vehicle_id"),
        "driver": ("driver", "driver_text"),
        "plate": ("plate_text",),
        "type": ("type_text",),
    }
    for label, keys in groups.items():
        if label in {"vehicle", "plate", "type"} and vehicle_set_here:
            continue
        if any(key in current_entry for key in keys):
            continue
        dated = [(sources[key], index) for index, key in enumerate(keys) if key in sources]
        if dated:
            result[label] = max(dated)[0]
    return result


def _attached_rows(raw, assignments):
    attached = []
    for item in raw.get("attached") or []:
        assignment_id = item.get("assignment_id")
        if assignment_id:
            assignment = assignments.get(assignment_id) or {}
            name = assignment.get("name") or assignment.get("label") or assignment_id
            attached.append({"assignment_id": assignment_id, "name": name})
        else:
            attached.append({"name": item.get("name", "")})
    return attached


def _row_view(data, ident, kind, name, raw, inherited, attached=None, assignment=None, day=None,
              inherited_from=None):
    direct = _direct_service_entries(data, day, ident, raw) if kind == "service" else []
    direct_view = []
    for item in direct:
        vehicle = _vehicle(data, item.get("vehicle_id"))
        type_text = str(item.get("type_text") or "").strip()
        group_key, group_label, group_rank = _vehicle_group(
            (vehicle or {}).get("type") or type_text)
        direct_view.append({"vehicle": vehicle,
                            "vehicle_id": vehicle["id"] if vehicle else "",
                            "type_text": type_text,
                            "vehicle_group": group_key,
                            "vehicle_group_label": group_label,
                            "vehicle_group_rank": group_rank,
                            "personnel_ids": list(item.get("personnel_ids") or []),
                            "officer_ids": list(item.get("officer_ids") or []),
                            "driver": _driver(data, item.get("driver") or
                                              (raw.get("driver") if len(direct) == 1 else None))})
    inline_driver = raw.get("driver")
    if kind == "service" and len(direct) == 1:
        inline_driver = direct[0].get("driver") or inline_driver
    row_vehicle = (_vehicle(data, raw.get("vehicle_id")) or
                   ((direct_view[0] or {}).get("vehicle") if direct_view else None))
    return {
        "id": ident,
        "kind": kind,
        "name": name,
        "base_name": name.split(" + ", 1)[0],
        "attached": attached if kind == "lorry" else [],
        "driver": _driver(data, inline_driver),
        "vehicle": row_vehicle,
        "plate_text": "" if row_vehicle else raw.get("plate_text", ""),
        "type_text": "" if row_vehicle else raw.get("type_text", ""),
        "vehicles": direct_view,
        "people": [{"id": person.get("id"), "name": person.get("name", ""),
                    "role": person.get("role", ""), "category": "personnel"}
                   for person in (assignment or {}).get("personnel", [])]
                  + [{"id": person.get("id"), "name": person.get("name", ""),
                     "role": person.get("role", ""), "category": "officers"}
                     for person in (assignment or {}).get("officers", [])],
        "time": (assignment or {}).get("time", ""),
        "party": (assignment or {}).get("party", ""),
        "inherited": inherited,
        "inherited_from": inherited_from or {},
        "warnings": [],
    }


def _status_text(state, missing):
    if state == "complete":
        return "متسكن"
    if state == "optional":
        return "اختياري"
    if missing == ["driver"]:
        return "ناقص سائق"
    if missing == ["vehicle"]:
        return "ناقص مركبة"
    return "غير متسكن"


def _set_status(row, state, missing=None, text=None):
    missing = list(missing or [])
    row["status"] = state
    row["missing"] = missing
    row["status_text"] = text or _status_text(state, missing)


def _regular_status(row, *, driver_only=False, optional=False):
    has_driver = bool(row.get("driver"))
    has_vehicle = bool(row.get("vehicle"))
    has_content = (has_driver or has_vehicle or bool(row.get("attached"))
                   or bool(str(row.get("type_text") or "").strip()))
    if optional and not has_content:
        _set_status(row, "optional")
        return
    missing = ([] if has_driver else ["driver"])
    if not driver_only and not has_vehicle:
        missing.append("vehicle")
    state = "complete" if not missing else ("partial" if has_content else "empty")
    _set_status(row, state, missing)


def _service_status(row):
    vehicles = row.get("service_vehicles") or []
    direct = [item for item in vehicles if item.get("source") == "direct"]
    carried = [item for item in vehicles if item.get("source") == "lorry"]
    complete_carrier = next((item for item in carried
                             if item.get("vehicle") and item.get("driver")), None)
    if complete_carrier:
        _set_status(row, "complete", text=f"على لوري {complete_carrier.get('lorry_name', '')}".strip())
        return
    if direct and all(item.get("vehicle") and item.get("driver") for item in direct):
        _set_status(row, "complete")
        return

    missing = []
    if direct:
        for index, item in enumerate(direct, 1):
            fields = []
            if not item.get("driver"):
                fields.append("driver")
            if not item.get("vehicle"):
                fields.append("vehicle")
            if fields:
                missing.extend([f"{field}:{index}" for field in fields])
    if carried:
        carrier = carried[0]
        if not carrier.get("driver") and "driver" not in missing:
            missing.append("driver")
        if not carrier.get("vehicle"):
            missing.append("vehicle")
        reason = _status_text("partial", missing)
        _set_status(row, "partial", missing,
                    f"على لوري {carrier.get('lorry_name', '')} — {reason}".strip())
        return
    if not direct:
        if not row.get("driver"):
            missing.append("driver")
        missing.append("vehicle")
    has_content = any(item.get("vehicle") or item.get("driver") or item.get("type_text")
                      for item in direct) or bool(row.get("driver"))
    labels = {"driver": "سائق", "vehicle": "مركبة"}
    line_missing = {}
    for value in missing:
        if ":" in value:
            field, index = value.split(":", 1)
            line_missing.setdefault(int(index), []).append(field)
    if len(direct) == 1:
        fields = line_missing.get(1, [])
        text = "ناقص " + " و".join(labels[field] for field in ("driver", "vehicle")
                                  if field in fields) if fields else ""
    else:
        text = " — ".join(
            f"المركبة {index}: ناقص " + " و".join(
                labels[field] for field in ("driver", "vehicle") if field in fields)
            for index, fields in sorted(line_missing.items()))
    _set_status(row, "partial" if has_content else "empty", missing, text or None)


def _post_status(row):
    has_driver = bool(str(row.get("driver_text") or "").strip())
    has_vehicle = bool(row.get("vehicle") or str(row.get("plate_text") or "").strip())
    missing = ([] if has_driver else ["driver"]) + ([] if has_vehicle else ["vehicle"])
    has_content = has_driver or has_vehicle or bool(str(row.get("type_text") or "").strip())
    _set_status(row, "complete" if not missing else ("partial" if has_content else "empty"), missing)


def _summary(rows):
    counts = {state: 0 for state in ("complete", "partial", "empty", "optional")}
    for row in rows:
        counts[row["status"]] += 1
    counts["missing"] = counts["partial"] + counts["empty"]
    counts["total"] = counts["complete"] + counts["missing"]
    return counts


def _service_vehicle(row):
    vehicles = row.get("service_vehicles") or []
    return (vehicles[0].get("vehicle") if vehicles else None) or row.get("vehicle")


CAMPAIGN_BAND_LABELS = {
    "lorry": "لواري",
    "bus": "أتوبيس",
    "micro": "ميكروباص",
    "pickup": "بيك اب",
    "other": "أخرى",
    "missing": "بدون مركبة",
    "security": "الأقوال الأمنية",
    "ambulance": "الإسعاف",
    "driver_only": "سائق بورتوفيق",
}


def _vehicle_type_text(row):
    """نوع المركبة الفعلي أو المطلوب للصف، بما فيه سطر خدمة بلا لوحة بعد."""
    candidates = []
    if isinstance(row, dict):
        candidates.append(row)
        for key in ("service_vehicles", "_vehicle_lines", "vehicles"):
            candidates.extend(row.get(key) or [])
    for item in candidates:
        if not isinstance(item, dict):
            continue
        vehicle = item.get("vehicle") or {}
        value = vehicle.get("type") or item.get("type_text")
        if str(value or "").strip():
            return str(value).strip()
    # صف اللوري نفسه يحمل نوعه الدلالي حتى قبل اختيار لوحة؛ أما الخدمة/القول
    # العام بلا نوع فيظل «غير محدد» ويذهب لآخر المجموعة.
    if isinstance(row, dict) and (row.get("kind") == "lorry" or row.get("_lorry")):
        return "لوري"
    return ""


def _vehicle_group(value):
    """مفتاح/عنوان تجميع ثابتين؛ اختلافات الكتابة لا تصنع مجموعتين."""
    value = str(value or "").strip()
    if not value:
        return "missing", "غير محدد", 99
    key = norm(value)
    category = fleet.vehicle_category(value)
    return f"type:{key}", value, fleet.CATEGORY_RANK.get(category, 4)


def _vehicle_group_subkey(row, type_text):
    """ترتيب فرعي يحافظ على تجاور كل لوري مع خدماته المحمولة القديمة."""
    if fleet.vehicle_category(type_text) != "lorry":
        return ""
    candidates = [row]
    if isinstance(row, dict):
        for key in ("service_vehicles", "_vehicle_lines", "vehicles"):
            candidates.extend(row.get(key) or [])
    for item in candidates:
        if isinstance(item, dict):
            vehicle = item.get("vehicle") or {}
            if vehicle.get("id"):
                return f"vehicle:{vehicle['id']}"
    return f"row:{(row or {}).get('id') or (row or {}).get('name') or ''}"


def order_campaign_vehicle_rows(rows):
    """يرتب أي قائمة مركبات حسب النوع مع الحفاظ على ترتيب الظهور داخل النوع.

    ``type_text`` مقصود هنا: الصف ذو النوع المطلوب فقط يسبق الصفوف غير المحددة
    حتى قبل اختيار اللوحة أو السائق. الصفوف بلا نوع تذهب دائمًا إلى النهاية.
    """
    rows = list(rows or [])
    entries = []
    first_seen = {}
    subgroup_seen = {}
    counts = {}
    for index, row in enumerate(rows):
        type_text = _vehicle_type_text(row)
        key, label, rank = _vehicle_group(type_text)
        subgroup = _vehicle_group_subkey(row, type_text)
        first_seen.setdefault(key, index)
        subgroup_seen.setdefault((key, subgroup), index)
        counts[key] = counts.get(key, 0) + 1
        entries.append((row, key, label, rank, subgroup, index))
    entries.sort(key=lambda item: (item[3], first_seen[item[1]],
                                   subgroup_seen[(item[1], item[4])], item[5]))
    result = []
    for row, key, label, _rank, _subgroup, _index in entries:
        result.append({**row, "vehicle_group": key, "vehicle_group_label": label,
                       "vehicle_group_count": counts[key],
                       "vehicle_group_subkey": _subgroup,
                       "vehicle_group_rank": _rank,
                       "vehicle_group_category": ("missing" if key == "missing"
                                                   else fleet.vehicle_category(_vehicle_type_text(row))),
                       "band": key, "band_label": f"{label} ({counts[key]})"})
    for index, row in enumerate(result):
        previous = result[index - 1] if index else None
        row["break_before"] = bool(previous and (
            row["vehicle_group_category"] != previous["vehicle_group_category"]
            or (row["vehicle_group_category"] == previous["vehicle_group_category"] == "lorry"
                and row["vehicle_group_subkey"]
                and row["vehicle_group_subkey"] != previous["vehicle_group_subkey"])))
        next_row = result[index + 1] if index + 1 < len(result) else None
        row["break_after"] = bool(index + 1 < len(result)
                                   and (row["vehicle_group_category"] != next_row["vehicle_group_category"]
                                        or (row["vehicle_group_category"] == next_row["vehicle_group_category"] == "lorry"
                                            and row["vehicle_group_subkey"]
                                            and row["vehicle_group_subkey"] != next_row["vehicle_group_subkey"])))
    return result


def is_driver_only_daily(row):
    """الصف اليومي الذي يحتاج سائقًا فقط؛ مستخدمة في الحالة والترتيب والتصدير."""
    return norm((row or {}).get("name")).startswith(norm("سائق"))


def order_campaign_rows(delivery_rows, daily_rows):
    """ترتيب خطوط السير والأقوال النهائي المشترك بين الصفحة وملف Word.

    كل عنصر راجع يحمل ``band`` و``band_label``، و``break_before`` للفاصل السميك
    بين فئات المركبات، وبين كل لوري، وقبل الأقوال والإسعاف وسائق بورتوفيق.
    """
    result = order_campaign_vehicle_rows(delivery_rows)
    # ``band`` يظل متوافقًا مع مستهلكي API الأقدم (فئة المركبة)، بينما
    # ``vehicle_group`` هو المفتاح الأدق الذي تستخدمه الصفحة للفصل بين نوعين
    # مختلفين داخل الفئة نفسها.
    for row in result:
        row["band"] = ("missing" if row["vehicle_group"] == "missing"
                       else fleet.vehicle_category(_vehicle_type_text(row)))

    daily_bands = (
        ("security", lambda row: not is_driver_only_daily(row)
         and norm("اسعاف") not in norm(row.get("name"))),
        ("ambulance", lambda row: not is_driver_only_daily(row)
         and norm("اسعاف") in norm(row.get("name"))),
        ("driver_only", is_driver_only_daily),
    )
    for band, predicate in daily_bands:
        rows = [row for row in daily_rows if predicate(row)]
        daily_counts = {}
        for row in rows:
            key = row.get("vehicle_group", "missing")
            daily_counts[key] = daily_counts.get(key, 0) + 1
        for index, row in enumerate(rows):
            result.append({**row, "band": band,
                           "vehicle_group_count": daily_counts.get(row.get("vehicle_group", "missing"), 1),
                           "band_label": f"{row.get('vehicle_group_label', 'غير محدد')} "
                                         f"({daily_counts.get(row.get('vehicle_group', 'missing'), 1)})",
                           "break_before": index == 0 and bool(result)})
    for index, row in enumerate(result):
        row["break_after"] = bool(index + 1 < len(result) and result[index + 1]["break_before"])
    return result


def order_services(rows):
    """يرتب خدمات التوصيل حسب نوع المركبة الفعلي أو المطلوب."""
    ordered = order_campaign_vehicle_rows(rows)
    for row in ordered:
        row["vehicle_category"] = fleet.vehicle_category(_vehicle_type_text(row)) if _vehicle_type_text(row) else "other"
        row["category_break"] = row["break_after"]
    return ordered


def build_campaign(data, day):
    current = (data.get("day_campaign") or {}).get(day) or {}
    chain = _chain(data, day)
    previous_day = chain[-1] if chain else None
    current_lorries = current.get("lorries") or {}
    specs = campaign_lorries_on(data, day) + APPOINTMENT_LORRIES
    previous_lorry_details = {
        spec["id"]: _prior_with_sources(data, chain, "lorries", spec["id"])
        for spec in specs}
    previous_lorries = {ident: details[0] for ident, details in previous_lorry_details.items()}
    previous_lorry_sources = {ident: details[1] for ident, details in previous_lorry_details.items()}
    lorry_data = {
        spec["id"]: _merge_inherited(previous_lorries[spec["id"]], current_lorries.get(spec["id"]))
        for spec in specs
    }

    daily_items = campaign_daily_on(data, day)
    basic_items = afraad_basic_on(data, day)
    basic_by_id = {item["id"]: item for item in basic_items}
    current_daily = current.get("daily") or {}

    assignments = {row.get("id"): row for row in occasional_rows(data, day)}
    removed_ids = set(current.get("removed_services") or [])
    live_assignment_ids = set(assignments)
    removed_ids.intersection_update(live_assignment_ids)
    if removed_ids != set(current.get("removed_services") or []):
        current["removed_services"] = sorted(removed_ids)
    attached_ids = {
        item.get("assignment_id")
        for value in lorry_data.values()
        for item in value.get("attached") or []
        if item.get("assignment_id") not in removed_ids
    }
    rows_l = []
    for spec in campaign_lorries_on(data, day):
        raw = lorry_data[spec["id"]]
        # عنصر الإلحاق مفتاحه assignment_id (مش id): الخدمة المزالة من اليومية مابتفضلش في اسم اللوري
        attached = [item for item in _attached_rows(raw, assignments)
                    if item.get("assignment_id") not in removed_ids]
        suffix = " + " + " + ".join(item["name"] for item in attached if item.get("name")) if attached else ""
        rows_l.append(_row_view(
            data, spec["id"], "lorry", spec["name"] + suffix, raw,
            _inherited(previous_lorries.get(spec["id"]), current_lorries.get(spec["id"]), previous_day),
            attached,
            inherited_from=_inherited_from(previous_lorry_sources.get(spec["id"]),
                                             current_lorries.get(spec["id"])),
        ))

    rows_a = []
    for spec in APPOINTMENT_LORRIES:
        raw = lorry_data[spec["id"]]
        # عنصر الإلحاق مفتاحه assignment_id (مش id): الخدمة المزالة من اليومية مابتفضلش في اسم اللوري
        attached = [item for item in _attached_rows(raw, assignments)
                    if item.get("assignment_id") not in removed_ids]
        suffix = " + " + " + ".join(item["name"] for item in attached if item.get("name")) if attached else ""
        rows_a.append(_row_view(
            data, spec["id"], "lorry", spec["name"] + suffix, raw,
            _inherited(previous_lorries.get(spec["id"]), current_lorries.get(spec["id"]), previous_day),
            attached,
            inherited_from=_inherited_from(previous_lorry_sources.get(spec["id"]),
                                             current_lorries.get(spec["id"])),
        ))

    rows_s = []
    service_rows = []
    grouped_ids = {mid for group in current.get("groups") or [] for mid in group.get("members") or []}
    for assignment in assignments.values():
        if assignment["id"] in removed_ids:
            continue
        if assignment["id"] in grouped_ids:
            continue
        raw = (current.get("services") or {}).get(assignment["id"], {})
        has_direct = bool(_direct_service_entries(data, day, assignment["id"], raw))
        row = _row_view(
            data, assignment["id"], "service",
            assignment.get("name") or assignment.get("label") or "", raw, False,
            assignment=assignment, day=day,
        )
        row["service_vehicles"] = order_campaign_vehicle_rows(
            service_vehicles(data, day, row["id"], include_empty_lorries=True))
        carrier = next((item for item in row["service_vehicles"] if item.get("source") == "lorry"), None)
        if carrier:
            carrier_sources = _inherited_from(
                previous_lorry_sources.get(carrier.get("lorry_id")),
                current_lorries.get(carrier.get("lorry_id")))
            row["inherited_from"] = carrier_sources
            row["inherited"] = bool(carrier_sources)
        service_rows.append(row)
        # ``services`` يفضل متوافقًا مع التصدير والمستهلكين القدامى: الخدمة
        # المحمولة فقط ممثلة بالفعل داخل اسم اللوري في ملف الأرشيف.
        if assignment.get("id") not in attached_ids or has_direct:
            rows_s.append(row)
    for group in current.get("groups") or []:
        members = [assignments[mid] for mid in group.get("members") or [] if mid in assignments]
        if not members:
            continue
        row = _row_view(data, group["id"], "group", group.get("title", ""), group, False, day=day)
        row["base_name"] = row["name"]
        row["members"] = [{"id": m["id"], "name": m.get("name") or m.get("label") or ""} for m in members]
        row["people"] = []
        vehicle = row["vehicle"]
        row["service_vehicles"] = order_campaign_vehicle_rows(
            ([{"vehicle": vehicle, "vehicle_id": vehicle["id"],
               "driver": row["driver"], "source": "group"}] if vehicle else []))
        rows_s.append(row)
        service_rows.append(row)
    service_rows = order_services(service_rows)
    visible_ids = {row["id"] for row in rows_s}
    rows_s = [row for row in service_rows if row["id"] in visible_ids]

    previous_daily_details = {
        item["id"]: _prior_with_sources(data, chain, "daily", item["id"])
        for item in daily_items}
    previous_daily = {ident: details[0] for ident, details in previous_daily_details.items()}
    previous_daily_sources = {ident: details[1] for ident, details in previous_daily_details.items()}
    daily_data = {
        item["id"]: _merge_inherited(previous_daily.get(item["id"]), current_daily.get(item["id"]))
        for item in daily_items
    }

    rows_d = [
        _row_view(
            data, item["id"], "daily", item["name"], daily_data[item["id"]],
            _inherited(previous_daily.get(item["id"]), current_daily.get(item["id"]), previous_day),
            inherited_from=_inherited_from(previous_daily_sources.get(item["id"]),
                                             current_daily.get(item["id"])),
        )
        for item in daily_items
    ]
    for row, item in zip(rows_d, daily_items):
        linked = basic_by_id.get(item.get("basic_entry_id"))
        if linked is None:
            wanted = norm(item.get("name"))
            matches = [candidate for candidate in basic_items
                       if norm(candidate.get("name")) == wanted
                       or norm(str(item.get("name") or "").removeprefix("ارتكاز ")) == norm(candidate.get("name"))]
            linked = matches[0] if len(matches) == 1 else None
        effective_id = daily_data[item["id"]].get("basic_entry_id") or item.get("basic_entry_id")
        linked = basic_by_id.get(effective_id) or linked
        row["basic_entry_id"] = linked.get("id") if linked else ""
        row["basic_service"] = linked
    rows_d = order_campaign_vehicle_rows(rows_d)

    post_items = campaign_posts_on(data, day)
    current_posts = current.get("posts") or {}
    previous_post_details = {
        item["id"]: _prior_with_sources(data, chain, "posts", item["id"])
        for item in post_items}
    previous_posts = {ident: details[0] for ident, details in previous_post_details.items()}
    previous_post_sources = {ident: details[1] for ident, details in previous_post_details.items()}
    rows_p = []
    for item in post_items:
        raw = _merge_inherited(previous_posts.get(item["id"]), current_posts.get(item["id"]))
        vehicle = _vehicle(data, raw.get("vehicle_id"))
        rows_p.append({
            "id": item["id"], "kind": "post", "number": item.get("number", ""),
            "name": item.get("name", ""),
            "driver_text": raw.get("driver_text", item.get("driver_text", "")),
            "vehicle": vehicle,
            "plate_text": "" if vehicle else raw.get("plate_text", ""),
            "type_text": "" if vehicle else raw.get("type_text", ""),
            "inherited": _inherited(previous_posts.get(item["id"]), current_posts.get(item["id"]), previous_day),
            "inherited_from": _inherited_from(previous_post_sources.get(item["id"]),
                                                current_posts.get(item["id"])),
            "warnings": [],
        })
    rows_p = order_campaign_vehicle_rows(rows_p)

    current_plates = current.get("plates")
    previous_plates, previous_plates_day = _prior_plates_with_source(data, chain)
    plates = deepcopy(current_plates if current_plates is not None else (previous_plates or {"rows": []}))
    plates_view = {"rows": plates.get("rows") or [],
                   "inherited": bool(previous_day and previous_plates is not None and current_plates is None),
                   "inherited_from": ({"plates": previous_plates_day}
                                      if current_plates is None and previous_plates_day else {})}

    for row in rows_l:
        _regular_status(row)
    for row in rows_a:
        _regular_status(row, optional=True)
    for row in service_rows:
        if row["kind"] == "group":
            _regular_status(row)
        else:
            _service_status(row)
    for row in rows_d:
        _regular_status(row, driver_only=is_driver_only_daily(row))
    for row in rows_p:
        _post_status(row)

    all_rows = rows_l + rows_a + service_rows + rows_d + rows_p
    _warnings(all_rows)
    force_ids = PeopleRepo(data).ids_on_force(day, "personnel")
    for row in all_rows:
        for driver in _row_drivers(row):
            if driver.get("kind") != "personnel" or driver.get("id") in force_ids:
                continue
            row["warnings"].append("الفرد السائق ليس على القوة في هذا اليوم.")
            break

    warnings = [
        {"row": _warning_name(row), "text": text}
        for row in all_rows
        for text in row["warnings"]
    ]
    vehicles = [
        {"id": vehicle.id, "label": fleet.vehicle_label(vehicle), "plate": vehicle.plate,
         "type": vehicle.type, "status": vehicle.status}
        for vehicle in VehicleRepo(data).all()
        if not vehicle.archived
    ]
    attachable = [
        {"assignment_id": row.get("id"), "name": row.get("name") or row.get("label") or ""}
        for row in assignments.values()
        if row.get("id") not in grouped_ids
    ]
    removed_services = []
    for ident in sorted(removed_ids):
        assignment = assignments[ident]
        raw = (current.get("services") or {}).get(ident, {})
        # اسم مختلف عن `vehicles` (قايمة اختيار المركبات تحت): إعادة استخدام الاسم كانت بتمسحها
        # أول ما يبقى فيه خدمة محذوفة، فالقوايم كلها بتفضى ومفيش رقم مركبة يظهر
        # اسم مختلف عن `vehicles` (قايمة اختيار المركبات): إعادة استخدامه كانت بتمسحها
        # أول ما يبقى فيه خدمة محذوفة، فمفيش رقم مركبة يظهر في أي قايمة
        held = service_vehicles(data, day, ident, include_empty_lorries=True)
        item = next((entry for entry in held if entry.get("source") == "direct"), None)
        item = item or next(iter(held), None)
        vehicle = (item or {}).get("vehicle") or {}
        driver = ((item or {}).get("driver") or {}).get("name", "")
        plate = vehicle.get("plate") or (item or {}).get("plate") or ""
        detail = (f"{plate} — سائق: {driver}" if plate and driver else
                  f"{plate} — بدون سائق" if plate else "بلا تسكين")
        removed_services.append({"id": ident,
            "name": assignment.get("name") or assignment.get("label") or "",
            "time": assignment.get("time") or assignment.get("date_time") or "",
            "summary": detail})
    sections = {
        "posts": _summary(rows_p),
        "lorries": _summary(rows_l),
        "services": _summary(service_rows),
        "daily": _summary(rows_d),
        "appointments": _summary(rows_a),
    }
    delivery_rows = order_campaign_rows(
        [{**row, "_lorry": True} for row in rows_l]
        + service_rows
        + [{**row, "_lorry": True} for row in rows_a],
        rows_d,
    )
    return {
        "date": day,
        "posts": rows_p,
        "lorries": rows_l,
        "appointments": rows_a,
        "services": rows_s,
        "service_rows": service_rows,
        "daily": rows_d,
        "delivery_rows": delivery_rows,
        "removed_services": removed_services,
        "plates": plates_view,
        "warnings": warnings,
        "summary": {"overall": _summary(all_rows), "sections": sections},
        "pickers": {"vehicles": vehicles, "types": VEHICLE_TYPES,
                    "drivers": fleet.drivers_on(data, day), "attachable": attachable,
                    "basic_services": basic_items},
    }


def _row_occurrences(row):
    """المراجع المنطقية للصف؛ يستبعد إسقاط أول مركبة وخط لوري الإلحاق."""
    if row.get("kind") == "post":
        vehicle = row.get("vehicle")
        return ([vehicle] if vehicle else []), []
    if row.get("kind") == "service":
        direct = [item for item in row.get("service_vehicles") or []
                  if item.get("source") == "direct"]
        vehicles = [item["vehicle"] for item in direct if item.get("vehicle")]
        drivers = [item["driver"] for item in direct if item.get("driver")]
        if not direct and row.get("driver"):
            drivers.append(row["driver"])
        return vehicles, drivers
    vehicle = row.get("vehicle")
    driver = row.get("driver")
    return ([vehicle] if vehicle else []), ([driver] if driver else [])


def _row_drivers(row):
    return _row_occurrences(row)[1]


def _warning_name(row):
    """اسم الصف في التحذيرات. الارتكاز واللوري ممكن يشتركوا في الاسم («المديرية») فالارتكاز
    بيتميّز بلاحقة، وإلا التحذير بيقول «مستخدمة في: المديرية» ومحدش عارف أنهي واحد."""
    name = row.get("base_name") or row.get("name", "")
    return f"{name} (ارتكاز)" if row.get("kind") == "post" else name


def _warnings(rows):
    vehicles, drivers = {}, {}
    for row in rows:
        row_vehicles, row_drivers = _row_occurrences(row)
        for vehicle in row_vehicles:
            vehicles.setdefault(vehicle["id"], []).append(row)
            if vehicle.get("status") == "disabled" or vehicle.get("archived"):
                text = "المركبة معطلة أو مؤرشفة." if row.get("kind") == "post" else "المركبة معطلة."
                if text not in row["warnings"]:
                    row["warnings"].append(text)
        for driver in row_drivers:
            if driver.get("id"):
                drivers.setdefault((driver.get("kind"), driver["id"]), []).append(row)

    for values, noun in ((vehicles, "المركبة"), (drivers, "السائق")):
        for grouped in values.values():
            group = list(grouped)
            if len(group) < 2:
                continue
            for row in set(map(id, group)):
                same = [item for item in group if id(item) == row]
                current = same[0]
                others = list(dict.fromkeys(_warning_name(other) for other in group if id(other) != row))
                adjective = "مستخدمة" if noun == "المركبة" else "مستخدم"
                texts = []
                if others:
                    texts.append(f"{noun} {adjective} أيضًا في: {'، '.join(others)}")
                if len(same) > 1:
                    # نفس الصف مستخدم المركبة/السائق مرتين (سطرين في خدمة) — مش «أيضًا في» نفسه
                    texts.append(f"{noun} مكررة داخل نفس الخدمة.")
                for text in texts:
                    if text not in current["warnings"]:
                        current["warnings"].append(text)
    for row in rows:
        if row.get("kind") != "service":
            continue
        for item in row.get("service_vehicles") or []:
            vehicle = item.get("vehicle") or {}
            if vehicle.get("id") and len(vehicles.get(vehicle["id"], [])) > 1:
                item.setdefault("warnings", []).append("المركبة مكررة في يومية الحملة.")


def scope_days(data, day):
    """أيام نطاق قراءة صفحة الحملة (اليوم + أيام نافذة الوراثة السابقة اللي ليها
    حملة) جوه بيانات محمّلة بنطاق أوسع، عشان توكن المراجعة يطابق اللي رجع من GET."""
    return {day, *_chain(data, day)}

"""منطق backend ليومية الحملة."""
from copy import deepcopy

from . import fleet
from .afraad import occasional_rows
from .constants import APPOINTMENT_LORRIES, CAMPAIGN_LORRIES, VEHICLE_TYPES
from .dated import (campaign_daily_on, campaign_posts_on,
                    record_campaign_daily_change, record_campaign_posts_change)
from .repo import ConscriptRepo, PeopleRepo, VehicleRepo
from .store import reserve_id


ALL_LORRIES = CAMPAIGN_LORRIES + APPOINTMENT_LORRIES


def referenced_vehicle_days(data, vehicle_id):
    days = []
    for day, sheet in (data.get("day_campaign") or {}).items():
        for section in ("lorries", "services", "daily", "posts"):
            if any((entry or {}).get("vehicle_id") == vehicle_id
                   for entry in ((sheet or {}).get(section) or {}).values()
                   if isinstance(entry, dict)):
                days.append(day)
                break
    return days


def referenced_conscript_days(data, conscript_id):
    return [day for day, sheet in (data.get("day_campaign") or {}).items()
            if any((entry.get("driver") or {}).get("kind") == "conscript" and
                   (entry.get("driver") or {}).get("id") == conscript_id
                   for section in (sheet or {}).values() if isinstance(section, dict)
                   for entry in section.values())]


def _raw(data, day):
    days = data.setdefault("day_campaign", {})
    return days.setdefault(day, {})


def _previous(data, day):
    days = [d for d in (data.get("day_campaign") or {}) if d < day]
    return max(days) if days else None


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
                "role": raw.get("role", "")}
    if kind == "conscript":
        person = ConscriptRepo(data).find(ident)
        if not person:
            return None
        return {"kind": kind, "id": ident, "name": person.name, "phone": person.phone}
    return {"kind": "text", "id": "", "name": str(value.get("name") or "").strip(), "phone": ""}


def _vehicle(data, vehicle_id):
    vehicle = VehicleRepo(data).find(vehicle_id) if vehicle_id else None
    if not vehicle:
        return None
    return {"id": vehicle.id, "plate": vehicle.plate, "type": vehicle.type,
            "model": vehicle.model, "status": vehicle.status, "fault": vehicle.fault,
            "origin": vehicle.origin, "party": vehicle.party, "archived": vehicle.archived}


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
    return None


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
            if entry.get("attached") or "vehicle_id" in entry or "driver" in entry:
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
    if not any(value.get(k) for k in ("lorries", "services", "daily", "posts", "plates")):
        data["day_campaign"].pop(day, None)


def set_lorry(data, day, lorry_id, payload):
    if lorry_id not in {x["id"] for x in ALL_LORRIES}:
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
    target = _raw(data, day).setdefault("services", {}).setdefault(assignment_id, {})
    error = _apply(data, target, payload)
    if error:
        return error, 400
    _clean(data, day)
    return None, None


def set_daily(data, day, row_id, payload):
    if row_id not in {x["id"] for x in campaign_daily_on(data, day)}:
        return "القول اليومي غير موجود.", 404
    target = _raw(data, day).setdefault("daily", {}).setdefault(row_id, {})
    error = _apply(data, target, payload)
    if error:
        return error, 400
    _clean(data, day)
    return None, None


def attach_service(data, day, lorry_id, item):
    if lorry_id not in {x["id"] for x in ALL_LORRIES}:
        return "اللوري غير موجود.", 404
    assignment_id = str(item.get("assignment_id") or "").strip()
    name = str(item.get("name") or "").strip()
    if assignment_id:
        row = next((r for r in occasional_rows(data, day) if r.get("id") == assignment_id), None)
        if not row:
            return "الخدمة غير موجودة في هذا اليوم.", 404
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
    if lorry_id not in {x["id"] for x in ALL_LORRIES}:
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


def add_daily_row(data, day, name):
    name = str(name or "").strip()
    if not name:
        return None, "اسم القول مطلوب.", 400
    items = campaign_daily_on(data, day)
    existing = [{"id": i.get("id")} for versions in ((data.get("reference_lists") or {}).get("campaign_daily") or []) for i in versions.get("items") or []]
    ident = reserve_id(data, "CD", existing)
    items.append({"id": ident, "name": name})
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


def add_post(data, day, name, number=None, driver_text=None):
    name = str(name or "").strip()
    if not name:
        return None, "اسم الارتكاز مطلوب.", 400
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
        for key in ("vehicle_id", "driver", "driver_text", "plate_text", "type_text")
        if key in previous_entry
    }
    for key in ("vehicle_id", "driver", "driver_text", "plate_text", "type_text"):
        if key in current_entry:
            merged[key] = deepcopy(current_entry[key])
    if "attached" in current_entry:
        merged["attached"] = deepcopy(current_entry["attached"])
    return merged


def _inherited(previous_entry, current_entry, previous_day):
    if not previous_day:
        return False
    previous_entry = previous_entry or {}
    current_entry = current_entry or {}
    return any(key in previous_entry and key not in current_entry
               for key in ("vehicle_id", "driver", "driver_text", "plate_text", "type_text"))


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


def _row_view(data, ident, kind, name, raw, inherited, attached=None):
    return {
        "id": ident,
        "kind": kind,
        "name": name,
        "base_name": name.split(" + ", 1)[0],
        "attached": attached if kind == "lorry" else [],
        "driver": _driver(data, raw.get("driver")),
        "vehicle": _vehicle(data, raw.get("vehicle_id")),
        "inherited": inherited,
        "warnings": [],
    }


def build_campaign(data, day):
    current = (data.get("day_campaign") or {}).get(day) or {}
    previous_day = _previous(data, day)
    previous = (data.get("day_campaign") or {}).get(previous_day) or {}
    current_lorries = current.get("lorries") or {}
    previous_lorries = previous.get("lorries") or {}
    lorry_data = {
        spec["id"]: _merge_inherited(previous_lorries.get(spec["id"]), current_lorries.get(spec["id"]))
        for spec in ALL_LORRIES
    }

    daily_items = campaign_daily_on(data, day)
    current_daily = current.get("daily") or {}
    previous_daily = previous.get("daily") or {}
    daily_data = {
        item["id"]: _merge_inherited(previous_daily.get(item["id"]), current_daily.get(item["id"]))
        for item in daily_items
    }

    assignments = {row.get("id"): row for row in occasional_rows(data, day)}
    attached_ids = {
        item.get("assignment_id")
        for value in lorry_data.values()
        for item in value.get("attached") or []
    }
    rows_l = []
    for spec in CAMPAIGN_LORRIES:
        raw = lorry_data[spec["id"]]
        attached = _attached_rows(raw, assignments)
        suffix = " + " + " + ".join(item["name"] for item in attached if item.get("name")) if attached else ""
        rows_l.append(_row_view(
            data, spec["id"], "lorry", spec["name"] + suffix, raw,
            _inherited(previous_lorries.get(spec["id"]), current_lorries.get(spec["id"]), previous_day),
            attached,
        ))

    rows_a = []
    for spec in APPOINTMENT_LORRIES:
        raw = lorry_data[spec["id"]]
        attached = _attached_rows(raw, assignments)
        suffix = " + " + " + ".join(item["name"] for item in attached if item.get("name")) if attached else ""
        rows_a.append(_row_view(
            data, spec["id"], "lorry", spec["name"] + suffix, raw,
            _inherited(previous_lorries.get(spec["id"]), current_lorries.get(spec["id"]), previous_day),
            attached,
        ))

    rows_s = []
    for assignment in assignments.values():
        if assignment.get("id") in attached_ids:
            continue
        raw = (current.get("services") or {}).get(assignment["id"], {})
        rows_s.append(_row_view(
            data, assignment["id"], "service",
            assignment.get("name") or assignment.get("label") or "", raw, False,
        ))

    rows_d = [
        _row_view(
            data, item["id"], "daily", item["name"], daily_data[item["id"]],
            _inherited(previous_daily.get(item["id"]), current_daily.get(item["id"]), previous_day),
        )
        for item in daily_items
    ]

    post_items = campaign_posts_on(data, day)
    current_posts = current.get("posts") or {}
    previous_posts = previous.get("posts") or {}
    rows_p = []
    for item in post_items:
        raw = _merge_inherited(previous_posts.get(item["id"]), current_posts.get(item["id"]))
        rows_p.append({
            "id": item["id"], "kind": "post", "number": item.get("number", ""),
            "name": item.get("name", ""),
            "driver_text": raw.get("driver_text", item.get("driver_text", "")),
            "vehicle": _vehicle(data, raw.get("vehicle_id")),
            "plate_text": raw.get("plate_text", ""), "type_text": raw.get("type_text", ""),
            "inherited": _inherited(previous_posts.get(item["id"]), current_posts.get(item["id"]), previous_day),
            "warnings": [],
        })

    current_plates = current.get("plates")
    previous_plates = previous.get("plates")
    plates = deepcopy(current_plates if current_plates is not None else (previous_plates or {"rows": []}))
    plates_view = {"rows": plates.get("rows") or [],
                   "inherited": bool(previous_day and previous_plates is not None and current_plates is None)}

    all_rows = rows_l + rows_a + rows_s + rows_d + rows_p
    _warnings(rows_l + rows_a + rows_s + rows_d)
    _post_warnings(rows_p)
    force_ids = PeopleRepo(data).ids_on_force(day, "personnel")
    for row in all_rows:
        driver = row.get("driver") or {}
        if driver.get("kind") == "personnel" and driver.get("id") not in force_ids:
            row["warnings"].append("الفرد السائق ليس على القوة في هذا اليوم.")

    warnings = [
        {"row": row["name"], "text": text}
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
    ]
    return {
        "date": day,
        "posts": rows_p,
        "lorries": rows_l,
        "appointments": rows_a,
        "services": rows_s,
        "daily": rows_d,
        "plates": plates_view,
        "warnings": warnings,
        "pickers": {"vehicles": vehicles, "types": VEHICLE_TYPES,
                    "drivers": fleet.drivers_on(data, day), "attachable": attachable},
    }


def _warnings(rows):
    vehicles, drivers = {}, {}
    for row in rows:
        if row.get("vehicle"):
            vehicles.setdefault(row["vehicle"]["id"], []).append(row)
        d = row.get("driver") or {}
        if d.get("id"):
            drivers.setdefault((d.get("kind"), d["id"]), []).append(row)
    for vals, text in ((vehicles, "المركبة مستخدمة في أكثر من صف."), (drivers, "السائق مستخدم في أكثر من صف.")):
        for group in vals.values():
            if len(group) > 1:
                for row in group: row["warnings"].append(text)
    for row in rows:
        if (row.get("vehicle") or {}).get("status") == "disabled":
            row["warnings"].append("المركبة معطلة.")


def _post_warnings(rows):
    """تحذيرات الارتكازات مستقلة عن تحذيرات صفوف التوصيل."""
    vehicles = {}
    for row in rows:
        vehicle = row.get("vehicle") or {}
        if vehicle.get("id"):
            vehicles.setdefault(vehicle["id"], []).append(row)
        if vehicle.get("status") == "disabled" or vehicle.get("archived"):
            row["warnings"].append("المركبة معطلة أو مؤرشفة.")
    for group in vehicles.values():
        if len(group) > 1:
            for row in group:
                row["warnings"].append("المركبة مستخدمة في أكثر من ارتكاز.")

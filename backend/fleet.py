"""منطق سجل الحملة وقائمة السائقين، من غير اعتماد على Flask."""
import re

from .repo import ConscriptRepo, PeopleRepo, VehicleRepo

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def normalize_plate(series, number):
    series = re.sub(r"\s+", " ", str(series or "").strip())
    number = str(number or "").translate(_ARABIC_DIGITS)
    number = re.sub(r"[\s-]+", "", number)
    return series, number


def plate_taken(data, series, number, ignore_id=None):
    series, number = normalize_plate(series, number)
    return any(v.id != ignore_id and normalize_plate(v.plate_series, v.plate_number) == (series, number)
               for v in VehicleRepo(data).all())


def vehicle_label(vehicle):
    label = f"{vehicle.plate} — {vehicle.type}"
    if vehicle.origin == "external":
        label += f" (خارجية: {vehicle.party})"
    return label


def drivers_on(data, day):
    personnel = []
    for person in PeopleRepo(data).on_force(day, "personnel"):
        effective = person.effective(day)
        post = effective.get("post") or person.post
        if "سائق" in str(post or ""):
            personnel.append({"id": person.id, "name": person.name,
                              "role": person.role, "phone": person.phone,
                              "post": post})
    personnel.sort(key=lambda item: item["name"])
    conscripts = [{"id": person.id, "name": person.name, "phone": person.phone}
                  for person in ConscriptRepo(data).all() if person.is_driver]
    return {"personnel": personnel, "conscripts": conscripts}


# ---------- تصنيف المركبة حسب النوع (ترتيب يومية الحملة) ----------

CATEGORY_RANK = {"lorry": 0, "bus": 1, "micro": 2, "pickup": 3, "other": 4}
_ARABIC_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي", "ـ": None})
_DIACRITICS = re.compile(r"[ً-ٰٟ]")


def _fold(text):
    text = _DIACRITICS.sub("", str(text or "")).translate(_ARABIC_FOLD)
    return " ".join(re.sub(r"[()\-_/،,.]+", " ", text).split())


def vehicle_category(vehicle_type):
    """lorry / bus / micro / pickup / other من نص نوع المركبة، بتطبيع الكتابات العربي المختلفة:
    «اتوبيس/أوتوبيس/اوتوبيس/باص»، «ميكروباص/ميكرو/ميك»، «بيك اب/بيكب/بيكاب»، «دوبل كبينة/دبل كابينة»."""
    text = _fold(vehicle_type)
    if not text:
        return "other"
    tokens = text.split()
    squashed = text.replace(" ", "")
    if "لوري" in squashed or "لورى" in squashed or "لواري" in squashed:
        return "lorry"
    # الميكرو قبل الأتوبيس لأن «ميكروباص» فيها «باص».
    if "ميكرو" in squashed or "ميني" in tokens or "ميك" in tokens:
        return "micro"
    if any(k in squashed for k in ("اتوبيس", "اوتوبيس", "اتوبس", "اوتوبس")) or "باص" in tokens:
        return "bus"
    if any(k in squashed for k in ("بيكاب", "بيكب")):
        return "pickup"
    if tokens[0] in ("دوبل", "دبل") and any(t.startswith(("كبين", "كابين", "كيبين")) for t in tokens[1:]):
        return "pickup"
    return "other"


def order_by_category(items, vehicle_type_of, group_key_of, *, lorry_if_missing=None):
    """يرتّب الصفوف: لوري (مجمّع لكل لوري ورا بعض) ثم أتوبيس ثم ميكروباص ثم بيك اب/دوبل كبينة
    ثم الباقي والصفوف من غير مركبة. الترتيب ثابت جوه كل فئة، واللواري بترتيب أول ظهور.

    ``vehicle_type_of(item)``: نوع المركبة (أو None). ``group_key_of(item)``: مفتاح اللوري
    (رقم المركبة أو معرف اللوري). ``lorry_if_missing(item)``: صف بلا مركبة يتعامل كلوري.
    يرجع قايمة (item, category, group_key, break_after)؛ break_after = حد سميك بعد الصف."""
    entries = []
    for index, item in enumerate(items):
        vtype = vehicle_type_of(item)
        category = vehicle_category(vtype) if vtype else (
            "lorry" if lorry_if_missing and lorry_if_missing(item) else "other")
        key = group_key_of(item) if category == "lorry" else None
        entries.append((item, category, key, index))
    first_seen = {}
    for _item, category, key, index in entries:
        first_seen.setdefault((category, key), index)
    entries.sort(key=lambda e: (CATEGORY_RANK[e[1]],
                                first_seen[(e[1], e[2])] if e[1] == "lorry" else 0, e[3]))
    out = []
    for position, (item, category, key, _index) in enumerate(entries):
        nxt = entries[position + 1] if position + 1 < len(entries) else None
        brk = nxt is not None and (nxt[1] != category or (category == "lorry" and nxt[2] != key))
        out.append((item, category, key, brk))
    return out

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

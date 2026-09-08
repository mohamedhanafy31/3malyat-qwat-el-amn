"""الراحات والإجازات — بناء سجل راحة والتحقق من التداخل."""
from datetime import timedelta

from .constants import LEAVE_TYPES
from .people import find_person
from .utils import parse_date


def build_leave(payload, data, leave_id):
    person_id = str(payload.get("person_id", "")).strip()
    person, _, _ = find_person(data, person_id)
    if not person:
        return None, "برجاء اختيار الشخص."

    kind = str(payload.get("type", "")).strip()
    if kind not in LEAVE_TYPES:
        return None, "نوع الراحة غير صحيح."

    start = parse_date(payload.get("start"))
    end = parse_date(payload.get("end"))
    if not start or not end:
        return None, "برجاء إدخال تاريخ بداية ونهاية صحيحين."
    if end < start:
        return None, "تاريخ النهاية لا يمكن أن يسبق تاريخ البداية."
    if (end - start).days > 120:
        return None, "مدة الراحة كبيرة بشكل غير منطقي."

    return {
        "id": leave_id,
        "person_id": person_id,
        "name": person.get("name", ""),
        "type": kind,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "return_date": (end + timedelta(days=1)).isoformat(),
        "note": str(payload.get("note", "")).strip(),
        # بيتحافظ عليه تلقائيًا عند التعديل لأن edit_leave بيمرر السجل الحالي
        # مدموج مع التعديلات الجديدة، فلو الطلب ما لمسوش فضل زي ما هو
        "source": str(payload.get("source", "")).strip(),
    }, None


def overlapping(data, leave, ignore_id=None):
    for lv in data["leaves"]:
        if lv.get("id") == ignore_id or lv.get("person_id") != leave["person_id"]:
            continue
        if lv["start"] <= leave["end"] and leave["start"] <= lv["end"]:
            return lv
    return None


def leave_on(data, person_id, day):
    for lv in leaves_of(data, person_id):
        if lv["start"] <= day <= lv["end"]:
            return lv
    return None


def leaves_of(data, person_id):
    """سجلات راحة شخص واحد — مفهرسة على البيانات المحمّلة.

    من غير الفهرس ده، بناء يومية واحدة كان بيلف على كل سجلات الراحة لكل
    ضابط (34 × 272 = 9,248 مقارنة للوحة الواحدة). الفهرس بيتبني مرة على
    نسخة البيانات وبيتخزن جواها، فبيتبني مرة واحدة لكل طلب.
    """
    index = data.get("_leaves_by_person")
    if index is None or index.get("_size") != len(data["leaves"]):
        index = {"_size": len(data["leaves"])}
        for lv in data["leaves"]:
            index.setdefault(lv.get("person_id"), []).append(lv)
        data["_leaves_by_person"] = index
    return index.get(person_id, ())

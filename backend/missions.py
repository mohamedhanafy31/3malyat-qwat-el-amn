"""المأموريات — كيان تشغيلي له دورة حياة، مش خدمة عادية بتتكرر كل يوم.

الفرق عن «الخدمة»: الخدمة نوع تشغيل بيتكرر (دورية، نقطة تفتيش...) وبتتحط
على اليومية التفصيلية كل يوم لوحدها. المأمورية حدث له بداية وحالة بتتغيّر
مع الوقت (مخططة → بدأت → عادت → أغلقت/ألغيت)، ومفيش داعي لإعادة كتابتها
كل يوم — دورة حياتها هي اللي بتتابَع.
"""
from .store import reserve_id

STATUSES = ["مخططة", "بدأت", "عادت", "أغلقت", "ألغيت"]
OPEN_STATUSES = {"مخططة", "بدأت"}


def missions(data):
    return data.setdefault("missions", [])


def new_id(data):
    return reserve_id(data, "MSN", missions(data))


def _clean_members(data, ids):
    from .people import find_person

    out = []
    for pid in ids or []:
        pid = str(pid).strip()
        if not pid or pid in out:
            continue
        person, category, _ = find_person(data, pid)
        if not person or category != "officers":
            return None, f"«{pid}» مش ضابط موجود في السجل."
        out.append(pid)
    return out, None


def blank_mission(mission_id, name):
    return {
        "id": mission_id, "name": name, "member_ids": [],
        "start": "", "note": "", "status": "مخططة",
    }


def apply_mission(data, mission, payload):
    """بيطبّق حقول الطلب على المأمورية. بترجع (mission, error) — error مش
    None يبقى مفيش تعديل."""
    from .utils import canonical_day

    if "name" in payload:
        name = str(payload["name"]).strip()
        if not name:
            return None, "اسم المأمورية مطلوب."
        mission["name"] = name
    if "member_ids" in payload:
        members, err = _clean_members(data, payload["member_ids"])
        if err:
            return None, err
        mission["member_ids"] = members
    if "start" in payload:
        raw = payload.get("start")
        start = canonical_day(raw) if raw else ""
        if raw and not start:
            return None, "تاريخ البداية غير صحيح."
        mission["start"] = start
    if "status" in payload:
        status = str(payload["status"]).strip()
        if status not in STATUSES:
            return None, "حالة غير صحيحة."
        mission["status"] = status
    if "note" in payload:
        mission["note"] = str(payload["note"]).strip()
    return mission, None


def with_member_names(data, mission):
    from .repo import PeopleRepo

    people = {p["id"]: p for p in PeopleRepo(data).raw_all("officers")}
    members = [{"id": pid, "name": people.get(pid, {}).get("name", ""),
               "role": people.get(pid, {}).get("role", "")}
               for pid in mission.get("member_ids", [])]
    return {**mission, "members": members}

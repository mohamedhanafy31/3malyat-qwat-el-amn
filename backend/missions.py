"""المأموريات — كيان تشغيلي له دورة حياة، مش خدمة عادية بتتكرر كل يوم.

الفرق عن «الخدمة»: الخدمة نوع تشغيل بيتكرر (دورية، نقطة تفتيش...) وبتتحط
على اليومية التفصيلية كل يوم لوحدها. المأمورية حدث له بداية وحالة بتتغيّر
مع الوقت (مخططة → بدأت → عادت → أغلقت/ألغيت)، ومفيش داعي لإعادة كتابتها
كل يوم — دورة حياتها هي اللي بتتابَع.
"""
from .store import reserve_id

STATUSES = ["مخططة", "بدأت", "عادت", "أغلقت", "ألغيت"]
OPEN_STATUSES = {"مخططة", "بدأت"}

# دورة الحياة اتجاه واحد بالترتيب ده، والإلغاء ينفع من أي حالة مفتوحة —
# من غيره كان ينفع تحط «أغلقت» رجوع لـ«مخططة» من غير أي معنى تشغيلي.
TRANSITIONS = {
    "مخططة": {"بدأت", "ألغيت"},
    "بدأت": {"عادت", "ألغيت"},
    "عادت": {"أغلقت"},
    "أغلقت": set(),
    "ألغيت": set(),
}


def missions(data):
    return data.setdefault("missions", [])


def new_id(data):
    return reserve_id(data, "MSN", missions(data))


def _clean_members(data, ids, start):
    """بترجع (قايمة, error). `start` لو محدد، العضو لازم يكون على القوة
    وقتها — من غيره ضابط اتأرشف قبل بداية المأمورية بكتير (أو مش على
    القوة أصلًا لسه) كان ينفع يتضاف عضو من غير أي فحص."""
    from .people import find_person
    from .repo import PeopleRepo

    on_force = ({p["id"] for p in PeopleRepo(data).raw_on_force(start, "officers")}
               if start else None)

    out = []
    for pid in ids or []:
        pid = str(pid).strip()
        if not pid or pid in out:
            continue
        person, category, _ = find_person(data, pid)
        if not person or category != "officers":
            return None, f"«{pid}» ليس ضابطًا موجودًا في السجل."
        if on_force is not None and pid not in on_force:
            return None, f"«{person.get('name', '')}» لم يكن على القوة في تاريخ بداية المأمورية."
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
    # تاريخ البداية لازم يتحدّد قبل التحقق من الأعضاء — فحص «كان على
    # القوة وقتها» محتاج التاريخ النهائي (من الطلب ده أو المسجّل بالفعل).
    if "start" in payload:
        raw = payload.get("start")
        start = canonical_day(raw) if raw else ""
        if raw and not start:
            return None, "تاريخ البداية غير صحيح."
        mission["start"] = start
    if "member_ids" in payload:
        members, err = _clean_members(data, payload["member_ids"], mission.get("start", ""))
        if err:
            return None, err
        mission["member_ids"] = members
    if "status" in payload:
        status = str(payload["status"]).strip()
        if status not in STATUSES:
            return None, "حالة غير صحيحة."
        current = mission.get("status", "مخططة")
        # دورة الحياة اتجاه واحد — من غير القيد ده كان ينفع ترجّع مأمورية
        # «أغلقت» لـ«مخططة» من غير أي معنى تشغيلي، ودورة الحياة اللي
        # الصفحة بتتابعها تبقى مالهاش قيمة.
        if status != current and status not in TRANSITIONS.get(current, set()):
            return None, f"لا يمكن تغيير حالة المأمورية من «{current}» إلى «{status}» مباشرة."
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


def daily_assignments(data, day):
    """الخدمات المعلّمة «مأمورية / ترحيلة» في يوم واحد.

    المصدر هو ``day_assignments`` نفسه؛ لذلك تعديل الخدمة أو حذفها من
    اليومية ينعكس هنا فورًا من غير سجل موازٍ أو خطوة مزامنة.
    """
    from .assignments import peek_day
    from .people import effective
    from .repo import PeopleRepo

    people = {}
    repo = PeopleRepo(data)
    for category in ("officers", "personnel"):
        for person in repo.raw_all(category):
            people[person["id"]] = (person, category)

    def member(person_id):
        found = people.get(person_id)
        if not found:
            return {"id": person_id, "name": "", "role": "", "category": "",
                    "missing": True}
        person, category = found
        state = effective(person, day)
        return {"id": person_id, "name": person.get("name", ""),
                "short_name": person.get("short_name", ""),
                "role": state.get("role", ""), "category": category}

    groups = {"داخلية": [], "خارجية": []}
    for assignment in peek_day(data, day):
        if not assignment.get("mission_transport"):
            continue
        kind = assignment.get("kind", "")
        if kind not in groups:
            # السجلات القديمة أو المعدّلة يدويًا لا تختفي، لكن إنشاء/تعديل
            # السجل عبر الـAPI يمنع أصلًا هذا التعارض.
            continue
        groups[kind].append({
            "id": assignment.get("id", ""),
            "name": assignment.get("name", ""),
            "kind": kind,
            "section": assignment.get("section", ""),
            "shift": assignment.get("shift", ""),
            "source_manning": assignment.get("source_manning", ""),
            "officers": [member(pid) for pid in assignment.get("officer_ids") or []],
            "personnel": [member(pid) for pid in assignment.get("personnel_ids") or []],
            "conscripts": assignment.get("conscripts") or [],
            "conscript_count": int(assignment.get("conscript_count") or 0),
            "weapon": assignment.get("weapon", ""),
            "time": assignment.get("time", ""),
            "party": assignment.get("party", ""),
            "note": assignment.get("note", ""),
        })
    return groups

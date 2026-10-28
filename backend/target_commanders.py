"""إدارة قادة الأهداف الثابتين كحركة مناصب مؤرخة.

قائد الهدف ليس الضابط الذي يغطي الهدف في يوم معين. الأول منصب يسري
من تاريخ، والثاني تكليف يومي يظل في اليومية التفصيلية.
"""
from . import changes
from .board import (
    is_target_commander_post, target_commander_post, target_commanders_for_day,
    target_row_names,
)
from .people import effective, record_change
from .repo import PeopleRepo
from .store import revision


def view(data, day):
    """حالة قادة الأهداف وقائمة الضابط الصالحين في تاريخ السريان."""
    repo = PeopleRepo(data)
    officers = []
    for person in repo.raw_on_force(day, "officers"):
        state = effective(person, day)
        officers.append({
            "id": person["id"], "name": person.get("name", ""),
            "short_name": person.get("short_name", ""),
            "role": state.get("role", ""), "post": state.get("post", ""),
        })
    return {
        "day": day,
        "targets": target_commanders_for_day(data, day),
        "officers": officers,
        "revision": revision(data, ()),
    }


def apply(data, day, assignments):
    """يطبّق الجدول كله كوحدة واحدة؛ ويرجع (payload, error)."""
    names = target_row_names(data, day)
    if not isinstance(assignments, dict):
        return None, "بيانات تعيين الأهداف غير صحيحة."
    if set(assignments) != set(names):
        return None, "يجب إرسال كل الأهداف الظاهرة في الكشف."

    desired = {}
    chosen = []
    for name in names:
        raw_id = assignments.get(name)
        officer_id = str(raw_id or "").strip()
        desired[name] = officer_id or None
        if officer_id:
            chosen.append(officer_id)
    if len(chosen) != len(set(chosen)):
        return None, "لا يمكن تعيين الضابط نفسه قائدًا لأكثر من هدف."

    repo = PeopleRepo(data)
    officers = repo.raw_on_force(day, "officers")
    by_id = {person["id"]: person for person in officers}
    missing = [officer_id for officer_id in chosen if officer_id not in by_id]
    if missing:
        return None, "أحد الضباط المختارين ليس على القوة في تاريخ السريان."

    before = target_commanders_for_day(data, day)
    desired_post = {
        officer_id: target_commander_post(name)
        for name, officer_id in desired.items() if officer_id
    }
    changed = []
    for person in officers:
        current = effective(person, day).get("post", "")
        wanted = desired_post.get(person["id"])
        if wanted is None and not is_target_commander_post(current):
            continue
        wanted = wanted or ""
        if current == wanted:
            continue
        record_change(person, day, {"post": wanted})
        changed.append({"id": person["id"], "name": person.get("name", ""),
                        "before": current, "after": wanted})

    after = target_commanders_for_day(data, day)
    if changed:
        changes.record(
            data, "target_commanders", day, "update", before=before, after=after, day=day,
            text=f"تحديث قادة الأهداف الساري من {day} ({len(changed)} تغيير).",
        )
    payload = view(data, day)
    payload["changed"] = changed
    return payload, None

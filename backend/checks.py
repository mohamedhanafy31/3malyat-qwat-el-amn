"""فحوصات اليوم — تنبيهات مش موانع.

المراجعة طلّعت إن مفيش أي فحص تعارض في السيستم. لكن الأرشيف بيوضّح إن
معظم «التعارضات» النظرية دي شغل عادي فعلًا: يومية 20/8 فيها ضابط على
«تبة ضرب النار + كنترول الازهر ليل» — خدمتين في نفس الفترة، وده مقصود.

عشان كده الفحوصات هنا **تنبيهات بتتعرض جنب اليوم** مش رفض للحفظ. الحاجة
الوحيدة اللي بتتمنع فعلًا هي التكرار الحرفي (نفس الضابط على نفس الخدمة
ونفس الفترة مرتين) لأنها مالهاش أي معنى تشغيلي وبتغلط العدّ.
"""
from .assignments import peek_day, services_by_id
from .constants import SHIFTS
from .leaves import leave_on


def duplicate_of(data, day, service_id, shift, person_ids, ignore_id=None):
    """-> id الخانة المكررة لو نفس الشخص على نفس الخدمة والفترة بالفعل."""
    for row in peek_day(data, day):
        if row["id"] == ignore_id or row.get("service_id") != service_id:
            continue
        if (row.get("shift") or "") != (shift or ""):
            continue
        assigned = set(row.get("officer_ids") or []) | set(row.get("personnel_ids") or [])
        if assigned & set(person_ids):
            return row["id"]
    return None


def day_warnings(data, day, rows):
    """تنبيهات اليوم من صفوف يومية الضباط المحسوبة.

    `rows` هي مخرجات summarise — فيها التكليفات والراحة والحالة لكل ضابط.
    """
    services = services_by_id(data)
    out = []

    for row in rows:
        name = f'{row["role"]}/ {row["name"]}'.strip(" /")

        # مكلّف وهو في راحة — بيحصل غلط، والوورد مابيعملهوش
        if row["leave"] and row["services"]:
            out.append({
                "kind": "راحة",
                "officer_id": row["id"],
                "text": f'{name} مكلّف بخدمة وهو في {row["leave"]["type"]}'
                        f' لحد {row["leave"]["end"]}',
            })

        # حالة خوارج (انتداب/غياب/مرضي/فرقة) مع تكليف
        if row["status"] and row["services"]:
            out.append({
                "kind": "حالة",
                "officer_id": row["id"],
                "text": f'{name} مسجّل «{row["status"]}» ومكلّف بخدمة في نفس اليوم',
            })

        # أكتر من خدمة في نفس الفترة — وارد جدًا في الوورد، بس يستاهل نظرة
        for shift in SHIFTS:
            same = [it["name"] for it in row["services"] if it["shift"] == shift]
            if len(same) > 1:
                out.append({
                    "kind": "ازدحام",
                    "officer_id": row["id"],
                    "text": f'{name} على {len(same)} خدمات في الفترة ال{shift}:'
                            f' {"، ".join(same)}',
                })

    # خدمة محتاجة ضابط ومحطوطش
    for assignment in peek_day(data, day):
        svc = services.get(assignment.get("service_id"))
        if not svc or not (svc.get("needs") or {}).get("officer"):
            continue
        if assignment.get("officer_ids"):
            continue
        out.append({
            "kind": "شاغرة",
            "assignment_id": assignment["id"],
            "text": f'«{svc["name"]}» محتاجة ضابط ولسه فاضية',
        })

    return out


def has_leave(data, person_id, day):
    return leave_on(data, person_id, day) is not None

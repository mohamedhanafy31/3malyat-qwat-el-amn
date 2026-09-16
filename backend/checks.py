"""فحوصات اليوم — تنبيهات مش موانع.

المراجعة طلّعت إن مفيش أي فحص تعارض في السيستم. لكن الأرشيف بيوضّح إن
معظم «التعارضات» النظرية دي شغل عادي فعلًا: يومية 20/8 فيها ضابط على
«تبة ضرب النار + كنترول الازهر ليل» — خدمتين في نفس الفترة، وده مقصود.

عشان كده الفحوصات هنا **تنبيهات بتتعرض جنب اليوم** مش رفض للحفظ. الحاجة
الوحيدة اللي بتتمنع فعلًا هي التكرار الحرفي (نفس الضابط على نفس الخدمة
ونفس الفترة مرتين) لأنها مالهاش أي معنى تشغيلي وبتغلط العدّ.
"""
from .assignments import peek_day
from .constants import SHIFTS, WARNING_LEVELS
from .leaves import leave_on
from .text import norm


def _tag(warning):
    warning["level"] = WARNING_LEVELS.get(warning["kind"], "info")
    return warning


def duplicate_of(data, day, name, shift, person_ids, ignore_id=None):
    """-> id الخانة المكررة لو نفس الشخص على نفس اسم الخدمة (بعد التطبيع)
    ونفس الفترة بالفعل."""
    key = norm(name)
    for row in peek_day(data, day):
        if row["id"] == ignore_id or norm(row.get("name", "")) != key:
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
    out = []

    for row in rows:
        name = f'{row["role"]}/ {row["name"]}'.strip(" /")

        # مكلّف وهو في راحة — بيحصل غلط، والوورد مابيعملهوش
        if row["leave"] and row["services"]:
            out.append(_tag({
                "kind": "راحة",
                "officer_id": row["id"],
                "text": f'{name} مكلّف بخدمة وهو في {row["leave"]["type"]}'
                        f' لحد {row["leave"]["end"]}',
            }))

        # حالة خوارج (انتداب/غياب/مرضي/فرقة) مع تكليف
        if row["status"] and row["services"]:
            out.append(_tag({
                "kind": "حالة",
                "officer_id": row["id"],
                "text": f'{name} مسجّل «{row["status"]}» ومكلّف بخدمة في نفس اليوم',
            }))

        # أكتر من خدمة في نفس الفترة — وارد جدًا في الوورد، بس يستاهل نظرة
        for shift in SHIFTS:
            same = [it["name"] for it in row["services"] if it["shift"] == shift]
            if len(same) > 1:
                out.append(_tag({
                    "kind": "ازدحام",
                    "officer_id": row["id"],
                    "text": f'{name} على {len(same)} خدمات في الفترة ال{shift}:'
                            f' {"، ".join(same)}',
                }))

    # خانة شاغرة تمامًا — من غير ضابط ولا فرد ولا حتى عدد مجندين مسجّل.
    # مفيش كتالوج يقول «الخدمة دي محتاجة ضابط» زي الأول، فالفحص بقى أبسط:
    # صف من غير أي قوام مسجّل عليه محتاج مراجعة.
    for assignment in peek_day(data, day):
        if (assignment.get("officer_ids") or assignment.get("personnel_ids")
                or assignment.get("conscript_count")):
            continue
        display = assignment.get("name") or "(بدون اسم)"
        out.append(_tag({
            "kind": "شاغرة",
            "assignment_id": assignment["id"],
            "text": f'«{display}» شاغرة تمامًا — من غير ضابط ولا فرد ولا عدد مجندين',
        }))

    return out


def has_leave(data, person_id, day):
    return leave_on(data, person_id, day) is not None

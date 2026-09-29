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
from .missions import missions as missions_of_data
from .people import officers_on
from .rest_status import is_weekly_rest_weekday
from .rest_suspension import is_suspended_on
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


def _started_mission_members(data, day):
    """أعضاء أي مأمورية حالتها «بدأت» وبدأت في اليوم ده أو قبله — المأمورية
    مالهاش تاريخ نهاية (دورة حياتها هي اللي بتتابَع)، فـ«لسه ما رجعش» يعني
    أي يوم من البداية لحد ما حد يغيّر حالتها بالإيد لـ«عادت»."""
    out = set()
    for m in missions_of_data(data):
        if m.get("status") == "بدأت" and m.get("start") and m["start"] <= day:
            out.update(m.get("member_ids") or [])
    return out


def day_warnings(data, day, rows):
    """تنبيهات اليوم من صفوف يومية الضباط المحسوبة.

    `rows` هي مخرجات summarise — فيها التكليفات والراحة والحالة لكل ضابط.
    """
    out = []
    on_mission = _started_mission_members(data, day)
    raw_officers = {o["id"]: o for o in officers_on(data, day)}

    for row in rows:
        name = f'{row["role"]}/ {row["name"]}'.strip(" /")

        # النهاردة يوم راحته الأسبوعية الثابت (`rest_day`) ومفيش راحة
        # مسجّلة له — الحساب الأسبوعي دايمًا تخمين دوري لحد ما تُسجّل
        # الراحة فعليًا (`rest_status.next_rest_start`)، فالتنبيه ده
        # تذكير يسجّلها بدل ما تفضل تنبيه تقصيرة/راحة يطلع لوحده صامت.
        officer = raw_officers.get(row["id"]) or {}
        if (officer.get("rest_system") == "أسبوعية" and officer.get("rest_day")
                and is_weekly_rest_weekday(officer["rest_day"], day) and not row["leave"]
                # الفرقة سبب مقصود لعدم تسجيل الراحة الأسبوعية في اليوم ده
                and not row["course"]
                # الراحة الأسبوعية موقوفة بأمر — مفيش راحة مستحقة تتسجّل أصلًا
                and not is_suspended_on(data, "أسبوعية", day)):
            out.append(_tag({
                "kind": "راحة أسبوعية غير مسجلة",
                "officer_id": row["id"],
                "text": f'اليوم هو يوم الراحة الأسبوعية لـ{name} ({officer["rest_day"]})، '
                        "ولم تُسجَّل له راحة بعد",
            }))

        # مكلّف بخدمة وهو في مأمورية «بدأت» ولسه ما اترجّعش — المأمورية
        # مالهاش سجل يومي يمنع التكليف زي الراحة، فممكن يفضل معيّن على
        # خدمة يومية من غير أي علم إنه في مأمورية.
        if row["id"] in on_mission and row["services"]:
            out.append(_tag({
                "kind": "مأمورية",
                "officer_id": row["id"],
                "text": f'{name} مكلّف بخدمة وهو في مأمورية «بدأت» ولم يعد منها بعد',
            }))

        # مكلّف وهو في راحة — بيحصل غلط، والوورد مابيعملهوش
        if row["leave"] and row["services"]:
            out.append(_tag({
                "kind": "راحة",
                "officer_id": row["id"],
                "text": f'{name} مكلّف بخدمة وهو في {row["leave"]["type"]}'
                        f' حتى {row["leave"]["end"]}',
            }))

        # راحة والتحاق فرقة في نفس اليوم — الاتنين مسجّلين لوحدهم من غير
        # تعارض بينهم (build_leave وbuild_term ما بيشوفش حاجة عن التاني)،
        # فممكن ضابط يفضل عنده الاتنين سهوًا.
        if row["leave"] and row["course"]:
            out.append(_tag({
                "kind": "راحة+فرقة",
                "officer_id": row["id"],
                "text": f'{name} في {row["leave"]["type"]} و«{row["course"]["name"]}» '
                        "في نفس اليوم",
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
                    "text": f'عدد خدمات {name} في الفترة ال{shift}: {len(same)} — '
                            f'{"، ".join(same)}',
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
            "text": f'«{display}» شاغرة تمامًا — بلا ضابط أو فرد أو عدد مجندين',
        }))

    return out


def has_leave(data, person_id, day):
    return leave_on(data, person_id, day) is not None

"""الراحات والإجازات — بناء سجل راحة والتحقق من التداخل."""
from collections import defaultdict
from datetime import date, timedelta

from .constants import LEAVE_TYPES
from .date_range import overlapping_of, parse_range
from .people import find_person
from .utils import MAX_LEN

MAX_NOTE = MAX_LEN["note"]


def build_leave(payload, data, leave_id):
    person_id = str(payload.get("person_id", "")).strip()
    person, _, _ = find_person(data, person_id)
    if not person:
        return None, "برجاء اختيار الشخص."

    kind = str(payload.get("type", "")).strip()
    if kind not in LEAVE_TYPES:
        return None, "نوع الراحة غير صحيح."

    start, end, error = parse_range(payload, 120, "مدة الراحة كبيرة بشكل غير منطقي.", required=True)
    if error:
        return None, error

    # الراحة لازم تقع جوّه فترة خدمة الشخص. راحة بتاريخ قبل الانضمام أو بعد
    # الخروج بتفضل في الإجماليات والإحصائيات وهي مستحيلة تشغيليًا، ومابتظهرش
    # في أي يومية (لأن officers_on بتستبعده) — فبتفضل غلط مخفي.
    join = str(person.get("join_date", "") or "")
    if join and start.isoformat() < join:
        return None, f"تاريخ الراحة قبل تاريخ انضمام الشخص ({join})."
    left = str(person.get("leave_date", "") or "")
    if left and end.isoformat() > left:
        return None, f"تاريخ الراحة بعد تاريخ خروج الشخص من القوة ({left})."

    note = str(payload.get("note", "")).strip()
    if len(note) > MAX_NOTE:
        return None, f"الملاحظة أطول من الحد المسموح ({MAX_NOTE} حرف)."

    # `name` **مابيتخزّنش** — بيتحلّ من `person_id` وقت القراءة
    # (`LeaveRepo.named`). تخزينه كان بيخلي أي تعديل اسم يسيب الراحات
    # القديمة بالاسم القديم لحد ما كود مزامنة يلحقها.
    leave = {
        "id": leave_id,
        "person_id": person_id,
        "type": kind,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "return_date": (end + timedelta(days=1)).isoformat(),
        "note": note,
        # بيتحافظ عليه تلقائيًا عند التعديل لأن edit_leave بيمرر السجل الحالي
        # مدموج مع التعديلات الجديدة، فلو الطلب ما لمسوش فضل زي ما هو
        "source": str(payload.get("source", "")).strip(),
    }
    # السجلات العادية والقديمة تفضل بنفس شكلها؛ الحقل بيتكتب بس لما يكون
    # للراحة مصدر آلي معروف محتاج يظهر في الواجهة.
    origin = str(payload.get("origin", "")).strip()
    if origin:
        leave["origin"] = origin
    return leave, None


def overlapping(data, leave, ignore_id=None):
    return overlapping_of(data["leaves"], leave["start"], leave["end"],
                           "person_id", leave["person_id"], ignore_id)


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


# الأنواع اللي بتتحدّث بكشف شهري من المديرية — بعكس الأسبوعية اللي
# بتتحسب لوحدها من rest_day، دول مالهمش تاريخ جاي تلقائي.
MONTHLY_REST_SYSTEMS = ("شهرية", "نصف شهرية")


def monthly_roster(data, today):
    """صف لكل ضابط نظامه شهري/نصف شهري + حالة آخر سجل راحة بنفس نوع نظامه.

    مفيش حساب تلقائي هنا زي الأسبوعية — الكشف بيوصل شهريًا بالإيد من
    المديرية، فالمصدر الوحيد لـ«الراحة الجاية» هو آخر سجل راحة اتسجل
    فعلاً من نوع نظام الضابط. لو آخر سجل خلص وماحدش سجّل التالي، الضابط
    يبقى «due» — ده اللي شاشة تحديث الكشف بتستخدمها تعرض علامة «تم».
    """
    today_iso = today.isoformat()
    out = []
    from .repo import PeopleRepo
    from .rest_suspension import suspended_types

    suspended = suspended_types(data)

    for o in PeopleRepo(data).bucket("officers", "active"):
        system = o.get("rest_system", "")
        if system not in MONTHLY_REST_SYSTEMS:
            continue
        candidates = [lv for lv in leaves_of(data, o["id"]) if lv.get("type") == system]
        current = max(candidates, key=lambda lv: lv["start"], default=None)
        status, info = "due", None
        if current:
            if current["start"] <= today_iso <= current["end"]:
                status, info = "active", {"start": current["start"], "end": current["end"]}
            elif current["start"] > today_iso:
                status, info = "upcoming", {"start": current["start"], "end": current["end"]}
        # نوع راحته موقوف بأمر — مش «متأخر» عن تسجيل الكشف، هو ممنوع يتسجّل أصلًا
        if status == "due" and system in suspended:
            order = suspended[system]
            status, info = "suspended", {"since": order.get("started_on"), "id": order.get("id")}
        out.append({"id": o["id"], "name": o.get("name", ""), "role": o.get("role", ""),
                    "rest_system": system, "status": status, "current": info})
    return out


def weekly_roster(data, today):
    """ضباط الراحة الأسبوعية الحاليون + الموعد الثابت والسجلات القادمة.

    الموعد الثابت معلومة جدول، والسجلات القادمة حقيقة مخزنة؛ الاتنين
    بيرجعوا منفصلين عشان الواجهة ماتعرضش التخمين كأنه سجل راحة.
    """
    from .repo import PeopleRepo
    from .rest_status import is_weekly_rest_weekday, next_weekday

    today_iso = today.isoformat()
    out = []
    for officer in PeopleRepo(data).active("officers"):
        if officer.rest_system != "أسبوعية" or not officer.rest_day:
            continue
        fixed = today if is_weekly_rest_weekday(officer.rest_day, today_iso) \
            else next_weekday(officer.rest_day, today)
        upcoming = [
            {k: lv.get(k, "") for k in ("id", "start", "end", "origin")}
            for lv in leaves_of(data, officer.id)
            if lv.get("type") == "أسبوعية" and lv.get("start", "") >= today_iso
        ]
        upcoming.sort(key=lambda lv: (lv["start"], lv["id"]))
        out.append({
            "id": officer.id, "name": officer.name, "role": officer.role,
            "rest_day": officer.rest_day,
            "next_fixed": fixed.isoformat() if fixed else "",
            "upcoming": upcoming,
        })
    return out


def validate_weekly_extra(data, leave, today):
    """قواعد المصدر `weekly_extra` فوق تحقق الراحة العادي."""
    if leave.get("origin") != "weekly_extra":
        return None
    from .repo import PeopleRepo
    from .rest_status import is_weekly_rest_weekday

    officer = PeopleRepo(data).find_in(leave.get("person_id"), "officers")
    if not officer or officer.archived or officer.rest_system != "أسبوعية":
        return "الراحة الإضافية متاحة لضابط على القوة بنظام راحة أسبوعية بس."
    if leave.get("type") != "أسبوعية" or leave.get("start") != leave.get("end"):
        return "الراحة الأسبوعية الإضافية لازم تكون يوم واحد."
    if leave.get("start", "") < today:
        return "الراحة الأسبوعية الإضافية لازم تكون النهاردة أو تاريخ جاي."
    if is_weekly_rest_weekday(officer.rest_day, leave["start"]):
        return "اليوم المختار هو يوم الراحة الأسبوعية الثابتة؛ اختار يوم إضافي مختلف."
    return None


def stats(data, filters):
    """إحصائيات راحات الضباط — قابلة للتصفية بالشهر/النوع/الحالة.

    كل حاجة بترجع من هنا معروضة فعلًا في الصفحة. أي مؤشر إضافي (تزامن
    الراحات، الالتزام بالكشف الشهري، مقارنة ضباط/أفراد) اتشال لأنه كان
    بيتحسب في كل طلب وماحدش بيقراه — نص زمن الدالة كان رايح في حلقة
    يوم-بيوم على كل الراحات عشان رسم مش موجود في الواجهة أصلًا.
    """
    from .repo import LeaveRepo

    all_leaves = data.get("leaves", [])
    today_str = date.today().isoformat()
    names = LeaveRepo(data).names()      # الاسم من سجل القوة مش من سجل الراحة

    month_from = filters.get("month_from", "")
    month_to = filters.get("month_to", "")
    leave_type = filters.get("type", "")
    status_filter = filters.get("status", "")

    def leave_status(lv):
        s, e = lv.get("start", ""), lv.get("end", "")
        return "جارية" if s <= today_str <= e else ("قادمة" if s > today_str else "منتهية")

    def leave_days(lv):
        try:
            s = date.fromisoformat(lv["start"])
            e = date.fromisoformat(lv["end"])
            return (e - s).days + 1
        except (KeyError, ValueError):
            return 0

    leaves = []
    for lv in all_leaves:
        m = (lv.get("start") or "")[:7]
        if month_from and m and m < month_from:
            continue
        if month_to and m and m > month_to:
            continue
        if leave_type and leave_type != "الكل" and lv.get("type") != leave_type:
            continue
        if status_filter and status_filter != "الكل" and leave_status(lv) != status_filter:
            continue
        leaves.append(lv)

    # ترتيب الأيام لازم يطابق date.weekday() (الاثنين=0 ... الأحد=6)
    weekday_by_index = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]

    by_type = defaultdict(int)
    by_month = defaultdict(int)
    by_weekday = defaultdict(int)
    duration_buckets = {"1 يوم": 0, "2-3 أيام": 0, "4-7 أيام": 0, "أكثر من 7": 0}
    status_counts = {"جارية": 0, "قادمة": 0, "منتهية": 0}
    by_officer = {}
    total_days = 0

    for lv in leaves:
        by_type[lv.get("type", "غير محدد")] += 1

        m = (lv.get("start") or "")[:7]
        if m:
            by_month[m] += 1

        n = leave_days(lv)
        total_days += n
        if n == 1:
            duration_buckets["1 يوم"] += 1
        elif n <= 3:
            duration_buckets["2-3 أيام"] += 1
        elif n <= 7:
            duration_buckets["4-7 أيام"] += 1
        elif n > 7:
            duration_buckets["أكثر من 7"] += 1

        status_counts[leave_status(lv)] += 1

        try:
            by_weekday[weekday_by_index[date.fromisoformat(lv["start"]).weekday()]] += 1
        except (KeyError, ValueError):
            pass

        pid = lv.get("person_id", "")
        entry = by_officer.setdefault(pid, {"name": names.get(pid, pid), "count": 0, "days": 0})
        entry["count"] += 1
        entry["days"] += n

    top_officers = sorted(by_officer.values(), key=lambda x: x["count"], reverse=True)[:10]
    avg_duration = round(total_days / len(leaves), 1) if leaves else 0

    cumulative, running = [], 0
    for m in sorted(by_month):
        running += by_month[m]
        cumulative.append({"month": m, "total": running})

    all_months = sorted({(lv.get("start") or "")[:7] for lv in all_leaves if (lv.get("start") or "")[:7]})
    all_types = sorted({lv.get("type", "") for lv in all_leaves if lv.get("type")})

    return {
        "summary": {
            "total": len(leaves),
            "total_days": total_days,
            "avg_duration": avg_duration,
            "current": status_counts["جارية"],
            "upcoming": status_counts["قادمة"],
        },
        "by_type": dict(by_type),
        "by_month": dict(sorted(by_month.items())),
        "by_weekday": dict(by_weekday),
        "duration_buckets": duration_buckets,
        "status_counts": status_counts,
        "cumulative": cumulative,
        "top_officers": top_officers,
        "meta_options": {"months": all_months, "types": all_types},
    }

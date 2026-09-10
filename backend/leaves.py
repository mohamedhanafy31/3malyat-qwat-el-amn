"""الراحات والإجازات — بناء سجل راحة والتحقق من التداخل."""
from collections import defaultdict
from datetime import date, timedelta

from .constants import LEAVE_TYPES
from .date_range import overlapping_of, parse_range
from .people import find_person


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
    for o in data["officers"]["active"]:
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
        out.append({"id": o["id"], "name": o.get("name", ""), "role": o.get("role", ""),
                    "rest_system": system, "status": status, "current": info})
    return out


def stats(data, filters):
    """إحصائيات شاملة للراحات — قابلة للتصفية بالشهر/النوع/الحالة/الفئة.

    `officer_ids`/`personnel_ids` قبل كده كانوا بيتحسبوا من
    `data.get("officers", [])` كأنها قايمة مسطّحة، بينما هي فعليًا
    `{"active": [...], "archive": [...]}` — فأي مقارنة `pid in officer_ids`
    كانت بتقارن بمفاتيح الديكشنري ("active"/"archive") مش بمعرّفات
    الضباط، فكان فلتر الفئة بيرجّع صفر نتيجة دايمًا.
    """
    all_leaves = data.get("leaves", [])
    today = date.today()
    today_str = today.isoformat()

    officer_ids = {p["id"] for p in data["officers"]["active"] + data["officers"]["archive"]}
    personnel_ids = {p["id"] for p in data["personnel"]["active"] + data["personnel"]["archive"]}
    officers_by_id = {p["id"]: p for p in data["officers"]["active"] + data["officers"]["archive"]}

    month_from = filters.get("month_from", "")
    month_to = filters.get("month_to", "")
    leave_type = filters.get("type", "")
    status_filter = filters.get("status", "")
    category_filter = filters.get("category", "")

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

    # فلاتر الشهر/النوع/الحالة من غير فلتر الفئة — مستخدمة في مقارنة
    # ضباط/أفراد تحت، عشان لو حد فلتر على فئة معيّنة يفضل يشوف إن الفئة
    # التانية أصلاً مالهاش سجلات (بدل ما الرسم يختفي من غير تفسير).
    leaves_any_category = []
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
        leaves_any_category.append(lv)

    leaves = []
    for lv in leaves_any_category:
        pid = lv.get("person_id", "")
        if category_filter in ("officers", "ضباط") and pid not in officer_ids:
            continue
        if category_filter in ("personnel", "أفراد") and pid not in personnel_ids:
            continue
        leaves.append(lv)

    by_type = defaultdict(int)
    for lv in leaves:
        by_type[lv.get("type", "غير محدد")] += 1

    by_month = defaultdict(int)
    for lv in leaves:
        m = (lv.get("start") or "")[:7]
        if m:
            by_month[m] += 1

    duration_buckets = {"1 يوم": 0, "2-3 أيام": 0, "4-7 أيام": 0, "أكثر من 7": 0}
    total_days = 0
    for lv in leaves:
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

    # ترتيب الأيام لازم يطابق date.weekday() (الاثنين=0 ... الأحد=6) —
    # كان فيه إزاحة يوم كاملة هنا (day_names كان بادئ بـ"الأحد" في
    # الإندكس صفر) فكل الراحات كانت بتتحسب على يوم غلط في رسم توزيع
    # الأيام (مثلاً راحة بدأت الاثنين كانت بتتحسب "الأحد").
    weekday_by_index = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
    by_weekday = defaultdict(int)
    for lv in leaves:
        try:
            s = date.fromisoformat(lv["start"])
            by_weekday[weekday_by_index[s.weekday()]] += 1
        except (KeyError, ValueError):
            pass

    by_officer = {}
    for lv in leaves:
        pid = lv.get("person_id", "")
        name = lv.get("name", pid)
        entry = by_officer.setdefault(pid, {"name": name, "count": 0, "days": 0})
        entry["count"] += 1
        entry["days"] += leave_days(lv)
    top_officers = sorted(by_officer.values(), key=lambda x: x["count"], reverse=True)[:10]

    status_counts = {"جارية": 0, "قادمة": 0, "منتهية": 0}
    for lv in leaves:
        status_counts[leave_status(lv)] += 1

    sorted_months = sorted(by_month.keys())
    cumulative, running = [], 0
    for m in sorted_months:
        running += by_month[m]
        cumulative.append({"month": m, "total": running})

    avg_duration = round(total_days / len(leaves), 1) if leaves else 0

    all_months = sorted({(lv.get("start") or "")[:7] for lv in all_leaves if (lv.get("start") or "")[:7]})
    all_types = sorted({lv.get("type", "") for lv in all_leaves if lv.get("type")})

    # ── ضباط/أفراد: التصنيف بيوضح إن كل سجلات الراحة الحالية بتاعة
    # الضباط فقط رغم إن الأفراد أكتر عدد بكتير — فجوة بيانات لازم تتشاف
    # في الداشبورد مش تختفي لما حد يفلتر على "أفراد" فيلاقي رسم فاضي.
    cat_officers = {"count": 0, "days": 0}
    cat_personnel = {"count": 0, "days": 0}
    cat_unknown = {"count": 0, "days": 0}
    for lv in leaves_any_category:
        pid = lv.get("person_id", "")
        bucket = cat_officers if pid in officer_ids else (cat_personnel if pid in personnel_ids else cat_unknown)
        bucket["count"] += 1
        bucket["days"] += leave_days(lv)

    active_officers = len(data["officers"]["active"])
    active_personnel = len(data["personnel"]["active"])
    if category_filter in ("officers", "ضباط"):
        relevant_headcount = active_officers
    elif category_filter in ("personnel", "أفراد"):
        relevant_headcount = active_personnel
    else:
        relevant_headcount = active_officers + active_personnel
    avg_days_per_person = round(total_days / relevant_headcount, 2) if relevant_headcount else 0

    # ── الكشف الشهري/نصف الشهري: كام ضابط فات معاد راحته وماحدش سجّل
    # التالي (due) — مؤشر تشغيلي مباشر مش موجود في الداشبورد خالص قبل كده،
    # رغم إن monthly_roster() أصلاً موجودة ومستخدمة في شاشة تانية.
    roster = monthly_roster(data, today)
    monthly_compliance = {"active": 0, "upcoming": 0, "due": 0, "due_officers": []}
    for r in roster:
        monthly_compliance[r["status"]] += 1
        if r["status"] == "due":
            monthly_compliance["due_officers"].append({"name": r["name"], "rest_system": r["rest_system"]})

    # ── الالتزام بيوم الراحة الأسبوعي المحدد لكل ضابط (rest_day) — قايس
    # مباشر لانضباط جدولة الراحة الأسبوعية، مش مجرد عدّها.
    on_day = off_day = no_rest_day = 0
    for lv in leaves:
        if lv.get("type") != "أسبوعية":
            continue
        officer = officers_by_id.get(lv.get("person_id"))
        rest_day = (officer or {}).get("rest_day", "")
        if not rest_day:
            no_rest_day += 1
            continue
        try:
            s = date.fromisoformat(lv["start"])
        except (KeyError, ValueError):
            continue
        if weekday_by_index[s.weekday()] == rest_day:
            on_day += 1
        else:
            off_day += 1
    weekly_total = on_day + off_day
    weekly_compliance = {
        "on_day": on_day, "off_day": off_day, "no_rest_day": no_rest_day,
        "rate": round(on_day / weekly_total * 100, 1) if weekly_total else None,
    }

    # ── تزامن الراحات: كام حد غايب في نفس اليوم بالظبط. ده اللي بيحدد
    # الأيام اللي فيها خطورة على التغطية اليومية، مش مجرد "كام راحة بدأت"
    # زي الرسم الشهري. بيتحسب على مدى تواريخ الراحات المفلترة فقط.
    daily_load = defaultdict(int)
    for lv in leaves:
        try:
            s = date.fromisoformat(lv["start"])
            e = date.fromisoformat(lv["end"])
        except (KeyError, ValueError):
            continue
        cur = s
        while cur <= e:
            daily_load[cur.isoformat()] += 1
            cur += timedelta(days=1)

    top_days = sorted(daily_load.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
    concurrent_load = {
        "max": max(daily_load.values()) if daily_load else 0,
        "avg": round(sum(daily_load.values()) / len(daily_load), 2) if daily_load else 0,
        "top_days": [{"date": d, "count": c} for d, c in top_days],
    }
    if concurrent_load["max"] and relevant_headcount:
        concurrent_load["max_pct"] = round(concurrent_load["max"] / relevant_headcount * 100, 1)
    else:
        concurrent_load["max_pct"] = None

    return {
        "summary": {
            "total": len(leaves),
            "total_days": total_days,
            "avg_duration": avg_duration,
            "avg_days_per_person": avg_days_per_person,
            "current": status_counts["جارية"],
            "upcoming": status_counts["قادمة"],
        },
        "by_type": dict(by_type),
        "by_month": dict(sorted(by_month.items())),
        "duration_buckets": duration_buckets,
        "by_weekday": dict(by_weekday),
        "top_officers": top_officers,
        "status_counts": status_counts,
        "cumulative": cumulative,
        "headcount": {
            "officers": active_officers,
            "personnel": active_personnel,
            "relevant": relevant_headcount,
        },
        "category_breakdown": {
            "officers": cat_officers,
            "personnel": cat_personnel,
            "unknown": cat_unknown,
        },
        "monthly_compliance": monthly_compliance,
        "weekly_compliance": weekly_compliance,
        "concurrent_load": concurrent_load,
        "meta_options": {
            "months": all_months,
            "types": all_types,
        },
    }

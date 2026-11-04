"""الراحات والإجازات — بناء سجل راحة والتحقق من التداخل."""
import re
from collections import defaultdict
from datetime import date, datetime, timedelta

from .constants import LEAVE_TYPES, LEGACY_LEAVE_TYPES
from .date_range import overlapping_of, parse_range
from .people import find_person
from .utils import MAX_LEN

MAX_NOTE = MAX_LEN["note"]
HISTORY_KEY = "leave_history"
HISTORY_ACTIONS = frozenset({"delete", "cancel", "stop"})


def _person_meta(data, person_id):
    from .repo import PeopleRepo
    raw, category, bucket = PeopleRepo(data).locate(person_id)
    return raw or {}, category or "", bucket or ""


def _origin_label(leave):
    origin = str((leave or {}).get("origin", "") or "")
    if origin == "auto_weekly":
        return "أسبوعية ثابتة"
    if origin == "weekly_extra":
        return "أسبوعية إضافية"
    if (leave or {}).get("type") in MONTHLY_REST_SYSTEMS:
        return "كشف راحات"
    if (leave or {}).get("source"):
        return "أرشيف / استيراد"
    return "يدوي"


def _suspension_of(change, after):
    """رقم أمر الوقف لو الحدث نتيجة أمر وقف راحات (إيقاف أو إلغاء قبل البدء)."""
    sid = (after or {}).get("suspension_id")
    if sid:
        return sid
    found = re.search(r"أمر وقف\s+(\S+?)\)", change.get("text") or "")
    return found.group(1) if found else ""


_ACTION_LABELS = {"delete": "حذف", "cancel": "إلغاء قبل البدء", "stop": "إنهاء مبكر"}


def history(data):
    return data.setdefault(HISTORY_KEY, [])


def record_history(data, change):
    """يثبّت حدث راحة قابلًا للاسترجاع من سطر تغيير ذي لقطات صريحة."""
    if not change or change.get("entity") != "leave" or change.get("action") not in HISTORY_ACTIONS:
        return None
    if any(row.get("change_id") == change.get("id") for row in history(data)):
        return None
    before = dict(change.get("before") or {})
    after = dict(change.get("after") or {}) if change.get("after") else None
    if not before or not before.get("person_id"):
        return None
    raw, category, _ = _person_meta(data, before["person_id"])
    from .store import reserve_id
    row = {
        "id": reserve_id(data, "LVH", history(data)),
        "change_id": change.get("id"),
        "leave_id": change.get("entity_id") or before.get("id"),
        "action": change.get("action"),
        "before": before,
        "after": after,
        "reason": change.get("reason") or "",
        "suspension_id": _suspension_of(change, after),
        "occurred_at": change.get("ts") or "",
        "performed_by": change.get("edited_by") or "النظام",
        "person_name": raw.get("name", ""),
        "person_category": category,
        "restored_at": "",
        "restored_by": "",
        "restored_leave_id": "",
        "restore_change_id": "",
    }
    history(data).append(row)
    return row


def backfill_history(data):
    """يحوّل حذف/إلغاء/إيقاف change_log الحالي إلى السجل الدائم، مرة واحدة."""
    added = 0
    for change in data.get("change_log") or []:
        if record_history(data, change):
            added += 1
    return added


def history_rows(data):
    """نسخة عرض، الأحدث أولًا، من غير تعديل البيانات المخزنة."""
    out = []
    for stored in reversed(data.get(HISTORY_KEY) or []):
        row = dict(stored)
        before = row.get("before") or {}
        raw, category, bucket = _person_meta(data, before.get("person_id", ""))
        row["person_name"] = row.get("person_name") or raw.get("name", "")
        row["person_category"] = row.get("person_category") or category
        row["person_archived"] = bucket == "archive"
        row["origin_label"] = _origin_label(before)
        row["action_label"] = ("وقف راحات" if row.get("suspension_id")
                               else _ACTION_LABELS.get(row.get("action"), ""))
        row.setdefault("suspension_id", "")
        row["display_type"] = leave_label(before)
        out.append(row)
    return out


def _restore_fail(message, status=400):
    from flask import jsonify
    from .store import AbortRequest
    raise AbortRequest((jsonify({"error": message}), status))


def mark_history_restored(data, leave_id, actions, restored_leave_id, restore_change):
    """يعلّم أحدث بند مطابق؛ تستخدمها أيضًا استعادة أمر الوقف القديمة."""
    event = next((row for row in reversed(history(data))
                  if row.get("leave_id") == leave_id
                  and row.get("action") in set(actions)
                  and not row.get("restored_at")), None)
    if not event:
        return None
    event.update({
        "restored_at": restore_change.get("ts") or datetime.now().isoformat(timespec="seconds"),
        "restored_by": restore_change.get("edited_by") or "النظام",
        "restored_leave_id": restored_leave_id,
        "restore_change_id": restore_change.get("id") or "",
    })
    return event


def restore_history(data, event_id):
    """يعيد لقطة الحذف/الإلغاء أو الحالة السابقة للإنهاء المبكر."""
    from . import changes, rest_suspension, retro
    from .models import Leave
    from .repo import Repos

    event = next((row for row in history(data) if row.get("id") == event_id), None)
    if not event:
        _restore_fail("بند سجل الراحة غير موجود.", 404)
    if event.get("restored_at"):
        _restore_fail("تم استرجاع هذا البند بالفعل، ولا يمكن استرجاعه مرة أخرى.", 409)

    snapshot = dict(event.get("before") or {})
    person_id = snapshot.get("person_id", "")
    raw, category, bucket = _person_meta(data, person_id)
    if not raw:
        _restore_fail("لا يمكن الاسترجاع لأن سجل صاحب الراحة لم يعد موجودًا.", 409)
    if category == "officers" and bucket == "archive":
        _restore_fail("لا يمكن الاسترجاع لأن الضابط موجود في الأرشيف. أعده إلى القوة أولًا.", 409)

    candidate = Leave.from_dict(snapshot)
    errors = candidate.validate()
    if errors:
        _restore_fail(errors[0])
    person = Repos(data).people.find(person_id)
    service_error = candidate.within_service(person)
    if service_error:
        _restore_fail(f"لا يمكن الاسترجاع: {service_error}", 409)

    repos = Repos(data)
    current = repos.leaves.find(event.get("leave_id", ""))
    is_stop = event.get("action") == "stop"
    if is_stop:
        if not current:
            _restore_fail("سجل الراحة الحالي غير موجود؛ استرجع بند الحذف الأحدث أولًا.", 409)
        expected = event.get("after") or {}
        if current.as_dict() != expected:
            _restore_fail("تغيّر سجل الراحة بعد الإنهاء المبكر؛ راجع التعديل الأحدث قبل الاسترجاع.", 409)
        ignore_id = current.id
    else:
        ignore_id = None

    blocked = rest_suspension.blocking(data, snapshot,
                                        current=current.as_dict() if current else None)
    if blocked:
        _restore_fail(blocked, 409)
    clash = overlapping(data, snapshot, ignore_id=ignore_id)
    if clash:
        _restore_fail("لا يمكن الاسترجاع لوجود راحة أخرى للشخص نفسه في المدة "
                      f"({clash['start']} ← {clash['end']}).", 409)

    closed = retro.closed_days_in(data, snapshot.get("start", ""), snapshot.get("end", ""))
    reason = retro.require_reason(closed)

    original_id = snapshot.get("id") or event.get("leave_id")
    if is_stop:
        restored_id = current.id
        repos.leaves.replace(candidate)
    else:
        if repos.leaves.find(original_id):
            candidate.id = repos.leaves.new_id()
        restored_id = candidate.id
        repos.leaves.add(candidate)

    name = raw.get("name", "")
    change = changes.record(
        data, "leave", restored_id, "restore", before=current.as_dict() if current else None,
        after=candidate.as_dict(), reason=reason,
        text=f"استرجاع راحة {name} ({leave_label(snapshot)} {snapshot.get('start')} ← {snapshot.get('end')}) "
             f"من سجل المحذوفة والملغية ({event_id})",
    )
    mark_history_restored(data, event.get("leave_id"), {event.get("action")}, restored_id, change)
    if closed:
        retro.log_retro(data, "leave", restored_id, closed, reason,
                        before=current.as_dict() if current else None, after=candidate.as_dict())
    return repos.leaves.named(candidate), event


def leave_label(leave):
    """الاسم المعروض للنوع، مع وصف الإجازة الخاصة إن وُجد."""
    kind = str((leave or {}).get("type", "") or "").strip()
    special = str((leave or {}).get("special_name", "") or "").strip()
    return f"إجازة خاصة — {special}" if kind == "إجازة خاصة" and special else kind


def build_leave(payload, data, leave_id, current_type=None):
    """``current_type`` نوع السجل قبل التعديل: سجل أرشيفي بنوع ملغي («راحة
    فرقة») ينفع يتعدّل وهو محتفظ بنوعه، لكن مفيش سجل جديد يتعمل بيه."""
    person_id = str(payload.get("person_id", "")).strip()
    person, _, _ = find_person(data, person_id)
    if not person:
        return None, "يرجى اختيار الشخص."

    kind = str(payload.get("type", "")).strip()
    if kind in LEGACY_LEAVE_TYPES and kind != current_type:
        return None, f"نوع «{kind}» لم يعد متاحًا — الفرقة تُسجّل من صفحة الفرق."
    if kind not in LEAVE_TYPES and kind not in LEGACY_LEAVE_TYPES:
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

    special_name = str(payload.get("special_name", "") or "").strip()
    if kind == "إجازة خاصة" and not special_name:
        return None, "اكتب اسم الإجازة الخاصة (مثال: إجازة عيد)."
    if len(special_name) > 80:
        return None, "اسم الإجازة الخاصة أطول من الحد المسموح (80 حرفًا)."

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
        "special_name": special_name if kind == "إجازة خاصة" else "",
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
    from .people import effective
    from .rest_suspension import suspended_types

    suspended = suspended_types(data)

    for o in PeopleRepo(data).bucket("officers", "active"):
        eff = effective(o, today_iso)
        system = eff.get("rest_system", "")
        if system not in MONTHLY_REST_SYSTEMS:
            continue
        candidates = [lv for lv in leaves_of(data, o["id"]) if lv.get("type") == system]
        current = max(candidates, key=lambda lv: lv["start"], default=None)
        status, info = "due", None
        if current:
            if current["start"] <= today_iso <= current["end"]:
                status, info = "active", {"id": current.get("id"),
                                           "start": current["start"], "end": current["end"]}
            elif current["start"] > today_iso:
                status, info = "upcoming", {"id": current.get("id"),
                                             "start": current["start"], "end": current["end"]}
        # نوع راحته موقوف بأمر — مش «متأخر» عن تسجيل الكشف، هو ممنوع يتسجّل أصلًا
        if status == "due" and system in suspended:
            order = suspended[system]
            status, info = "suspended", {"since": order.get("started_on"), "id": order.get("id")}
        out.append({"id": o["id"], "name": o.get("name", ""), "role": eff.get("role", ""),
                    "rest_system": system, "status": status, "current": info})
    return out


def weekly_roster(data, today):
    """ضباط الراحة الأسبوعية الحاليون + الموعد الثابت والسجلات القادمة.

    الموعد الثابت معلومة جدول، والسجلات القادمة حقيقة مخزنة؛ الاتنين
    بيرجعوا منفصلين عشان الواجهة ماتعرضش التخمين كأنه سجل راحة.
    """
    from .repo import PeopleRepo
    from .rest_status import is_weekly_rest_weekday, next_weekday
    from .people import effective

    today_iso = today.isoformat()
    out = []
    for officer in PeopleRepo(data).active("officers"):
        eff = effective(officer.as_dict(), today_iso)
        if eff["rest_system"] != "أسبوعية" or not eff["rest_day"]:
            continue
        fixed = today if is_weekly_rest_weekday(eff["rest_day"], today_iso) \
            else next_weekday(eff["rest_day"], today)
        upcoming = [
            {k: lv.get(k, "") for k in ("id", "start", "end", "origin")}
            for lv in leaves_of(data, officer.id)
            if lv.get("type") == "أسبوعية" and lv.get("start", "") >= today_iso
        ]
        upcoming.sort(key=lambda lv: (lv["start"], lv["id"]))
        out.append({
            "id": officer.id, "name": officer.name, "role": eff["role"],
            "rest_day": eff["rest_day"],
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
    from .people import effective
    eff = effective(officer.as_dict(), leave.get("start", today)) if officer else {}
    if not officer or officer.archived or eff.get("rest_system") != "أسبوعية":
        return "الراحة الإضافية متاحة فقط لضابط على القوة بنظام راحة أسبوعية."
    if leave.get("type") != "أسبوعية" or leave.get("start") != leave.get("end"):
        return "يجب أن تكون الراحة الأسبوعية الإضافية يومًا واحدًا."
    if leave.get("start", "") < today:
        return "يجب أن تكون الراحة الأسبوعية الإضافية اليوم أو في تاريخ لاحق."
    if is_weekly_rest_weekday(eff.get("rest_day"), leave["start"]):
        return "اليوم المختار هو يوم الراحة الأسبوعية الثابتة؛ اختر يومًا إضافيًا مختلفًا."
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

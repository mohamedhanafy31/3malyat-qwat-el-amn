"""وقف الراحات — أمر عام بيوقف أنواع راحة معيّنة للضباط، وإيقاف راحة ضابط
بعينه قبل نهايتها.

**الأمر العام**: المشغّل بيختار الأنواع من `LEAVE_TYPES` (كلها، فأي نوع
جديد بيظهر تلقائي). الأمر بيفضل ساري لحد ما يتفتح صراحةً («فتح الراحات»)
— مالوش تاريخ نهاية. وهو ساري، تسجيل راحة جديدة من نوع موقوف لضابط
بيترفض. فتح الراحات **مابيرجّعش** أي راحة اتوقفت؛ بعده الضباط بيتسكّنوا في
راحة عادي من جديد.

وقت إنشاء الأمر، راحات الضباط الجارية والقادمة من الأنواع دي بتتعرض
للمشغّل وهو يختار منها اللي تتوقف — مفيش إيقاف تلقائي.

**إيقاف راحة واحدة**: `on` = أول يوم رجوع للعمل. الراحة بتتقص لحد اليوم
اللي قبله، والتاريخ الأصلي بيفضل في `original_end` — مش بيتكتب فوقه في صمت
زي التعديل العادي. راحة لسه ما بدأتش بتتلغي بالكامل (مدة صفر مش سجل
صالح)، وسجلها الكامل بيفضل في سجل التغييرات.

الإيقاف مالوش أي علاقة بمنطق التسكين نفسه — الراحة أصلًا مابتمنعش التسكين
(`checks.py`: تنبيه مش رفض). اللي بيتغيّر إن `leave_on` بطّل يلاقي راحة في
الأيام دي، فالضابط بيرجع للقوة: بيظهر في بحث التسكين، ومابيتحسبش في
الخوارج في جدول الإجمالي.

الموديول ده مايستوردش `rest_status` — العكس هو اللي بيحصل.
"""
from datetime import datetime, timedelta

from flask import jsonify

from . import changes, retro
from .constants import LEAVE_TYPES
from .store import AbortRequest, reserve_id
from .utils import MAX_LEN, parse_date

KEY = "rest_suspensions"
STOP_FIELDS = ("original_end", "stopped_on", "stop_reason", "suspension_id")
_LOCKED_ON_STOPPED = ("person_id", "type", "start", "end")


def _fail(message, status=400):
    raise AbortRequest((jsonify({"error": message}), status))


# ---------- قراءة (من غير setdefault — عشان core.json مايتكتبش على الفاضي) ----------

def all_orders(data):
    return data.get(KEY) or []


def active(data):
    return [o for o in all_orders(data) if not o.get("lifted_on")]


def suspended_types(data):
    """{نوع: الأمر الساري اللي موقفه}."""
    return {t: o for o in active(data) for t in o.get("types", [])}


def is_suspended_on(data, kind, day):
    """النوع ده كان موقوف في اليوم ده؟ — بيشمل الأوامر اللي اتفتحت بعد
    اليوم ده، عشان الأيام اللي فاتت جوّه مدة الأمر تفضل محسوبة صح."""
    for o in all_orders(data):
        if kind not in o.get("types", []):
            continue
        lifted = o.get("lifted_on") or ""
        if o.get("started_on", "") <= day and (not lifted or day < lifted):
            return True
    return False


def _ordered(types):
    return [t for t in LEAVE_TYPES if t in types]


def summary(data):
    """اللي الواجهة محتاجاه في كل صفحة (بانر + تلميح نموذج الراحة)."""
    rows = active(data)
    return {
        "types": _ordered({t for o in rows for t in o.get("types", [])}),
        "active": [{k: o.get(k) for k in ("id", "types", "started_on", "reason")} for o in rows],
    }


def _with_stopped(data, order):
    """نسخة من الأمر ومعاها الراحات اللي أوقفها (من السجلات نفسها، بـ
    `suspension_id`) — نسخة عشان العرض مايتخزّنش جوّه البيانات."""
    from .repo import Repos
    repos = Repos(data)
    stopped = [repos.leaves.named(lv) for lv in repos.leaves.all()
               if lv.suspension_id == order.get("id")]
    return {**order, "stopped_leaves": stopped}


def listing(data):
    orders = all_orders(data)
    history = [o for o in orders if o.get("lifted_on")]
    history.sort(key=lambda o: (o.get("lifted_on", ""), o.get("id", "")), reverse=True)
    return {"active": [_with_stopped(data, o) for o in active(data)],
            "history": [_with_stopped(data, o) for o in history[:20]],
            "leave_types": LEAVE_TYPES}


def on_day(data, day):
    """لشريط اليومية التفصيلية ويومية الضباط: الأنواع الموقوفة في اليوم ده،
    والضباط اللي رجعوا للعمل فيه بسبب إيقاف راحتهم — دول اللي محتاجين
    يتسكّنوا، فلازم يبانوا في مكان التسكين نفسه مش في صفحة الراحات بس."""
    from .repo import PeopleRepo, Repos

    people = PeopleRepo(data)
    returned = []
    for lv in Repos(data).leaves.all():
        if lv.stopped_on != day:
            continue
        raw, category, _ = people.locate(lv.person_id)
        if category != "officers":
            continue
        returned.append({"person_id": lv.person_id, "name": raw.get("name", ""),
                         "role": raw.get("role", ""), "type": lv.type,
                         "original_end": lv.original_end, "stop_reason": lv.stop_reason})
    return {"types": [t for t in LEAVE_TYPES if is_suspended_on(data, t, day)],
            "returned": returned}


def _is_officer(data, person_id):
    from .repo import PeopleRepo
    _, category, _ = PeopleRepo(data).locate(person_id)
    return category == "officers"


# ---------- الحراسة على تسجيل/تعديل الراحات ----------

def blocking(data, leave, current=None):
    """رسالة الرفض لو الراحة دي ممنوعة بسبب أمر وقف ساري — أو None.

    بتمنع بس: ضابط + نوع موقوف + الراحة لسه ماخلصتش قبل بداية الأمر (راحة
    قديمة خلصت قبل الأمر ينفع تتسجّل متأخر). في التعديل (`current`)، الرفض
    بس لو التعديل **بيدخل** في الوقف أو **بيوسّعه** — تقصير راحة موجودة أو
    تعديل ملاحظتها مسموح، لأن المشغّل اختار بنفسه مايوقفهاش.
    """
    if not _is_officer(data, leave.get("person_id")):
        return None
    order = suspended_types(data).get(leave.get("type"))
    if not order or leave.get("end", "") < order.get("started_on", ""):
        return None
    if current is not None and not (
            leave.get("type") != current.get("type")
            or leave.get("start", "") < current.get("start", "")
            or leave.get("end", "") > current.get("end", "")):
        return None
    return (f"الراحات «{leave.get('type')}» موقوفة حاليًا (أمر وقف من "
            f"{order.get('started_on')}) — لازم «فتح الراحات» الأول.")


def edit_guard(current, leave):
    """راحة اتوقفت قبل كده: تواريخها ونوعها وصاحبها مقفولين (الملاحظة بس
    تتعدّل). وفي كل الأحوال بيرحّل حقول الإيقاف للسجل الجديد — `build_leave`
    بيبني dict جديد بحقوله هو بس، فمن غير ده أي تعديل كان هيمسحها."""
    if current.get("stopped_on") and any(
            str(leave.get(f, "")) != str(current.get(f, "")) for f in _LOCKED_ON_STOPPED):
        _fail("الراحة دي اتوقفت — تواريخها مقفولة؛ امسحها وسجّل من جديد لو محتاج.")
    for f in STOP_FIELDS:
        if current.get(f):
            leave[f] = current[f]


# ---------- المرشّحين للإيقاف ----------

def candidates(data, types, today):
    """راحات الضباط (على القوة) الجارية والقادمة من الأنواع دي."""
    from .repo import PeopleRepo, Repos
    from .utils import command_priority_map, rank_key

    types = set(types)
    if not types:
        return []
    officers = {o["id"]: o for o in PeopleRepo(data).bucket("officers", "active")}
    priority = command_priority_map(data)
    out = []
    for lv in Repos(data).leaves.all():
        officer = officers.get(lv.person_id)
        if not officer or lv.type not in types or lv.end < today:
            continue
        upcoming = lv.start > today
        new_end = (parse_date(today) - timedelta(days=1)).isoformat()
        out.append({
            "leave_id": lv.id, "person_id": lv.person_id,
            "name": officer.get("name", ""), "role": officer.get("role", ""),
            "type": lv.type, "start": lv.start, "end": lv.end,
            "state": "upcoming" if upcoming else "active",
            "effect": "cancel" if lv.start >= today else "trim",
            "new_end": None if lv.start >= today else new_end,
            "return_date": today,
            "_rank": rank_key(officer, priority),
        })
    out.sort(key=lambda r: (r["state"] != "active", r["start"], r["_rank"]))
    for r in out:
        r.pop("_rank")
    return out


# ---------- إيقاف راحة واحدة ----------

def stop_leave(data, leave_id, reason, on=None, suspension_id=None, today=None):
    """-> {"leave": السجل بعد القص أو None, "cancelled": bool}."""
    from . import day_status
    from .repo import Repos

    repos = Repos(data)
    lv = repos.leaves.find(leave_id)
    if not lv:
        _fail("سجل الراحة غير موجود.", 404)
    if not _is_officer(data, lv.person_id):
        _fail("إيقاف الراحة للضباط بس.")
    reason = str(reason or "").strip()
    if not reason:
        _fail("لازم سبب مكتوب لإيقاف الراحة.")
    if len(reason) > MAX_LEN["note"]:
        _fail(f"السبب أطول من الحد المسموح ({MAX_LEN['note']} حرف).")

    today = today or day_status.today_iso()
    on = on or today
    on_date = parse_date(on)
    if not on_date:
        _fail("تاريخ الإيقاف غير صحيح.")
    on = on_date.isoformat()
    if lv.end < today:
        _fail("الراحة دي خلصت بالفعل — عدّلها من «تعديل» لو محتاج.")
    if on > lv.end:
        _fail("تاريخ الإيقاف بعد نهاية الراحة — مفيش حاجة تتوقف.")

    name = repos.leaves.name_of(lv.person_id)
    before = lv.as_dict()
    closed = retro.closed_days_in(data, max(on, lv.start), lv.end)
    by_order = f" (أمر وقف {suspension_id})" if suspension_id else ""

    if on <= lv.start:
        repos.leaves.remove(lv.id)
        changes.record(data, "leave", lv.id, "cancel", before=before, reason=reason,
                       text=f"إلغاء راحة {name} ({lv.type} {lv.start} ← {lv.end}) "
                            f"قبل بدايتها{by_order} — السبب: {reason}")
        if closed:
            retro.log_retro(data, "leave", lv.id, closed, reason, before=before)
        from .repo import PeopleRepo
        raw, _, _ = PeopleRepo(data).locate(lv.person_id)
        # السجل نفسه اتمسح — اللقطة دي اللي صفحة الوقف بتعرضها تحت الأمر،
        # وهي كاملة (بـperson_id) عشان «فتح الراحات» في نفس يوم الوقف يقدر
        # يرجّعها زي ما كانت. متسجّلة في `references.py` زي أي مرجع لشخص.
        snapshot = {"leave_id": lv.id, "person_id": lv.person_id, "name": name,
                    "role": (raw or {}).get("role", ""), "type": lv.type,
                    "start": lv.start, "end": lv.end, "return_date": lv.return_date,
                    "note": lv.note, "source": lv.source}
        return {"leave": None, "cancelled": True, "snapshot": snapshot}

    original_end = lv.original_end or lv.end
    lv.original_end = original_end
    lv.end = (on_date - timedelta(days=1)).isoformat()
    lv.return_date = on
    lv.stopped_on = on
    lv.stop_reason = reason
    if suspension_id:
        lv.suspension_id = suspension_id
    repos.leaves.save(lv)
    after = lv.as_dict()
    changes.record(data, "leave", lv.id, "stop", before=before, after=after, reason=reason,
                   text=f"إيقاف راحة {name} ({lv.type}): كانت لحد {original_end} ← "
                        f"آخر يوم بقى {lv.end}، العودة {on}{by_order} — السبب: {reason}")
    if closed:
        retro.log_retro(data, "leave", lv.id, closed, reason, before=before, after=after)
    return {"leave": repos.leaves.named(lv), "cancelled": False}


# ---------- الأمر العام ----------

def create(data, payload, today):
    """-> (الأمر, {"stopped": [...], "cancelled": [...]}). أي خطأ جوّه بيلغي
    الطلب كله (`with_data` مابيحفظش)، فالعملية ذرّية."""
    raw_types = payload.get("types")
    if not isinstance(raw_types, list) or not raw_types:
        _fail("اختار نوع راحة واحد على الأقل.")
    unknown = [t for t in raw_types if t not in LEAVE_TYPES]
    if unknown:
        _fail(f"نوع راحة غير معروف: {'، '.join(map(str, unknown))}")
    types = _ordered(set(raw_types))

    reason = str(payload.get("reason", "") or "").strip()
    if not reason:
        _fail("لازم سبب مكتوب لأمر الوقف.")
    if len(reason) > MAX_LEN["note"]:
        _fail(f"السبب أطول من الحد المسموح ({MAX_LEN['note']} حرف).")

    held = suspended_types(data)
    already = [t for t in types if t in held]
    if already:
        _fail(f"الأنواع دي موقوفة بالفعل بأمر ساري: {'، '.join(already)}", 409)

    stop_ids = payload.get("stop_leave_ids") or []
    if not isinstance(stop_ids, list):
        _fail("قايمة الراحات المطلوب إيقافها غير صحيحة.")
    allowed = {c["leave_id"] for c in candidates(data, types, today)}
    bad = [i for i in stop_ids if i not in allowed]
    if bad:
        _fail(f"الراحة دي مش من المرشّحين للإيقاف: {bad[0]}")

    rows = data.setdefault(KEY, [])
    order = {
        "id": reserve_id(data, "RS", rows), "types": types, "started_on": today,
        "reason": reason, "created_at": datetime.now().isoformat(timespec="seconds"),
        "lifted_on": "", "lift_reason": "", "stopped_count": 0, "cancelled_count": 0,
        "cancelled_leaves": [],
    }
    rows.append(order)

    report = {"stopped": [], "cancelled": []}
    for leave_id in dict.fromkeys(stop_ids):
        result = stop_leave(data, leave_id, reason, on=today,
                            suspension_id=order["id"], today=today)
        if result["cancelled"]:
            report["cancelled"].append(leave_id)
            order["cancelled_leaves"].append(result["snapshot"])
        else:
            report["stopped"].append(result["leave"])
    order["stopped_count"] = len(report["stopped"])
    order["cancelled_count"] = len(report["cancelled"])

    changes.record(data, "rest_suspension", order["id"], "suspend", after=dict(order),
                   reason=reason,
                   text=f"وقف الراحات: {'، '.join(types)} — اتوقفت {order['stopped_count']} "
                        f"راحة واتلغت {order['cancelled_count']} — السبب: {reason}")
    return order, report


def can_restore(order, today):
    """الرجوع للراحات زي ما كانت متاح بس لو الفتح في نفس يوم الوقف — بعد
    كده الضباط اتسكّنوا خلاص على أساس إن راحتهم اتوقفت."""
    return not order.get("lifted_on") and order.get("started_on") == today


def _restore(data, order, reason):
    """بيرجّع كل راحة الأمر ده أوقفها لنهايتها الأصلية، وبيرجّع اللي لغاها
    (قادمة) من اللقطة. أي تداخل مع راحة اتسجّلت في الوقت ده بيلغي الفتح
    كله (`with_data` مابيحفظش) — مفيش رجوع نص."""
    from .leaves import overlapping
    from .models import Leave
    from .repo import Repos

    repos = Repos(data)
    restored = []

    def clash_guard(leave, name, ignore_id=None):
        clash = overlapping(data, leave, ignore_id=ignore_id)
        if clash:
            _fail(f"مش ممكن ترجع راحة {name}: فيه راحة تانية متسجّلة في نفس المدة "
                  f"({clash['start']} ← {clash['end']}). عدّلها الأول أو افتح من غير رجوع.", 409)

    for lv in [l for l in repos.leaves.all() if l.suspension_id == order.get("id")]:
        name = repos.leaves.name_of(lv.person_id)
        before = lv.as_dict()
        end = lv.original_end or lv.end
        clash_guard({"person_id": lv.person_id, "start": lv.start, "end": end}, name, ignore_id=lv.id)
        lv.end = end
        lv.return_date = (parse_date(end) + timedelta(days=1)).isoformat()
        for f in STOP_FIELDS:
            setattr(lv, f, "")
        lv._absent = frozenset(lv._absent | set(STOP_FIELDS))   # مايتخزّنوش فاضيين
        repos.leaves.save(lv)
        changes.record(data, "leave", lv.id, "restore", before=before, after=lv.as_dict(),
                       reason=reason, text=f"رجوع راحة {name} ({lv.type}) لنهايتها الأصلية "
                                           f"{end} — فتح الراحات في نفس يوم الوقف")
        restored.append(lv.id)

    for snap in order.get("cancelled_leaves") or []:
        if not snap.get("person_id") or repos.leaves.find(snap["leave_id"]):
            continue
        if not _is_officer(data, snap["person_id"]):
            continue
        leave = {k: snap.get(k, "") for k in
                 ("person_id", "type", "start", "end", "return_date", "note", "source")}
        leave["id"] = snap["leave_id"]
        clash_guard(leave, snap.get("name", ""))
        repos.leaves.add(Leave.from_dict(leave))
        changes.record(data, "leave", leave["id"], "restore", after=dict(leave), reason=reason,
                       text=f"رجوع راحة {snap.get('name', '')} ({leave['type']} {leave['start']} "
                            f"← {leave['end']}) اللي اتلغت — فتح الراحات في نفس يوم الوقف")
        restored.append(leave["id"])
    return restored


def lift(data, order_id, payload, today):
    order = next((o for o in all_orders(data) if o.get("id") == order_id), None)
    if not order:
        _fail("أمر الوقف غير موجود.", 404)
    if order.get("lifted_on"):
        _fail("الأمر ده اتفتح بالفعل.", 409)
    restore = bool(payload.get("restore"))
    if restore and not can_restore(order, today):
        _fail("الرجوع للراحات زي ما كانت متاح بس لو الفتح في نفس يوم الوقف.")
    lift_reason = str(payload.get("reason", "") or "").strip()[:MAX_LEN["note"]]
    before = dict(order)
    order["lifted_on"] = today
    order["lift_reason"] = lift_reason
    restored = _restore(data, order, lift_reason) if restore else []
    order["restored_count"] = len(restored)
    changes.record(data, "rest_suspension", order_id, "lift", before=before,
                   after=dict(order), reason=lift_reason,
                   text=f"فتح الراحات: {'، '.join(order.get('types', []))}"
                        + (f" — ورجعت {len(restored)} راحة زي ما كانت" if restore else "")
                        + (f" — {lift_reason}" if lift_reason else ""))
    return order

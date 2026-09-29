"""إدارة القوة — البحث عن شخص، ترتيبها، وقواعد الراحة الأساسية."""
from .constants import REST_SYSTEMS, SECTION_FORCE, WEEKDAYS


def effective(person, day):
    """الرتبة والمنصب والقسم وجهة التشغيل زي ما كانوا **في اليوم ده**.

    الرتبة والمنصب بيتغيّروا مع الترقيات وحركة الضباط، وتخزين قيمة واحدة
    حالية معناه إن إعادة توليد يوم قديم بتطبع بيانات غلط — يومية 5/7
    بتقول «مقدم / أشرف الشريف» والملف الحالي فيه «عقيد».

    دلوقتي بترجّع من `history` (آخر سجل تاريخ سريانه <= اليوم)، وبترجع
    للقيم الحالية لو مفيش تاريخ مسجّل.
    """
    person = person or {}
    current = {
        "role": person.get("role", ""),
        "post": person.get("post", ""),
        "section": person.get("section", "") or SECTION_FORCE,
        "search_attached": bool(person.get("search_attached")),
    }
    history = person.get("history") or []
    if not history:
        return current
    applicable = [h for h in history if (h.get("from") or "") <= day]
    if not applicable:
        applicable = [min(history, key=lambda h: h.get("from") or "")]
    latest = max(applicable, key=lambda h: h.get("from") or "")
    return {key: latest.get(key, current[key]) for key in current}


HISTORY_FIELDS = ("role", "post", "section", "search_attached")


def record_change(person, effective_from, changes):
    """يسجّل تغيير في الرتبة/المنصب/القسم/جهة التشغيل بتاريخ سريان.

    الترقية أو حركة الضباط بتغيّر الرتبة والمنصب، وتخزين قيمة واحدة كان
    معناه إن الأيام القديمة تتطبع ببيانات النهاردة — يومية 5/7 فيها
    «مقدم / أشرف الشريف» والملف كان فيه «عقيد».

    القيم الحالية على الضابط بتفضل مرآة لآخر سجل، عشان أي كود بيقرا
    person["role"] مباشرةً يفضل شغّال.
    """
    history = person.setdefault("history", [])
    if not history:
        # أول سجل بيبدأ من تاريخ انضمامه، مش من تاريخ التعديل — القيم
        # القديمة كانت سارية من الأول
        history.append({"from": person.get("join_date", effective_from),
                        **{f: person.get(f, False if f == "search_attached" else "")
                           for f in HISTORY_FIELDS}})

    latest = max(history, key=lambda h: h.get("from") or "")
    merged = {**{f: latest.get(f) for f in HISTORY_FIELDS}, **changes}
    if all(merged[f] == latest.get(f) for f in HISTORY_FIELDS):
        return                                  # مفيش تغيير فعلي

    same_day = next((h for h in history if h.get("from") == effective_from), None)
    if same_day:
        same_day.update(merged)                 # تصحيح لنفس تاريخ السريان
    else:
        history.append({"from": effective_from, **merged})
    history.sort(key=lambda h: h.get("from") or "")

    newest = history[-1]
    for field in HISTORY_FIELDS:
        person[field] = newest[field]


def find_person(data, person_id):
    """-> (person, category, bucket) or (None, None, None)

    واجهة قديمة متسيبة للتوافق — التنفيذ الحقيقي في `PeopleRepo.locate`،
    اللي بيستخدم فهرس بدل المسح الخطي على أربع قوايم. الدالة دي كانت
    بتتنده جوّه حلقات (مرة لكل شخص في كل صف لوحة).
    """
    from .repo import PeopleRepo
    return PeopleRepo(data).locate(person_id)



def new_person_id(data, category):
    """معرّف جديد للشخص — فريد على مستوى الفئة كلها (القوة + الأرشيف).

    المعرّف كان `تاريخ-اليوم + رقم الأقدمية`، وفحص التكرار كان على القوة
    بس. يعني: ضابط بيتشال للأرشيف، وبديله بيتسجّل بنفس رقم الأقدمية في
    نفس اليوم ⇒ **السجلين بنفس الـid بالظبط**، وأي عملية بتدوّر بالـid
    (حذف سجل أرشيف مثلًا) بتمسك الاتنين. reserve_id بتضمن رقم ما اتكررش
    ولا هيتكرر، وبنفس شكل أرقام الاستيراد (OFF-050 / IND-201).
    """
    from .repo import PeopleRepo
    return PeopleRepo(data).new_id(category)


def valid_rest(payload, errors, current=None):
    """Validate and normalise the rest fields in place.

    `current` هو سجل الشخص وقت التعديل — لازم عشان طلب بيغيّر
    `rest_system` لوحده من غير `rest_day` يتقاس على اليوم المسجّل فعلًا.
    """
    system = str(payload.get("rest_system", "")).strip()
    if system and system not in REST_SYSTEMS:
        errors.append("نظام الراحة غير صحيح.")
    day = str(payload.get("rest_day", "")).strip()
    if day and day not in WEEKDAYS:
        errors.append("يوم الراحة غير صحيح.")
    if system and system != "أسبوعية":
        payload["rest_day"] = ""       # only weekly rest is tied to a weekday
    elif system == "أسبوعية":
        # راحة أسبوعية من غير يوم محدد بتعطّل حساب الراحة الجاية بالكامل:
        # next_rest_start مابتلاقيش يوم تبني عليه، فالضابط عمره ما بيطلع
        # في تنبيه التقصيرة ولا بيتحسب في الالتزام — وكل ده في صمت.
        effective_day = day or str((current or {}).get("rest_day", "")).strip()
        if not effective_day:
            errors.append("يجب تحديد يوم في الأسبوع للراحة الأسبوعية.")


def officers_on(data, day):
    """الضباط اللي كانوا على القوة في اليوم ده — مش الحاليين.

    الضابط محسوب لو انضم في اليوم ده أو قبله، ولسه ما خرجش (أو خرج بعده).
    """
    from .repo import PeopleRepo
    return PeopleRepo(data).raw_on_force(day, "officers")


# ---------- تعارض مدى الخدمة (خروج، أو تعديل تاريخ انضمام/خروج) ----------
#
# لما شخص يخرج من القوة، أو تاريخ انضمامه/خروجه يتعدّل، ممكن يفضل عنده
# راحات أو التحاقات فرق أو تكليفات مسجّلة **برّه** مدى خدمته الجديد —
# مسجّلة مقدّمًا (تكليفات أيام جاية) أو من فترة خدمة سابقة اتقصّرت بالتعديل.
# من غير الفحص ده، البيانات دي بتفضل معلّقة: ظاهرة في اليومية والراحات
# لشخص السيستم بيقول إنه مش على القوة وقتها.

def service_window_conflicts(data, person_id, category, join_date, leave_date="",
                             check_missions=False):
    """كل السجلات المسجّلة برّه مدى الخدمة [join_date, leave_date] —
    راحات، فرق (للضباط بس)، تكليفات، وحالات يوم. بترجّع dict فاضي لو
    مفيش تعارض. `leave_date=""` معناها لسه على القوة (بلا نهاية).
    """
    from .repo import Repos

    repos = Repos(data)
    out = {}

    def outside(day):
        day = day or ""
        return bool(day) and (day < join_date or (leave_date and day > leave_date))

    leaves = [lv for lv in repos.leaves.of_person(person_id)
              if outside(lv.start) or outside(lv.end)]
    if leaves:
        out["leaves"] = [{"id": lv.id, "start": lv.start, "end": lv.end, "type": lv.type}
                          for lv in leaves]

    if category == "officers":
        terms = [t for t in repos.terms.of_officer(person_id)
                 if outside(t.start) or outside(t.end)]
        if terms:
            out["terms"] = [{"id": t.id, "start": t.start, "end": t.end} for t in terms]

    key = "officer_ids" if category == "officers" else "personnel_ids"
    assignment_days = [d for d in repos.days.assignment_days_of(person_id, (key,))
                       if outside(d)]
    if assignment_days:
        out["assignment_days"] = assignment_days

    if category == "officers":
        state_days = [d for d in repos.days.officer_state_days_of(person_id) if outside(d)]
        if state_days:
            out["state_days"] = state_days

        if check_missions:
            open_missions = [m for m in repos.missions.of_officer(person_id) if m.open]
            if open_missions:
                out["missions"] = [{"id": m.id, "name": m.name, "status": m.status}
                                   for m in open_missions]

    return out


def cleanup_outside_window(data, person_id, category, join_date, leave_date=""):
    """بينظّف كل اللي `service_window_conflicts` لقاه — بيتنادى بس لما
    المشغّل يأكد (`cleanup: true`). راحة/التحاق يبدأ برّه المدى بيتشال
    كامل، واللي يبدأ جوّه المدى وينتهي برّاه بيتقص لحد حده. بترجّع تقرير
    {الوصف: العدد} للسجل."""
    from .repo import Repos

    repos = Repos(data)
    report = {}

    def outside(day):
        day = day or ""
        return bool(day) and (day < join_date or (leave_date and day > leave_date))

    trimmed = deleted = 0
    for lv in repos.leaves.of_person(person_id):
        if not (outside(lv.start) or outside(lv.end)):
            continue
        if lv.start < join_date and (not leave_date or lv.end <= leave_date):
            lv.start = join_date          # بدأت قبل الانضمام الجديد — تُقصّ من أوله
        if leave_date and lv.end > leave_date and lv.start >= join_date:
            lv.end = leave_date            # امتدت بعد الخروج — تُقصّ من آخره
        if lv.start > lv.end or (leave_date and lv.start > leave_date) or lv.start < join_date:
            repos.leaves.remove(lv.id)
            deleted += 1
        else:
            from datetime import date, timedelta
            lv.return_date = (date.fromisoformat(lv.end) + timedelta(days=1)).isoformat()
            repos.leaves.save(lv)
            trimmed += 1
    if trimmed or deleted:
        report["leaves"] = {"trimmed": trimmed, "deleted": deleted}

    if category == "officers":
        deleted = 0
        for t in repos.terms.of_officer(person_id):
            if outside(t.start) or outside(t.end):
                repos.terms.remove(t.id)
                deleted += 1
        if deleted:
            report["terms"] = {"deleted": deleted}

    key = "officer_ids" if category == "officers" else "personnel_ids"
    days = [d for d in repos.days.assignment_days_of(person_id, (key,)) if outside(d)]
    if days:
        touched = repos.days.detach_person_on_days(person_id, key, days)
        report["assignments"] = {"days": days, "rows_detached": touched}

    if category == "officers":
        state_days = [d for d in repos.days.officer_state_days_of(person_id) if outside(d)]
        if state_days:
            touched = repos.days.drop_officer_states_on_days(person_id, state_days)
            report["states"] = {"days": state_days, "rows_dropped": touched}

        detached = 0
        for m in repos.missions.of_officer(person_id):
            if m.open:
                m.member_ids = [i for i in m.member_ids if i != person_id]
                repos.missions.save(m)
                detached += 1
        if detached:
            report["missions"] = {"detached": detached}

    return report

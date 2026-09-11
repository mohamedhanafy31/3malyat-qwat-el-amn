"""إدارة القوة — البحث عن شخص، ترتيبها، وقواعد الراحة الأساسية."""
from .constants import REST_SYSTEMS, SECTION_FORCE, WEEKDAYS
from .utils import command_priority_map, rank_key, sort_active


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
    """-> (person, category, bucket) or (None, None, None)"""
    for cat in ("officers", "personnel"):
        for bucket in ("active", "archive"):
            for p in data[cat][bucket]:
                if p.get("id") == person_id:
                    return p, cat, bucket
    return None, None, None



def new_person_id(data, category):
    """معرّف جديد للشخص — فريد على مستوى الفئة كلها (القوة + الأرشيف).

    المعرّف كان `تاريخ-اليوم + رقم الأقدمية`، وفحص التكرار كان على القوة
    بس. يعني: ضابط بيتشال للأرشيف، وبديله بيتسجّل بنفس رقم الأقدمية في
    نفس اليوم ⇒ **السجلين بنفس الـid بالظبط**، وأي عملية بتدوّر بالـid
    (حذف سجل أرشيف مثلًا) بتمسك الاتنين. reserve_id بتضمن رقم ما اتكررش
    ولا هيتكرر، وبنفس شكل أرقام الاستيراد (OFF-050 / IND-201).
    """
    from .store import reserve_id
    prefix = "OFF" if category == "officers" else "IND"
    pool = data[category]["active"] + data[category]["archive"]
    return reserve_id(data, prefix, pool)


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
            errors.append("الراحة الأسبوعية لازم يتحدد ليها يوم في الأسبوع.")


def officers_on(data, day):
    """الضباط اللي كانوا على القوة في اليوم ده — مش الحاليين.

    الضابط محسوب لو انضم في اليوم ده أو قبله، ولسه ما خرجش (أو خرج بعده).
    """
    out = []
    for bucket in ("active", "archive"):
        for o in data["officers"][bucket]:
            join = o.get("join_date", "")
            if join and join > day:
                continue
            left = o.get("leave_date", "")
            if left and day > left:
                continue
            out.append(o)
    priority = command_priority_map(data)
    out.sort(key=lambda o: rank_key(o, priority))
    return out

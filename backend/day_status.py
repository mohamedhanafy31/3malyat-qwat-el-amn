"""إغلاق اليوم — اليوم بيقفل **لوحده** الساعة ١٢ بالليل، والتعديل بعد كده
لازم يكون استثنائي وموثّق مش تعديل عادي زي أي يوم تاني.

القفل التلقائي مش مجدول ولا محتاج خدمة شغّالة في الخلفية: اليوم بيتحسب
مقفول لو تاريخه أقدم من تاريخ النهاردة، خلاص. ده مقصود لأن النظام بيشتغل
على جهاز معزول ممكن يتقفل بالليل ويتفتح الصبح — أي مجدول كان هيفوّت
منتصف الليل والجهاز مطفي، بينما المقارنة دي بتديك نفس النتيجة بالظبط في
كل الحالات ومن غير أي حالة متخزّنة.

يعني بالظبط:

    يوم فات       -> مقفول تلقائيًا (من الساعة ١٢ اللي بعده)
    النهاردة      -> مفتوح، إلا لو المشغّل قفله بدري بإيده
    يوم جاي       -> مفتوح (التجهيز المسبق مسموح)

الفتح الاستثنائي (`reopen_day`) صالح **لليوم اللي اتعمل فيه بس** — بيرجع
يتقفل تلقائي في منتصف الليل زي أي يوم تاني. من غير القيد ده كان الفتح
الاستثنائي هيبقى فتح دائم، وساعتها القفل التلقائي مالوش أي معنى بعد أول
مرة حد يفتح فيها يوم قديم.
"""
from datetime import date, datetime, timedelta


def today_iso():
    """تاريخ النهاردة — نقطة واحدة عشان الاختبارات تقدر تثبّتها."""
    return date.today().isoformat()


def _auto_closed_at(day):
    """لحظة القفل التلقائي: الساعة ١٢ بالليل اللي بعد اليوم ده."""
    try:
        return (date.fromisoformat(day) + timedelta(days=1)).isoformat() + "T00:00:00"
    except ValueError:
        return ""


def status_of(data, day):
    entry = dict((data.get("day_status") or {}).get(day) or {})
    today = today_iso()

    # فتح استثنائي — صالح لليوم اللي اتعمل فيه بس
    if entry.get("reopened_on") == today:
        return {**entry, "closed": False, "auto": False, "reopened": True}

    # قفل بدري بإيد المشغّل (قبل منتصف الليل)
    if entry.get("closed"):
        return {**entry, "closed": True, "auto": False, "reopened": False}

    if day < today:
        return {"closed": True, "auto": True, "reopened": False,
                "closed_at": _auto_closed_at(day), "closed_by": ""}

    return {"closed": False, "auto": False, "reopened": False}


def is_closed(data, day):
    return bool(status_of(data, day).get("closed"))


def check_open(data, day):
    """-> (ok, error_message). ok=False يعني الكتابة ممنوعة لحد ما اليوم يتفتح."""
    status = status_of(data, day)
    if not status.get("closed"):
        return True, None
    if status.get("auto"):
        return False, (f"اليوم {day} اتقفل تلقائيًا الساعة ١٢ بالليل. "
                       f"افتحه فتح استثنائي الأول لو محتاج تعدّل.")
    return False, f"اليوم {day} مقفول. افتحه فتح استثنائي الأول لو محتاج تعدّل."


def close_day(data, day, closed_by=""):
    """قفل بدري بإيد المشغّل — لليوم الحالي أو الجاي قبل ما القفل التلقائي يوصله."""
    statuses = data.setdefault("day_status", {})
    entry = {"closed": True, "closed_at": datetime.now().isoformat(timespec="seconds"),
             "closed_by": closed_by}
    statuses[day] = entry
    return entry


def reopen_day(data, day, reason="", reopened_by=""):
    """فتح استثنائي — صالح النهاردة بس وبعدين اليوم بيرجع يتقفل تلقائي."""
    statuses = data.setdefault("day_status", {})
    entry = {"closed": False, "reopened_on": today_iso(),
             "reopened_at": datetime.now().isoformat(timespec="seconds"),
             "reopened_by": reopened_by, "reason": reason}
    statuses[day] = entry
    return entry

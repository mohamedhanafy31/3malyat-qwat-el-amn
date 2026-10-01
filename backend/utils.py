"""أدوات عامة صغيرة مستخدمة في أكتر من مكان."""
from bisect import bisect_left, bisect_right
from datetime import date, timedelta

from flask import request

from .constants import COMMAND_ROLES, RANK_ORDER, WEEKDAYS


def json_payload():
    """جسم الطلب كـ dict دايمًا — لو العميل بعت array أو نص أو JSON غير صحيح
    برضو بترجع {} بدل ما ترمي 500 من أول payload.get(...) بعدها."""
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


def parse_date(value):
    try:
        return date.fromisoformat(str(value).strip())
    except (ValueError, TypeError):
        return None


# WEEKDAYS بيبدأ بالسبت؛ date.weekday() بيبدأ بالاثنين (0=اثنين .. 6=أحد) —
# جدول التحويل ده مكانه هنا عشان أي كود محتاج «اسم يوم الأسبوع من تاريخ»
# (راحة الضباط الأسبوعية، جدول التفتيشات) يستخدم نفس التحويل بالظبط.
_TO_PY_WEEKDAY = [5, 6, 0, 1, 2, 3, 4]      # السبت=5, الأحد=6, الاثنين=0 ...
_PY_WEEKDAY_TO_INDEX = {py: i for i, py in enumerate(_TO_PY_WEEKDAY)}


def weekday_name(value):
    """اسم يوم الأسبوع بالعربي (من `WEEKDAYS`) لتاريخ ISO — أو None لو غلط."""
    parsed = parse_date(value)
    return WEEKDAYS[_PY_WEEKDAY_TO_INDEX[parsed.weekday()]] if parsed else None


def canonical_day(value):
    """التاريخ في صورته المعيارية YYYY-MM-DD، أو None لو مش تاريخ صالح.

    `date.fromisoformat` في بايثون 3.11+ بيقبل صور تانية كمان («20260605»
    و«2026-W23-1»)، والمسار القديم كان بيتحقق بيها وبعدين **يستخدم النص
    الخام زي ما جه** كمفتاح تخزين لليوم أو كقيمة join_date. النتيجة إن نفس
    اليوم بيتخزّن في مفتاحين مختلفين، والمقارنات النصية («20260101» >
    «2026-06-01») بتطلع بالعكس. أي تاريخ داخل السيستم لازم يعدّي من هنا.
    """
    parsed = parse_date(value)
    return parsed.isoformat() if parsed else None


# حدود طول الحقول الحرة — مش قواعد تشغيلية، دي حماية من الإدخال الغلط
# (لصق صفحة كاملة في خانة الاسم) ومن تضخيم ملف البيانات.
MAX_LEN = {"name": 120, "code": 40, "phone": 30, "post": 200,
           "address": 200, "note": 500, "reason": 200, "section": 60,
           "weapon_custody": 60, "weapon": 120, "time": 60, "party": 120}


def too_long(payload, field):
    """-> رسالة خطأ لو الحقل موجود في الطلب وأطول من حده، وإلا None."""
    limit = MAX_LEN.get(field)
    if limit is None or field not in payload:
        return None
    if len(str(payload[field] or "").strip()) > limit:
        return f"الحقل «{field}» أطول من الحد المسموح ({limit} حرف)."
    return None


def check_lengths(payload, fields):
    """أول خطأ طول في الحقول دي — أو None."""
    for field in fields:
        error = too_long(payload, field)
        if error:
            return error
    return None


# أرقام وفواصل الترقيم اللي بتتكتب فعلًا في التليفونات (+20، 010-123، 010 123)
_PHONE_OK = set("0123456789 +-/()")


def valid_phone(value):
    """رقم تليفون معقول — أرقام وفواصل بس، وفيه رقم واحد على الأقل.

    مش تحقق من صحة الرقم نفسه (الأرقام في الملف بصور مختلفة)، بس بيمنع
    نص عشوائي أو صفحة ملزوقة من إنها تتخزّن كتليفون.
    """
    raw = str(value or "").strip()
    if not raw or len(raw) > MAX_LEN["phone"]:
        return False
    if not any(ch.isdigit() for ch in raw):
        return False
    return all(ch in _PHONE_OK for ch in raw)


def category_for(person_type):
    return "officers" if person_type == "officer" else "personnel"


def command_priority_map(data, day=None):
    """{officer_id: ترتيبه بين مناصب القيادة} — مدير الإدارة أولًا ثم وكيله.

    «طبي» و«بحث» (`command_groups`) مش هنا عن قصد — منصبين جماعيين
    مالهمش أثر على ترتيب أي قايمة ضباط، عكس مدير/وكيل الإدارة."""
    priority = {}
    if day:
        from .dated import command_on
        command = command_on(data or {}, day)
    else:
        command = (data or {}).get("command") or {}
    for i, role in enumerate(COMMAND_ROLES):
        officer_id = command.get(role)
        if officer_id:
            priority[officer_id] = i
    return priority


def rank_key(person, command_priority=None):
    """مدير/وكيل الإدارة دايمًا أعلى اتنين في أي قايمة ضباط، بغض النظر عن
    الرتبة العسكرية — هم الأعلى تنظيميًا في الإدارة. باقي الضباط بعدهم
    بالرتبة العسكرية العادية زي ما كان."""
    top = (command_priority or {}).get(person.get("id"), len(COMMAND_ROLES))
    r = (person.get("role") or "").strip()
    idx = RANK_ORDER.index(r) if r in RANK_ORDER else len(RANK_ORDER)
    return (top, idx, person.get("name", ""), person.get("code", ""))


def sort_active(data, category):
    """قوائم الضباط دايمًا بالرتبة (وقيادة الإدارة أولًا)؛ الأفراد بالاسم
    زي ما هو معمول من الأول."""
    from .repo import PeopleRepo
    PeopleRepo(data).sort(category)


# ---------- مدى تاريخ بيتحل من فلتر مستخدم (تجميع على عدة أيام) ----------
# مستخدمة في أي صفحة بتلفّ على مدى أيام بدل يوم واحد (إحصائيات التشغيل،
# سجل خدمات الضابط) — منطق واحد لتحديد المدى الافتراضي وقايمة الأيام
# المسجّلة فعلًا، بدل ما يتكرر في كل موديول.

def days_between(start, end):
    """كل يوم بين `start` و`end` (شاملهم) كنص معياري — start/end كائنات date."""
    out, cur = [], start
    while cur <= end:
        out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def resolve_recorded_range(data, filters, default_range_days=30):
    """(date_from, date_to, recorded) بصورتهم المعيارية — افتراضي آخر
    `default_range_days` يوم فيهم يومية فعلًا لو الفلتر فاضي.

    `recorded` = تكليف أو حالة ضابط مسجّلة — نفس تعريف `register.py::
    recorded_days()` بالظبط، وعن قصد **أضيق** من `DayRepo.dates()`
    (اللي بتضيف قفل/تأكيد/عدّ خدمات كمان): يوم اتقفل أو اتأكد من غير
    ما حد يكتب فيه تكليف أو حالة ضابط لسه مش «يوم شغل فعلي» — بالظبط
    الالتباس اللي `register.py` بيتفاداه بالتفرقة دي. تقصيرة أو حالة
    مسجّلة بس من غير تكليف لسه لازم تتحسب، فـ`day_officers` باقي في
    التعريف — بس مش القفل/التأكيد/العدّ.
    """
    recorded = sorted(set(data.get("day_assignments") or {}) | set(data.get("day_officers") or {}))
    date_from = canonical_day(filters.get("date_from", ""))
    date_to = canonical_day(filters.get("date_to", ""))
    if not date_to:
        date_to = recorded[-1] if recorded else date.today().isoformat()
    if not date_from:
        end = date.fromisoformat(date_to)
        try:
            date_from = (end - timedelta(days=default_range_days - 1)).isoformat()
        except OverflowError:                 # date_to في أول أيام سنة 1
            date_from = date.min.isoformat()
    if date_from > date_to:
        date_from, date_to = date_to, date_from
    return date_from, date_to, recorded


def range_filters(args):
    """-> (filters, error) من باراميترات date_from/date_to في الطلب.

    التاريخ الفاضي مسموح (المدى الافتراضي)؛ التاريخ الموجود ومش صالح
    بيرجّع رسالة خطأ بدل ما يتجاهل بصمت ويعرض مدى غير اللي اتطلب."""
    filters = {}
    for key, label in (("date_from", "البداية"), ("date_to", "النهاية")):
        raw = str(args.get(key, "") or "").strip()
        if raw and not canonical_day(raw):
            return None, f"تاريخ {label} غير صحيح."
        filters[key] = canonical_day(raw) if raw else ""
    return filters, None


def recorded_between(recorded, date_from, date_to):
    """الأيام المسجّلة بين الحدين (شاملهم) من قايمة `recorded` المرتبة.

    بحث ثنائي على النص المعياري YYYY-MM-DD (ترتيبه النصي = ترتيبه الزمني)
    بدل ما نلف على كل يوم في التقويم — مدى زي 0001-01-01..9999-12-31 كان
    بيبني ٣.٦ مليون تاريخ عشان يلاقي كام يوم مسجّل بس."""
    if date_from > date_to:
        date_from, date_to = date_to, date_from
    return recorded[bisect_left(recorded, date_from):bisect_right(recorded, date_to)]

"""جدول تفتيشات زيارات الأهالي الأسبوعي — تفتيش تأمين المجندين لزيارات
أهالي المساجين، بيتكرر بنفس الأسماء كل أسبوع على أيام ثابتة (زي «تفتيش
فيصل» كل سبت وأحد واثنين). كل تفتيش اسمه «تفتيش» + اسم السجن، وليه
تسليح وعدد مجندين ثابتين.

الجدول بيتحرّر من صفحة «دليل الخدمات»، وبيتحط تلقائيًا على اليومية
التفصيلية (`build_board`) أول ما يوم الأسبوع بتاعه يتفتح لأول مرة —
`seed_board_day()` بتتنادى من `GET /api/board/<day>` نفسها. بعد كده
الصفوف دي خانات عادية زي أي خانة تانية على اللوحة: تتعدّل وتتشال وتتكلّف
عليها أفراد بحرية، من غير أي علاقة بالجدول الأسبوعي تاني.

زي أي قسم مخصّص تاني، القسم («تفتيشات» — `SECTION_INSPECTIONS`) مش من
الستة الرسمية ومش محتاج أي تسجيل في `ASSIGNMENT_SECTIONS`؛ اللوحة بتتعامل
مع أي قسم مش مسجّل تلقائيًا.
"""
from .constants import (
    INSPECTION_DEFAULT_COUNT, INSPECTION_DEFAULT_WEAPON, SECTION_INSPECTIONS,
    WEEKDAYS,
)
from .utils import MAX_LEN, check_lengths, weekday_name


def schedule(data):
    """{يوم الأسبوع: [تفتيش, ...]} — كل أيام الأسبوع مضمونة الوجود كمفاتيح."""
    sched = data.setdefault("inspection_schedule", {})
    for day in WEEKDAYS:
        sched.setdefault(day, [])
    return sched


def day_entries(data, weekday):
    return schedule(data).get(weekday, [])


def _all_entries(data):
    return [e for entries in schedule(data).values() for e in entries]


def _find(data, weekday, entry_id):
    return next((e for e in day_entries(data, weekday) if e["id"] == entry_id), None)


def _clean(payload, current=None):
    """-> (dict نظيف, رسالة خطأ أو None). `current` بيوفّر القيم الغائبة
    من الطلب لما بيبقى تعديل جزئي."""
    current = current or {}
    name = str(payload.get("name", current.get("name", "")) or "").strip()
    if not name:
        return None, "اسم التفتيش مطلوب."

    # حقل فاضي (يتبعت أو يتمسح من غير قصد) معناه «استخدم الافتراضي» —
    # مش خطأ. الرقم غلط بس هو اللي يرفض الطلب.
    raw_weapon = payload.get("weapon")
    if raw_weapon in (None, ""):
        raw_weapon = current.get("weapon") or INSPECTION_DEFAULT_WEAPON
    weapon = str(raw_weapon).strip()

    raw_count = payload.get("count")
    if raw_count in (None, ""):
        raw_count = current.get("count", INSPECTION_DEFAULT_COUNT)
    try:
        count = max(0, int(raw_count))
    except (TypeError, ValueError):
        return None, "يجب أن يكون عدد المجندين رقمًا."

    clean = {"name": name, "weapon": weapon, "count": count}
    error = check_lengths(clean, ["name"])
    if error:
        return None, error
    return clean, None


def add_entry(data, weekday, payload):
    if weekday not in WEEKDAYS:
        return None, "يوم غير معروف."
    clean, error = _clean(payload)
    if error:
        return None, error
    from .store import reserve_id

    entry = {"id": reserve_id(data, "INS", _all_entries(data)), **clean}
    schedule(data)[weekday].append(entry)
    return entry, None


def edit_entry(data, weekday, entry_id, payload):
    if weekday not in WEEKDAYS:
        return None, "يوم غير معروف."
    entry = _find(data, weekday, entry_id)
    if not entry:
        return None, "هذا التفتيش غير موجود."
    clean, error = _clean(payload, current=entry)
    if error:
        return None, error
    entry.update(clean)
    return entry, None


def delete_entry(data, weekday, entry_id):
    entries = day_entries(data, weekday)
    before = len(entries)
    schedule(data)[weekday] = [e for e in entries if e["id"] != entry_id]
    return len(schedule(data)[weekday]) < before


def needs_seed(data, day):
    """فحص رخيص للقراءة بس — يقرر لو `seed_board_day` هيعمل حاجة فعلًا،
    عشان نقاط الـGET تتجنّب الدخول في مسار كتابة (وتسجيل في audit.log)
    لأغلب الأيام اللي اتفتحت قبل كده."""
    from . import day_status
    from .imports import is_imported

    ok, _ = day_status.check_open(data, day)
    if not ok or is_imported(data, day) or day in _seeded_days(data):
        return False
    return bool(day_entries(data, weekday_name(day) or ""))


def _seeded_days(data):
    """أيام اتحط عليها تفتيشات تلقائية قبل كده — علامة مستقلة عن
    `day_assignments`، عشان لو المشغّل مسح كل خانات اليوم ده (تفتيشات أو
    غيرها) الملف الفاضي بيتشال بالكامل (`DayRepo.remove_assignment`)،
    ولو اعتمدنا على وجود اليوم في `day_assignments` بس كنا هنعيد
    التفتيشات تاني لوحدها في أول فتح جاي — عكس «تتشال بحرية»."""
    return data.setdefault("inspection_seeded_days", {})


def seed_board_day(data, day):
    """أول ما يوم يتفتح لأول مرة، بيتحط عليه تفتيشات يوم الأسبوع بتاعه —
    لو اليوم اتفتح قبل كده (حتى لو اتمسحت كل خاناته بعدين)، ملوش دخل تاني.
    الفحص هنا بيتكرر تاني (مش بس `needs_seed`) عشان يفضل صحيح حتى لو
    اتنادى مباشرة من غير مرور على `needs_seed` الأول."""
    from . import day_status
    from .imports import is_imported

    ok, _ = day_status.check_open(data, day)
    if not ok or is_imported(data, day) or day in _seeded_days(data):
        return
    entries = day_entries(data, weekday_name(day) or "")
    if not entries:
        return

    from .assignments import blank, new_id

    _seeded_days(data)[day] = True
    rows = data.setdefault("day_assignments", {}).setdefault(day, [])
    for entry in entries:
        aid = new_id(data, day, rows)
        rows.append(blank(aid, entry["name"], SECTION_INSPECTIONS,
                          kind="خارجية", weapon=entry.get("weapon") or INSPECTION_DEFAULT_WEAPON,
                          conscript_count=int(entry.get("count") or 0)))

"""نسخ ضباط الأهداف مبدئيًا من آخر تأكيد لليوم السابق."""
from datetime import date, timedelta

from . import day_status
from .assignments import officer_states, peek_day
from .constants import ROLE_MEDICAL, SECTION_TARGETS, TARGET_NAMES, TARGETS_FIRST
from .dated import groups_on, targets_on
from .leaves import leave_on
from .repo import PeopleRepo



def _previous(day):
    return (date.fromisoformat(day) - timedelta(days=1)).isoformat()


def _next(day):
    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()


def _markers(data):
    # القراءة العادية بتستخدم `data.get` في الدوال اللي تحت؛ الإنشاء هنا
    # محصور في مسار البذر نفسه عشان GET السريع يفضل من غير كتابة.
    return data.setdefault("target_defaults", {})


def _marker(data, day):
    return (data.get("target_defaults") or {}).get(day)


def _target_rows(data, day):
    return [row for row in peek_day(data, day)
            if row.get("section") == SECTION_TARGETS]


def _target_map(rows, targets):
    """خريطة التعيين فقط؛ باقي حقول صف الهدف ثابتة ومش قرار يومي."""
    out = {name: [] for name in targets}
    unknown = {}
    for row in rows:
        name = row.get("name", "")
        bucket = out.get(name)
        if bucket is None:
            bucket = unknown.setdefault(name, [])
        for officer_id in row.get("officer_ids") or []:
            officer_id = str(officer_id).strip()
            if officer_id and officer_id not in bucket:
                bucket.append(officer_id)
    return {**out, **unknown}


def _confirmed_source(data, day):
    source_day = _previous(day)
    entry = (data.get("day_confirm") or {}).get(source_day)
    return source_day, entry


def needs_seed(data, day):
    """فحص قراءة رخيص قبل الدخول في `with_data`."""
    if _marker(data, day) or _target_rows(data, day):
        return False
    ok, _ = day_status.check_open(data, day)
    if not ok:
        return False
    _source_day, entry = _confirmed_source(data, day)
    return bool(entry)


def _eligible_map(data, day, confirmed_rows):
    on_force = PeopleRepo(data).ids_on_force(day, "officers")
    targets = targets_on(data, day)
    medical = set(groups_on(data, day).get(ROLE_MEDICAL) or [])
    states = officer_states(data, day)
    copied = _target_map(
        (row for row in confirmed_rows if row.get("section") == SECTION_TARGETS), targets)

    result = {}
    for name in targets:
        result[name] = [
            officer_id for officer_id in copied[name]
            if officer_id in on_force
            and officer_id not in medical
            and not leave_on(data, officer_id, day)
            and not str((states.get(officer_id) or {}).get("status") or "").strip()
        ]
    return result


def _apply(data, day, source_day, entry):
    # الاستيراد محلي عشان `board` تقدر تستخدم `untouched_seed` في بناء
    # الاستجابة من غير دورة استيراد بينها وبين الوحدة دي.
    from .board import set_target_officers

    targets = _eligible_map(data, day, entry.get("rows") or [])
    for name in targets_on(data, day):
        _row, error, _status = set_target_officers(data, day, name, targets[name])
        if error:
            # البذر مساعدة مش شرط لفتح اليوم. لقطة قديمة أو مكتوبة بإيد
            # ممكن تعدّي الفلتر ثم يرفضها تحقق الحفظ؛ الهدف ده وحده يفضل
            # شاغر وباقي الأهداف تكمل بدل ما فتح اللوحة أو التأكيد يقع.
            set_target_officers(data, day, name, [])
            targets[name] = []
    marker = {
        "source_day": source_day,
        "confirmed_at": entry.get("at"),
        "targets": targets,
    }
    _markers(data)[day] = marker
    return marker


def seed_day(data, day):
    """يبذر يومًا مفتوحًا مرة واحدة لو يومه السابق له لقطة مؤكدة."""
    if _marker(data, day) or _target_rows(data, day):
        return None
    ok, _ = day_status.check_open(data, day)
    if not ok:
        return None
    source_day, entry = _confirmed_source(data, day)
    if not entry:
        return None
    return _apply(data, day, source_day, entry)


def _day_exists(data, day):
    """هل لليوم ملف منطقي بالفعل من أي قسم يومي، لا مجرد تاريخ ممكن."""
    from .store import DAY_SECTIONS

    return any(day in (data.get(key) or {}) for key in DAY_SECTIONS)


def refresh_after_confirmation(data, source_day):
    """يحدّث اليوم التالي لو ما زال نسخة البذر التي لم يلمسها المشغّل."""
    day = _next(source_day)
    ok, _ = day_status.check_open(data, day)
    if not ok:
        return None

    marker = _marker(data, day)
    rows = _target_rows(data, day)
    if marker:
        if marker.get("source_day") != source_day or marker.get("modified"):
            return None
        if _target_map(rows, targets_on(data, day)) != marker.get("targets"):
            # تثبيت المعلومة يمنع أي تأكيد لاحق من لمس يوم عرفنا بالفعل
            # إن المشغّل عدّل أهدافه، حتى لو فضّاها كلها بعد كده.
            marker["modified"] = True
            return None
        from .weekly_rest import seed_day as seed_weekly_rest

        seed_weekly_rest(data, day)
        entry = (data.get("day_confirm") or {}).get(source_day)
        return _apply(data, day, source_day, entry)

    if rows or not _day_exists(data, day):
        return None
    # اليوم كان موجودًا فعلًا قبل النداء، فنسجّل راحته الأسبوعية أولًا.
    # ترتيب الشرط قبل التسجيل يمنع تأكيد اليوم السابق من إنشاء يوم تالٍ
    # لم يفتحه أو يجهّزه أحد.
    from .weekly_rest import seed_day as seed_weekly_rest

    seed_weekly_rest(data, day)
    entry = (data.get("day_confirm") or {}).get(source_day)
    return _apply(data, day, source_day, entry)


def untouched_seed(data, day):
    """العلامة المعروضة في رأس القسم، أو None بعد أي تعديل في الأهداف."""
    marker = _marker(data, day)
    if not marker or marker.get("modified"):
        return None
    if _target_map(_target_rows(data, day), targets_on(data, day)) != marker.get("targets"):
        return None
    return marker

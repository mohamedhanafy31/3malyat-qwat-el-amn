"""تسجيل الراحة الأسبوعية الثابتة أول مرة يومها يتفتح."""
from datetime import date, timedelta

from . import changes, day_status
from .courses import term_on
from .leaves import build_leave, leave_on
from .models import ACTIVE, Leave
from .repo import Repos
from .rest_suspension import is_suspended_on
from .utils import weekday_name
from .people import effective

KIND = "أسبوعية"
ORIGIN = "auto_weekly"


def _seeded(data):
    # القراءة هنا من غير setdefault عشان فحص الـGET يفضل قراءة فعلًا.
    return data.get("weekly_rest_seeded_days") or {}


def _candidates(data, day):
    """ضباط نشطون، على القوة في اليوم، ويومهم الأسبوعي مطابق."""
    people = Repos(data).people
    active_ids = {o.get("id") for o in people.bucket("officers", "active")}
    weekday = weekday_name(day)
    return [o for o in people.on_force(day, "officers")
            if o.status == ACTIVE and o.id in active_ids
            and o.effective(day).get("rest_system") == KIND
            and o.effective(day).get("rest_day") == weekday]


def needs_seed(data, day):
    """فحص قراءة رخيص قبل الدخول في `with_data`."""
    if day in _seeded(data):
        return False
    ok, _ = day_status.check_open(data, day)
    return bool(ok and _candidates(data, day))


def seed_day(data, day):
    """يسجّل المستحقين مرة واحدة، ويعلّم اليوم حتى لو كلهم اتخطّوا."""
    if day in _seeded(data):
        return []
    ok, _ = day_status.check_open(data, day)
    if not ok:
        return []
    candidates = _candidates(data, day)
    if not candidates:
        return []

    data.setdefault("weekly_rest_seeded_days", {})[day] = True

    repos = Repos(data)
    created = []
    for officer in _due(data, day, candidates):
        leave, error = build_leave({
            "person_id": officer.id, "type": KIND,
            "start": day, "end": day, "origin": ORIGIN,
        }, data, repos.leaves.new_id())
        if error:
            continue
        added = repos.leaves.add(Leave.from_dict(leave))
        changes.record(
            data, "leave", leave["id"], "create", after=dict(leave), day=day,
            text=f"تسجيل تلقائي لراحة {officer.name} الأسبوعية يوم {effective(officer.as_dict(), day)['rest_day']}",
        )
        created.append(repos.leaves.named(added))
    return created


def _due(data, day, candidates):
    """المستحقين فعلًا من المرشحين: بعد الوقف، ومن غير راحة/فرقة تغطي اليوم.

    ده نفس الفلتر اللي `seed_day` بيسجّل بيه، ومنه بيتحسب سجل الراحات
    للأيام الجاية — فاليوميات وسجل الراحات ما يختلفوش على نفس اليوم.
    """
    if is_suspended_on(data, KIND, day):
        return []
    return [o for o in candidates
            if not (leave_on(data, o.id, day) or term_on(data, o.id, day))]


def upcoming_fixed(data, day):
    """الراحات الأسبوعية الثابتة اللي هتتسجّل لما يوم `day` يتفتح (قراءة بس).

    اليومية بتعرضها قبل تسجيلها (معاينة على نسخة)، وسجل الراحات كان
    بيستنى التسجيل الفعلي فبيفضل ناقص لحد ما حد يفتح اليوم.
    """
    if day in _seeded(data):
        return []
    ok, _ = day_status.check_open(data, day)
    if not ok:
        return []
    out = []
    for officer in _due(data, day, _candidates(data, day)):
        leave, error = build_leave({
            "person_id": officer.id, "type": KIND,
            "start": day, "end": day, "origin": ORIGIN,
        }, data, "")
        if not error:
            out.append(leave)
    return out


# سجل الراحات بيعرض الأسبوعية الثابتة لأسبوع قدّام (النهاردة + 6 أيام)،
# فكل ضابط بيظهر له راحة واحدة بالظبط في الفترة دي.
LOG_HORIZON_DAYS = 7
VIRTUAL_ORIGIN = "fixed_weekly"


def log_window(today):
    """أيام نافذة سجل الراحات (نصوص ISO) — نفس اللي بتتحمّل بياناتها."""
    first = date.fromisoformat(today)
    return [(first + timedelta(days=i)).isoformat() for i in range(LOG_HORIZON_DAYS)]


def virtual_rows(data, today):
    """راحات أسبوعية ثابتة لسه ما اتسجّلتش (اليوم ما اتفتحش) — للعرض بس.

    نفس حساب اليوميات (`upcoming_fixed` ← `_due`)، فلو ظهرت في اليومية
    تظهر هنا والعكس. بتتشال لوحدها أول ما اليوم يتفتح وتتسجّل راحة فعلية
    (يبقى اليوم متعلّم seeded وما بيتكررش)، فمفيش تكرار مع السجل الحقيقي.
    كل صف `virtual` ومالوش id قابل للتعديل/الحذف.
    """
    repos = Repos(data)
    rows = []
    for day in log_window(today):
        for leave in upcoming_fixed(data, day):
            row = {**leave, "id": f"virtual:{leave['person_id']}:{day}",
                   "origin": VIRTUAL_ORIGIN, "virtual": True}
            row["name"] = repos.leaves.name_of(leave["person_id"])
            row["display_type"] = leave["type"]
            rows.append(row)
    return rows

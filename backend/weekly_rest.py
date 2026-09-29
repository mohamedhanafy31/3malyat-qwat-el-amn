"""تسجيل الراحة الأسبوعية الثابتة أول مرة يومها يتفتح."""
from . import changes, day_status
from .courses import term_on
from .leaves import build_leave, leave_on
from .models import ACTIVE, Leave
from .repo import Repos
from .rest_suspension import is_suspended_on
from .utils import weekday_name

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
            and o.rest_system == KIND and o.rest_day == weekday]


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
    if is_suspended_on(data, KIND, day):
        return []

    repos = Repos(data)
    created = []
    for officer in candidates:
        if leave_on(data, officer.id, day) or term_on(data, officer.id, day):
            continue
        leave, error = build_leave({
            "person_id": officer.id, "type": KIND,
            "start": day, "end": day, "origin": ORIGIN,
        }, data, repos.leaves.new_id())
        if error:
            continue
        added = repos.leaves.add(Leave.from_dict(leave))
        changes.record(
            data, "leave", leave["id"], "create", after=dict(leave), day=day,
            text=f"تسجيل تلقائي لراحة {officer.name} الأسبوعية يوم {officer.rest_day}",
        )
        created.append(repos.leaves.named(added))
    return created

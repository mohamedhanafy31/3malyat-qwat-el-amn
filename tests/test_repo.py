"""المستودعات — الاستعلامات، الكتابة، وعدم تغيير شكل الملف.

`test_real_day_round_trips_byte_for_byte` هو نظير `test_models` على مستوى
المستودع: بيقرا كل يوم في البيانات الحقيقية في `data/` كتجميعة `Day` ويكتبها تاني
من غير أي تعديل، ولازم الملف يطلع **مطابق تمامًا**. لو `DayRepo` بيضيف
حقل أو بيشيل مفتاح فاضي غلط، ده بيبان هنا مش في الإنتاج.
"""
import copy
import json

import pytest

from backend.models import Assignment, Leave, Mission, OfficerDayState
from backend.repo import Repos

def real_data():
    """البيانات الحقيقية مجمّعة من مجلد `data/` — أو None لو مش موجودة.

    الاختبارات دي أهم شبكة أمان في الريفاكتور: بتتأكد إن النماذج
    والمستودعات بتقرا **البيانات الحقيقية** وترجّعها زي ما هي بالحرف.
    من غير الدالة دي كانت بتتخطّى في صمت بعد ما البيانات بقت مجلد.
    """
    from backend import store
    return store.assemble() if store.core_file().exists() else None


HAS_REAL = real_data() is not None

@pytest.fixture
def repos(data_file):
    return Repos(json.loads(data_file.read_text(encoding="utf-8")))


# ---------- عدم تغيير الشكل ----------

@pytest.mark.skipif(not HAS_REAL, reason="مافيش بيانات حقيقية")
def test_real_day_round_trips_byte_for_byte():
    """كل يوم بيتقرا كتجميعة ويترجع زي ما هو بالحرف."""
    data = real_data()
    before = copy.deepcopy({k: data[k] for k in
                            ("day_assignments", "day_officers", "day_status")})
    days = Repos(data).days
    for day in days.dates():
        days.save(days.get(day))

    for key, original in before.items():
        assert data[key] == original, f"شكل «{key}» اتغيّر بعد قراءة وكتابة"


@pytest.mark.skipif(not HAS_REAL, reason="مافيش بيانات حقيقية")
def test_indexes_never_reach_the_stored_file():
    """فهارس المستودعات بتتخزّن على `data` بمفاتيح بتبدأ بـ`_`، و
    `store._write()` بيشيلها — عشان ما تكبّرش الملف."""
    data = real_data()
    r = Repos(data)
    r.people.find("OFF-002")
    r.leaves.of_person("OFF-002")
    r.courses.find("CRS-002")
    assert [k for k in data if k.startswith("_")], "المفروض الفهارس اتبنت"

    payload = {k: v for k, v in data.items() if not k.startswith("_")}
    assert not [k for k in payload if k.startswith("_")]


# ---------- القوة ----------

def test_locate_matches_the_old_find_person_signature(repos):
    raw, category, bucket = repos.people.locate("OFF-001")
    assert raw["name"] == "أحمد محمد"
    assert (category, bucket) == ("officers", "active")
    assert repos.people.locate("OFF-999") == (None, None, None)


def test_find_in_rejects_the_wrong_category(repos):
    """بيمنع تكليف فرد في خانة ضابط والعكس."""
    assert repos.people.find_in("OFF-001", "officers") is not None
    assert repos.people.find_in("OFF-001", "personnel") is None


def test_on_force_includes_archived_people_for_past_days(repos):
    """الضابط المتأرشف لازم يفضل ظاهر في الأيام اللي كان فيها بالقوة،
    عشان تعديل يوم قديم يشتغل."""
    officer = repos.people.find("OFF-001")
    officer.leave_date = "2026-06-30"
    officer.status = "archived"
    repos.people.save(officer)
    repos.people.move("OFF-001", "archive")

    assert "OFF-001" in repos.people.ids_on_force("2026-06-15")
    assert "OFF-001" not in repos.people.ids_on_force("2026-07-15")


def test_new_id_is_unique_across_active_and_archive(repos):
    """المعرّف كان بيتفحص على القوة بس، فضابط بيتأرشف وبديله بيتسجّل
    في نفس اليوم كانوا بياخدوا نفس الـid بالظبط."""
    officer = repos.people.find("OFF-001")
    officer.leave_date, officer.status = "2026-06-30", "archived"
    repos.people.save(officer)
    repos.people.move("OFF-001", "archive")

    fresh = repos.people.new_id("officers")
    assert repos.people.locate(fresh) == (None, None, None)
    assert fresh != repos.people.new_id("officers")   # العدّاد بيزيد بس


def test_save_writes_through_to_the_stored_record(repos):
    officer = repos.people.find("OFF-001")
    officer.post = "منصب جديد"
    assert repos.people.save(officer)
    assert repos.people.find("OFF-001").post == "منصب جديد"


# ---------- الراحات ----------

def test_leaves_index_by_person(repos):
    assert [lv.id for lv in repos.leaves.of_person("OFF-001")] == ["LV-001"]
    assert repos.leaves.of_person("OFF-002") == []


def test_leave_on_day_finds_a_covering_record(repos):
    assert repos.leaves.on_day("OFF-001", "2026-01-10").id == "LV-001"
    assert repos.leaves.on_day("OFF-001", "2026-01-11") is None


def test_overlapping_ignores_the_record_being_edited(repos):
    same = Leave.from_dict({"person_id": "OFF-001", "start": "2026-01-10",
                            "end": "2026-01-10"})
    assert [lv.id for lv in repos.leaves.overlapping(same)] == ["LV-001"]
    assert repos.leaves.overlapping(same, ignore_id="LV-001") == []


def test_adding_a_leave_assigns_an_id_and_invalidates_the_index(repos):
    added = repos.leaves.add(Leave.from_dict({
        "person_id": "OFF-002", "type": "أسبوعية",
        "start": "2026-02-01", "end": "2026-02-01"}))
    assert added.id.startswith("LV-")
    assert [lv.id for lv in repos.leaves.of_person("OFF-002")] == [added.id]


# ---------- اليوم ----------

def test_day_aggregate_collects_every_per_date_key(repos):
    day = "2026-05-05"
    repos.days.add_assignment(day, Assignment.blank("", "خدمة", "الخدمات الطارئة"))
    repos.days.set_state(day, "OFF-001", OfficerDayState.from_dict({"note": "راحة"}))

    loaded = repos.days.get(day)
    assert len(loaded.assignments) == 1
    assert loaded.state_of("OFF-001").note == "راحة"
    assert loaded.count_entries is None          # لسه على القالب


def test_empty_officer_state_is_removed_not_stored(repos):
    """السجل الفاضي بيتشال بدل ما يتخزّن مدخل فاضي يكبّر الملف."""
    day = "2026-05-06"
    repos.days.set_state(day, "OFF-001", OfficerDayState.from_dict({"note": "x"}))
    assert repos.data["day_officers"].get(day)
    repos.days.set_state(day, "OFF-001", OfficerDayState())
    assert day not in repos.data["day_officers"]


def test_assignment_ids_are_scoped_to_the_day(repos):
    """رقم التكليف نطاقه اليوم — العدّ بيبدأ من أول كل يوم."""
    first = repos.days.add_assignment("2026-05-07", Assignment.blank("", "أ"))
    other = repos.days.add_assignment("2026-05-08", Assignment.blank("", "ب"))
    assert first.id == other.id == "AS-0001"


def test_detach_person_clears_them_from_every_day(repos):
    for day in ("2026-05-09", "2026-05-10"):
        repos.days.add_assignment(day, Assignment.blank(
            "", "خدمة", officer_ids=["OFF-001", "OFF-002"]))

    assert repos.days.detach_person("OFF-001", "officer_ids") == 2
    for day in ("2026-05-09", "2026-05-10"):
        assert repos.days.assignments(day)[0].officer_ids == ["OFF-002"]


def test_removing_the_last_assignment_drops_the_day_key(repos):
    day = "2026-05-11"
    row = repos.days.add_assignment(day, Assignment.blank("", "خدمة"))
    assert repos.days.remove_assignment(day, row.id)
    assert day not in repos.data["day_assignments"]


# ---------- الإعدادات ----------

def test_command_roles_are_always_present(repos):
    assert set(repos.config.command()) == {"مدير الإدارة", "وكيل الإدارة"}


def test_clearing_command_empties_every_post_the_officer_holds(repos):
    repos.config.assign_command("مدير الإدارة", "OFF-001")
    assert repos.config.role_of("OFF-001") == "مدير الإدارة"
    repos.config.clear_command("OFF-001")
    assert repos.config.role_of("OFF-001") is None


def test_tags_are_added_without_duplicates(repos):
    repos.config.add_tags(["مباراة", "مباراة", "قرعة الحج"])
    assert repos.config.tags() == ["مباراة", "قرعة الحج"]


# ---------- المأموريات ----------

def test_missions_filter_by_officer_and_open_state(repos):
    repos.missions.add(Mission.from_dict({"name": "أولى", "member_ids": ["OFF-001"]}))
    closed = repos.missions.add(Mission.from_dict({"name": "تانية", "status": "أغلقت"}))

    assert [m.name for m in repos.missions.open()] == ["أولى"]
    assert [m.name for m in repos.missions.of_officer("OFF-001")] == ["أولى"]
    assert not closed.open


# ---------- توحيد الحالة (هجرة 008) ----------

def test_roster_is_stored_as_one_list_with_status(repos):
    """القوة قايمة واحدة؛ `status` هو اللي بيفرّق مش قايمة منفصلة."""
    assert isinstance(repos.data["officers"], list)
    assert {p["status"] for p in repos.data["officers"]} == {"active"}


def test_buckets_are_computed_views_not_storage(repos):
    repos.people.move("OFF-001", "archive")
    assert [p.id for p in repos.people.active("officers")] == ["OFF-002"]
    assert [p.id for p in repos.people.archived("officers")] == ["OFF-001"]
    assert len(repos.data["officers"]) == 2      # مفيش سجل اتنقل ولا اتكرر


def test_archiving_is_a_single_status_change(repos):
    repos.people.move("OFF-001", "archive")
    raw, _, bucket = repos.people.locate("OFF-001")
    assert raw["status"] == "archived" and bucket == "archive"


def test_old_two_list_shape_is_normalised_on_read(repos):
    """نسخة احتياطية قديمة لازم تتقرا صح — القايمة هي اللي بتكسب على
    `status` لو اتخالفوا، لأنها هي اللي كانت بتتعرض فعلًا."""
    from backend.repo.people import PeopleRepo

    legacy = {"officers": {
        "active": [{"id": "OFF-A", "name": "أ", "status": "archived"}],   # متخالف
        "archive": [{"id": "OFF-B", "name": "ب"}],                        # بلا حقل
    }}
    people = PeopleRepo(legacy)
    assert [p.id for p in people.active("officers")] == ["OFF-A"]
    assert [p.id for p in people.archived("officers")] == ["OFF-B"]


def test_unified_list_keeps_active_before_archived(repos):
    """الترتيب المخزّن: القوة الأول بالرتبة، بعدين الأرشيف — نفس الترتيب
    اللي القايمتين كانوا بيدّوه."""
    repos.people.move("OFF-001", "archive")
    statuses = [p["status"] for p in repos.data["officers"]]
    assert statuses == sorted(statuses, key=lambda s: s != "active")

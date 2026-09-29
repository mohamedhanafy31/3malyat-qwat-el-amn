"""النماذج — العقد، والتحقق، وأهم من الاتنين: عدم تغيير الشكل.

`test_real_data_round_trips` هو الاختبار اللي بيحمي المرحلة ١ كلها: كل
سجل في البيانات الحقيقية في `data/` بيتحوّل لنموذج ويرجع dict، ولازم يطلع **مطابق
بالحرف** للي دخل. لو النموذج ضاف حقل ناقص أو شال حقل مش عارفه، الاختبار
ده بيقع — وده بالظبط اللي بيمنع النماذج إنها تغيّر ملف البيانات في صمت.
"""
import json

import pytest

from backend.models import (
    Assignment, ChangeEntry, ConscriptSlot, Course, CourseTerm, CountEntry,
    Individual, Leave, Mission, Officer, OfficerDayState, OfficerHistory,
)

def real_data():
    """البيانات الحقيقية مجمّعة من مجلد `data/` — أو None لو مش موجودة.

    الاختبارات دي أهم شبكة أمان في الريفاكتور: بتتأكد إن النماذج
    والمستودعات بتقرا **البيانات الحقيقية** وترجّعها زي ما هي بالحرف.
    من غير الدالة دي كانت بتتخطّى في صمت بعد ما البيانات بقت مجلد.
    """
    from backend import store
    return store.assemble() if store.core_file().exists() else None


HAS_REAL = real_data() is not None

# ---------- عدم تغيير الشكل ----------

def _round_trip(model, raw):
    return model.from_dict(raw).as_dict()


@pytest.mark.parametrize("raw", [
    {},                                              # سجل فاضي تمامًا
    {"id": "OFF-001"},                               # حقل واحد بس
    {"id": "OFF-001", "name": "فلان", "phone": None},  # قيمة None صريحة
    {"id": "OFF-001", "حقل_مش_معروف": 5},             # حقل مش في النموذج
])
def test_partial_records_keep_their_exact_keys(raw):
    assert _round_trip(Officer, raw) == raw


def test_absent_field_stays_absent():
    """الحقل اللي ماكانش موجود مايتضافش — `confirm._fingerprint` بيفرّق
    بين `None` (ناقص) و`""` (موجود وفاضي)، فإضافته كانت هتخلي كل يوم
    متأكّد يبان كأنه اتعدّل."""
    out = _round_trip(Assignment, {"id": "AS-0001", "name": "خدمة"})
    assert "note" not in out and "weapon" not in out


def test_absent_field_appears_once_it_is_set():
    row = Assignment.from_dict({"id": "AS-0001", "name": "خدمة"})
    row.note = "ملاحظة"
    out = row.as_dict()
    assert out["note"] == "ملاحظة"
    assert "weapon" not in out          # اللي لسه ماتلمسش فضل ناقص


def test_new_record_gets_every_field():
    """السجل المبني بالـconstructor (مش مقروء من ملف) بياخد كل حقوله —
    ده المكان الصح للقيم الافتراضية."""
    out = Assignment.blank("AS-0001", "خدمة").as_dict()
    assert out["counts_in_summary"] is True
    assert out["officer_ids"] == [] and out["note"] == ""


def test_reserved_word_fields_map_back():
    """`from` و`class` كلمات محجوزة في بايثون — بتتخزّن بأسمائها الأصلية."""
    hist = {"from": "2026-06-01", "role": "عقيد", "post": "", "section": "القوة",
            "search_attached": False}
    assert _round_trip(OfficerHistory, hist) == hist
    slot = {"class": "فرد", "count": 2}
    assert _round_trip(ConscriptSlot, slot) == slot


@pytest.mark.skipif(not HAS_REAL, reason="مافيش بيانات حقيقية")
def test_real_data_round_trips():
    """كل سجل في الملف الحقيقي بيرجع زي ما هو بالحرف."""
    data = real_data()
    checked = 0

    def check(model, raw, where):
        nonlocal checked
        assert _round_trip(model, raw) == raw, f"الشكل اتغيّر في {where}"
        checked += 1

    # القوة قايمة واحدة من هجرة 008 — و`status` بيفرّق القوة عن الأرشيف
    for o in data["officers"]:
        check(Officer, o, f"officers[{o.get('id')}]")
        for h in o.get("history") or []:
            check(OfficerHistory, h, f"history of {o.get('id')}")
    for p in data["personnel"]:
        check(Individual, p, f"personnel[{p.get('id')}]")

    for lv in data["leaves"]:
        check(Leave, lv, f"leaves[{lv.get('id')}]")
    for c in data["courses"]:
        check(Course, c, f"courses[{c.get('id')}]")
    for t in data["course_terms"]:
        check(CourseTerm, t, f"course_terms[{t.get('id')}]")
    for m in data.get("missions") or []:
        check(Mission, m, f"missions[{m.get('id')}]")
    for e in data.get("change_log") or []:
        check(ChangeEntry, e, f"change_log[{e.get('id')}]")
    for e in (data.get("counts_template") or {}).get("entries") or []:
        check(CountEntry, e, f"counts_template[{e.get('id')}]")

    for day, rows in data["day_assignments"].items():
        for row in rows:
            check(Assignment, row, f"day_assignments[{day}][{row.get('id')}]")
            for slot in row.get("conscripts") or []:
                check(ConscriptSlot, slot, f"conscripts of {row.get('id')}")
    for day, states in data["day_officers"].items():
        for oid, state in states.items():
            check(OfficerDayState, state, f"day_officers[{day}][{oid}]")

    assert checked > 3000, f"الاختبار فحص {checked} سجل بس — المتوقع آلاف"


# ---------- التحقق ----------

def test_officer_requires_name_and_valid_rank():
    errors = Officer.from_dict({"id": "OFF-1", "code": "1",
                                "join_date": "2026-01-01", "role": "رتبة مخترعة"}).validate()
    assert "الاسم مطلوب." in errors
    assert "الرتبة غير صحيحة." in errors


def test_weekly_rest_without_a_weekday_is_rejected():
    """راحة أسبوعية من غير يوم بتعطّل حساب التقصيرة في صمت."""
    officer = Officer.from_dict({"id": "OFF-1", "name": "فلان", "code": "1",
                                 "role": "نقيب", "join_date": "2026-01-01",
                                 "rest_system": "أسبوعية", "rest_day": ""})
    assert "الراحة الأسبوعية لازم يتحدد ليها يوم في الأسبوع." in officer.validate()


def test_leave_dates_must_be_ordered_and_sane():
    assert "تاريخ النهاية قبل تاريخ البداية." in Leave.from_dict({
        "person_id": "OFF-1", "type": "أسبوعية",
        "start": "2026-03-10", "end": "2026-03-01"}).validate()
    assert "مدة الراحة كبيرة بشكل غير منطقي." in Leave.from_dict({
        "person_id": "OFF-1", "type": "أسبوعية",
        "start": "2026-01-01", "end": "2026-12-31"}).validate()


def test_leave_must_fall_inside_the_person_service_period():
    person = Officer.from_dict({"id": "OFF-1", "join_date": "2026-06-01",
                                "leave_date": "2026-08-01"})
    early = Leave.from_dict({"start": "2026-05-01", "end": "2026-05-02"})
    assert "قبل تاريخ انضمام" in early.within_service(person)
    late = Leave.from_dict({"start": "2026-09-01", "end": "2026-09-02"})
    assert "بعد تاريخ خروج" in late.within_service(person)
    inside = Leave.from_dict({"start": "2026-07-01", "end": "2026-07-02"})
    assert inside.within_service(person) is None


def test_guard_service_has_no_shift():
    """الحراسات هدف ثابت طول اليوم فمالهاش فترة."""
    row = Assignment.from_dict({"name": "هدف", "kind": "حراسات", "shift": "صباحية"})
    assert "الحراسات مالهاش فترة." in row.validate()
    assert Assignment.from_dict({"name": "هدف", "kind": "حراسات", "shift": ""}).ok


# ---------- سلوك ----------

def test_officer_effective_reads_the_dated_history():
    """يومية 5/7 لازم تطبع «مقدم» مش «عقيد» بعد الترقية."""
    officer = Officer.from_dict({
        "id": "OFF-1", "role": "عقيد", "post": "مدير", "section": "القوة",
        "history": [{"from": "2026-06-01", "role": "مقدم", "post": "مدير",
                     "section": "القوة", "search_attached": False},
                    {"from": "2026-08-01", "role": "عقيد", "post": "مدير",
                     "section": "القوة", "search_attached": False}]})
    assert officer.effective("2026-07-05")["role"] == "مقدم"
    assert officer.effective("2026-09-01")["role"] == "عقيد"


def test_on_force_respects_join_and_leave_dates():
    officer = Officer.from_dict({"id": "OFF-1", "join_date": "2026-06-01",
                                 "leave_date": "2026-08-01"})
    assert not officer.on_force("2026-05-31")
    assert officer.on_force("2026-06-01") and officer.on_force("2026-08-01")
    assert not officer.on_force("2026-08-02")


def test_assignment_label_embeds_the_shift():
    row = Assignment.from_dict({"name": "تدخل سريع", "shift": "صباحية"})
    assert row.label() == "تدخل سريع صبح"
    assert row.label(with_shift=False) == "تدخل سريع"


def test_empty_officer_state_is_detected():
    """الحالة الفاضية بتتشال من الملف بدل ما تتخزّن مدخل فاضي."""
    assert OfficerDayState.from_dict({}).empty
    assert not OfficerDayState.from_dict({"note": "راحة"}).empty


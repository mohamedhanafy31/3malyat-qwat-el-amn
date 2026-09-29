"""حالة الراحة/التقصيرة — والضابط المتحد بفرقة اللي مش داخل في دورة
الراحة الأسبوعية طول مدة الالتحاق.

مثال حقيقي: ضابط عنده فرقة لحد يوم 24، رحته الأسبوعية يوم الجمعة — مفيش
داعي لتنبيه تقصيرة كل جمعة واقعة جوّه مدة الفرقة، لأنه أصلًا مش هيشتغل
عشان يقصّر منه. الاختبارات هنا بتنادي `rest_status` مباشرة بتاريخ محدد
بدل `date.today()` الحقيقي، عشان تفضل حتمية مهما كان تاريخ التشغيل.
"""
from datetime import date

from backend import store
from backend.rest_status import officer_status

DAY = "2026-04-10"


def _term(client, officer_id="OFF-001", start="2026-04-05", end="2026-04-24"):
    course = client.post("/api/courses", json={"name": "فرقة الحراسات المشددة"}).get_json()
    r = client.post("/api/course-terms",
                    json={"officer_id": officer_id, "course_id": course["id"],
                         "start": start, "end": end})
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def _officer(client, officer_id="OFF-001"):
    officers = client.get("/api/bootstrap/officers").get_json()["officers"]["active"]
    return next(o for o in officers if o["id"] == officer_id)


def test_officer_without_a_course_gets_taqseera_normally(client, data_file):
    """قاعدة أساسية: مفيش فرقة، الدورة الأسبوعية بتشتغل عادي — OFF-001
    رحته الأسبوعية السبت."""
    officer = _officer(client)
    data = store.assemble()
    st = officer_status(data, officer, date(2026, 4, 17))   # الجمعة قبل سبت 18/4
    assert st["state"] == "taqseera"
    assert st["taqseera_date"] == "2026-04-17"


def test_a_friday_taqseera_inside_an_active_course_is_suppressed(client, data_file):
    """السبت الجاي (18/4) جوّه مدة الفرقة (5/4 لحد 24/4) — يوم التقصيرة
    (17/4) نفسه واقع جواها، فمفيش داعي للتنبيه أصلًا."""
    _term(client)
    officer = _officer(client)
    data = store.assemble()

    st = officer_status(data, officer, date(2026, 4, 17))
    assert st["state"] == "working", "يوم التقصيرة نفسه جوّه مدة الفرقة"


def test_a_rest_saturday_that_falls_right_after_the_course_ends_is_not_suppressed(client, data_file):
    """الفرقة لحد 24/4. يوم التقصيرة اللي بعده (24/4 نفسه، قبل سبت 25/4)
    لسه جوّه مدة الفرقة فبيتجاهل، لكن أول جمعة بعد كده فعليًا (يوم
    التقصيرة بره الفرقة) لازم يرجع يطلع عادي."""
    _term(client, start="2026-04-05", end="2026-04-24")
    officer = _officer(client)
    data = store.assemble()

    # اليوم اللي التقصيرة بتاعته (24/4) لسه آخر يوم في الفرقة — مقموع
    st_last_day = officer_status(data, officer, date(2026, 4, 23))
    assert st_last_day["state"] != "taqseera"

    # بعد ما الفرقة خلصت خالص، الدورة العادية بترجع تشتغل من غير أي أثر
    st_after = officer_status(data, officer, date(2026, 4, 30))
    assert st_after["state"] in ("taqseera", "upcoming")
    assert st_after["rest_start"] == "2026-05-02"


def test_a_recorded_leave_during_the_course_still_counts(client, data_file):
    """الراحة المسجّلة بيانات حقيقية اتكتبت بإيد حد — تفضل صالحة حتى لو
    وقعت جوّه مدة الفرقة، عكس التخمين الأسبوعي الدوري."""
    _term(client, start="2026-04-05", end="2026-04-24")
    r = client.post("/api/leaves", json={"person_id": "OFF-001", "type": "إجازة طارئة",
                                         "start": "2026-04-15", "end": "2026-04-15"})
    assert r.status_code == 201, r.get_json()
    officer = _officer(client)
    data = store.assemble()

    st = officer_status(data, officer, date(2026, 4, 15))
    assert st["state"] == "resting"


def test_a_course_for_a_different_officer_does_not_affect_this_one(client, data_file):
    _term(client, officer_id="OFF-002")
    officer = _officer(client, "OFF-001")
    data = store.assemble()

    st = officer_status(data, officer, date(2026, 4, 17))
    assert st["state"] == "taqseera"


def test_an_officer_without_a_weekly_rest_system_is_unaffected_by_courses(client, data_file):
    """OFF-002 نظامه «—» — مفيش دورة أسبوعية أصلًا تتقاطع مع الفرقة."""
    _term(client, officer_id="OFF-002")
    officers = client.get("/api/bootstrap/officers").get_json()["officers"]["active"]
    officer = next(o for o in officers if o["id"] == "OFF-002")
    data = store.assemble()

    assert officer_status(data, officer, date(2026, 4, 17))["state"] == "working"

"""القادم والمعلّق — راحات هترجع، فرق هتبدأ، وخدمات بكرة لسه شاغرة.
كل حاجة محسوبة من البيانات الموجودة، مفيش تخزين جديد.
"""
from datetime import date


def test_leave_ending_within_the_horizon_is_included(client):
    """LV-001 في الـfixture بتنتهي يوم 2026-01-10."""
    from backend.store import load_data
    from backend.upcoming import leaves_ending_soon

    data = load_data()
    out = leaves_ending_soon(data, date(2026, 1, 8))
    assert [lv["id"] for lv in out] == ["LV-001"]
    assert out[0]["person_name"] == "أحمد محمد"
    assert out[0]["person_role"] == "عقيد"


def test_leave_ending_soon_does_not_mutate_stored_leave(client):
    from backend.store import load_data
    from backend.upcoming import leaves_ending_soon

    data = load_data()
    stored = next(lv for lv in data["leaves"] if lv["id"] == "LV-001")
    before = stored.copy()

    out = leaves_ending_soon(data, date(2026, 1, 8))

    assert stored == before
    assert out[0] is not stored


def test_leave_ending_today_counts_as_soon(client):
    from backend.store import load_data
    from backend.upcoming import leaves_ending_soon

    data = load_data()
    out = leaves_ending_soon(data, date(2026, 1, 10))
    assert [lv["id"] for lv in out] == ["LV-001"]


def test_leave_already_ended_is_excluded(client):
    from backend.store import load_data
    from backend.upcoming import leaves_ending_soon

    data = load_data()
    out = leaves_ending_soon(data, date(2026, 1, 20))
    assert out == []


def test_leave_far_in_the_future_is_excluded(client):
    from backend.store import load_data
    from backend.upcoming import leaves_ending_soon

    data = load_data()
    out = leaves_ending_soon(data, date(2025, 12, 1))
    assert out == []


def test_course_starting_soon_is_included(client):
    course = client.post("/api/courses", json={"name": "فرقة اختبار", "kind": "تدريبية"}).get_json()
    client.post("/api/course-terms", json={
        "officer_id": "OFF-002", "course_id": course["id"],
        "start": "2026-05-05", "end": "2026-05-10"})

    from backend.store import load_data
    from backend.upcoming import courses_starting_soon
    data = load_data()
    out = courses_starting_soon(data, date(2026, 5, 3))
    assert len(out) == 1
    assert out[0]["officer_name"] == "محمود علي"
    assert out[0]["course_name"] == "فرقة اختبار"


def test_tomorrow_vacant_reads_the_next_days_board(client):
    """صف شاغر بكرة (من غير ضابط/فرد/عدد مجندين) لازم يظهر هنا."""
    client.post("/api/assignments/2026-06-02", json={
        "name": "خدمة شاغرة", "kind": "خارجية", "section": "الخدمات الطارئة"})

    from backend.store import load_data
    from backend.upcoming import tomorrow_vacant
    data = load_data()
    out = tomorrow_vacant(data, date(2026, 6, 1))
    assert any("خدمة شاغرة" in w["text"] for w in out)


def test_dashboard_bootstrap_includes_upcoming(client):
    d = client.get("/api/bootstrap/dashboard").get_json()
    assert set(d["upcoming"]) == {"leaves_ending_soon", "courses_starting_soon", "tomorrow_vacant"}

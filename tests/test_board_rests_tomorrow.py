"""اليومية التفصيلية: ضباط راحتهم أو إجازتهم (أي نوع) بتبدأ بكرة، لكل يوم معروض."""
from backend import store


def _add_leave(ident, person, kind, start, end, back):
    def add(data):
        data.setdefault("leaves", []).append({
            "id": ident, "person_id": person, "type": kind, "start": start, "end": end,
            "return_date": back, "note": "", "source": "من الأرشيف"})
    store.with_data(add)


def _rests(client, day):
    response = client.get(f"/api/board/{day}")
    assert response.status_code == 200
    return {item["id"]: item for item in response.get_json()["rests_tomorrow"]}


def test_monthly_and_half_monthly_rests_are_listed_the_day_before(client):
    _add_leave("LV-M1", "OFF-001", "شهرية", "2026-01-17", "2026-01-23", "2026-01-24")
    _add_leave("LV-M2", "OFF-002", "نصف شهرية", "2026-01-17", "2026-01-19", "2026-01-20")

    tomorrow = _rests(client, "2026-01-16")

    assert tomorrow["OFF-001"]["type"] == "شهرية" and tomorrow["OFF-001"]["rest_start"] == "2026-01-17"
    assert tomorrow["OFF-002"]["type"] == "نصف شهرية"
    # مش بتظهر قبل اليوم اللي قبلها ولا بعد ما تبدأ
    assert "OFF-001" not in _rests(client, "2026-01-14")
    assert "OFF-001" not in _rests(client, "2026-01-18")


def test_leave_types_and_the_officers_work_today_are_included(client):
    _add_leave("LV-V1", "OFF-001", "إجازة اعتيادية", "2026-02-03", "2026-02-12", "2026-02-13")
    client.put("/api/duty/2026-02-02/OFF-001", json={"note": "مناوبة المكتب"})

    item = _rests(client, "2026-02-02")["OFF-001"]

    assert item["type"] == "إجازة اعتيادية"
    assert "مناوبة المكتب" in item["service"]


def test_no_rests_tomorrow_means_an_empty_list(client):
    assert client.get("/api/board/2026-03-05").get_json()["rests_tomorrow"] == []

"""مدير/وكيل الإدارة أعلى اتنين في أي قايمة ضباط، بغض النظر عن الرتبة."""


def test_deputy_ranks_ahead_of_higher_or_equal_rank_officers(client):
    """في الـfixture: OFF-001 عقيد، OFF-002 نقيب. لو OFF-002 وكيل الإدارة،
    لازم يظهر قبل OFF-001 رغم إن رتبته أقل."""
    client.patch("/api/command", json={"وكيل الإدارة": "OFF-002"})
    active = client.get("/api/data").get_json()["officers"]["active"]
    assert [o["id"] for o in active] == ["OFF-002", "OFF-001"]


def test_director_ahead_of_deputy(client):
    client.patch("/api/command", json={"مدير الإدارة": "OFF-002", "وكيل الإدارة": "OFF-001"})
    active = client.get("/api/data").get_json()["officers"]["active"]
    assert [o["id"] for o in active] == ["OFF-002", "OFF-001"]


def test_officers_on_day_also_respects_command_order(client):
    client.patch("/api/command", json={"وكيل الإدارة": "OFF-002"})
    rows = client.get("/api/duty/2026-06-01").get_json()["rows"]
    assert rows[0]["id"] == "OFF-002"


def test_archiving_command_holder_clears_the_post(client):
    client.patch("/api/command", json={"مدير الإدارة": "OFF-001"})
    r = client.post("/api/person/OFF-001/remove", json={"leave_date": "2026-06-01"})
    assert r.status_code == 200
    assert client.get("/api/data").get_json()["command"]["مدير الإدارة"] is None


def test_archiving_medical_officer_removes_him_from_the_list(client):
    client.patch("/api/medical-officers", json={"officer_ids": ["OFF-001"]})
    client.post("/api/person/OFF-001/remove", json={"leave_date": "2026-06-01"})
    assert client.get("/api/data").get_json()["medical_officers"] == []

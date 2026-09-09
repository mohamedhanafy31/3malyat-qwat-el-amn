"""يومية الضباط — جدول الإجمالي وحالة الضابط.

التكليف بخدمة بقى في `/api/assignments` (نفس نقطة اللوحة) — الملف ده
للإجمالي وحالة الضابط بس. التكليفات نفسها في test_projections.py.
"""


def test_balance_invariant_with_no_duties(client):
    r = client.get("/api/duty/2026-03-01")
    assert r.status_code == 200
    s = r.get_json()["summary"]
    assert s["balanced"] is True
    assert s["أصل القوة"] == 2
    assert s["صافي"] == 2          # مفيش تكليف لحد = الكل في الصافي


def test_every_officer_lands_in_exactly_one_cell(client):
    """مجموع خانات الجدول لازم يساوي أصل القوة — ده ثابت في الوورد في كل
    الأيام المفحوصة (34 من 34)."""
    client.post("/api/assignments/2026-03-01",
                json={"service_id": "SVC-001", "shift": "صباحية",
                      "officer_ids": ["OFF-002"]})
    client.put("/api/duty/2026-03-01/OFF-001", json={"status": "انتداب"})
    s = client.get("/api/duty/2026-03-01").get_json()["summary"]
    assert s["counted"] == s["أصل القوة"] == 2
    assert s["balanced"] is True


def test_state_only_officer_is_not_dropped_from_the_file(client):
    client.put("/api/duty/2026-03-01/OFF-002", json={"note": "متابعة أعمال"})
    assert _row(client, "OFF-002")["note"] == "متابعة أعمال"
    client.put("/api/duty/2026-03-01/OFF-002", json={"note": ""})
    assert _row(client, "OFF-002")["note"] == ""


def test_state_for_officer_not_on_force_that_day_rejected(client):
    assert client.put("/api/duty/2019-01-01/OFF-002", json={}).status_code == 404


def test_bad_date_is_refused(client):
    assert client.get("/api/duty/مش-تاريخ").status_code == 400


def test_clear_officer_state_delete_endpoint(client):
    # Set state
    client.put("/api/duty/2026-03-01/OFF-001", json={"status": "انتداب", "note": "تست"})
    assert _row(client, "OFF-001")["status"] == "انتداب"

    # Delete state
    res = client.delete("/api/duty/2026-03-01/OFF-001")
    assert res.status_code == 200
    assert res.get_json()["ok"] is True
    assert _row(client, "OFF-001")["status"] == ""


def test_clear_assignments_day_delete_endpoint(client):
    # Create assignment and state
    client.post("/api/assignments/2026-03-01", json={"service_id": "SVC-001", "shift": "صباحية", "officer_ids": ["OFF-001"]})
    client.put("/api/duty/2026-03-01/OFF-001", json={"status": "انتداب"})

    # Bulk clear day with clear_states=1
    res = client.delete("/api/assignments/2026-03-01?clear_states=1")
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    assert body["states_cleared"] is True
    assert len(client.get("/api/assignments/2026-03-01").get_json()["assignments"]) == 0
    assert _row(client, "OFF-001")["status"] == ""


def _row(client, officer_id, day="2026-03-01"):
    d = client.get(f"/api/duty/{day}").get_json()
    return next(r for r in d["rows"] if r["id"] == officer_id)


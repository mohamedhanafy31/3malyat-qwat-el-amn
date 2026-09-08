def test_balance_invariant_with_no_duties(client):
    r = client.get("/api/duty/2026-03-01")
    assert r.status_code == 200
    s = r.get_json()["summary"]
    assert s["balanced"] is True
    assert s["أصل القوة"] == 2
    assert s["صافي"] == 2          # مفيش تكليف لحد = الكل في الصافي


def test_assign_service_moves_out_of_net(client):
    r = client.put("/api/duty/2026-03-01/OFF-002", json={
        "items": [{"service_id": "SVC-001", "shift": "صباحية"}],
    })
    assert r.status_code == 200
    s = r.get_json()["summary"]
    assert s["balanced"] is True
    assert s["صافي"] == 1
    assert s["خارجية"]["صباحية"] == 1


def test_assign_unknown_service_rejected(client):
    r = client.put("/api/duty/2026-03-01/OFF-002", json={
        "items": [{"service_id": "SVC-999", "shift": "صباحية"}],
    })
    assert r.status_code == 400


def test_assign_officer_not_on_force_that_day_rejected(client):
    r = client.put("/api/duty/2019-01-01/OFF-002", json={"items": []})
    assert r.status_code == 404

"""«مهام اليوم» في الرئيسية — حالة تأكيد اليومية وآخر التغييرات بتوصل مع
bootstrap الرئيسية نفسه، من غير طلبات زيادة."""


def test_dashboard_ships_today_confirm_state(client):
    d = client.get("/api/bootstrap/dashboard").get_json()
    assert {"confirmed", "pending", "count"} <= set(d["confirm"])
    assert d["confirm"]["confirmed"] in (True, False)


def test_dashboard_ships_at_most_five_recent_changes_newest_first(client):
    for i in range(7):
        r = client.post("/api/leaves", json={"person_id": "OFF-002", "type": "أسبوعية",
                                              "start": f"2026-03-{10 + i:02d}", "end": f"2026-03-{10 + i:02d}"})
        assert r.status_code in (200, 201), r.get_json()
    d = client.get("/api/bootstrap/dashboard").get_json()
    changes = d["recent_changes"]
    # سبع راحات اتسجّلوا، والرئيسية بتاخد آخر خمسة بس
    assert len(changes) == 5
    assert all(c["entity"] == "leave" for c in changes)
    stamps = [c.get("ts", "") for c in changes]
    assert stamps == sorted(stamps, reverse=True)

"""سجل خدمات الضابط — List زمني لضابط واحد على مدى تاريخ مختار."""
DAY = "2026-04-10"
DAY2 = "2026-04-11"


def _add(client, day=DAY, **over):
    body = {"name": "دورية خارجية", "kind": "خارجية", "section": "الخدمات أساسية",
            "shift": "صباحية"}
    body.update(over)
    r = client.post(f"/api/assignments/{day}", json=body)
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def _log(client, officer_id, date_from=DAY, date_to=DAY2):
    r = client.get(f"/api/officer-log/{officer_id}?date_from={date_from}&date_to={date_to}")
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def test_unknown_officer_404s(client):
    r = client.get(f"/api/officer-log/NOPE?date_from={DAY}&date_to={DAY2}")
    assert r.status_code == 404


def test_a_service_day_lists_the_service_and_weekday(client):
    """DAY = 2026-04-10 جمعة."""
    _add(client, day=DAY, officer_ids=["OFF-001"], name="نقطة تفتيش", kind="خارجية", shift="صباحية")

    d = _log(client, "OFF-001")
    row = next(r for r in d["rows"] if r["date"] == DAY)
    assert row["weekday"] == "الجمعة"
    assert [s["name"] for s in row["services"]] == ["نقطة تفتيش"]


def test_a_day_with_no_service_shows_up_as_net(client):
    _add(client, day=DAY, officer_ids=["OFF-002"])   # يوم مسجّل عشان يتحسب "recorded"

    d = _log(client, "OFF-001")
    row = next(r for r in d["rows"] if r["date"] == DAY)
    assert row["services"] == []
    assert row["group"] == "صافي"


def test_officer_response_includes_name_and_role(client):
    _add(client, day=DAY, officer_ids=["OFF-001"])
    d = _log(client, "OFF-001")
    assert d["officer"]["id"] == "OFF-001"
    assert d["officer"]["name"] == "أحمد محمد"
    assert d["officer"]["role"] == "عقيد"


def test_days_before_the_officer_joined_are_excluded(client):
    """ضابط اتضاف بعد بداية المدى — الأيام اللي قبل انضمامه ميظهروش صفوف
    ليها، عشان officers_on بيستبعده منها أصلًا."""
    r = client.post("/api/person", json={
        "type": "officer", "name": "ضابط جديد", "code": "NEW-1", "phone": "0102",
        "join_date": DAY2, "rest_system": "—",
    })
    assert r.status_code == 201, r.get_json()
    new_id = r.get_json()["id"]
    _add(client, day=DAY, officer_ids=["OFF-001"])
    _add(client, day=DAY2, officer_ids=["OFF-001"])

    d = _log(client, new_id, DAY, DAY2)
    assert not any(r["date"] == DAY for r in d["rows"])
    assert any(r["date"] == DAY2 for r in d["rows"])


def test_bootstrap_ships_officer_index_for_the_picker(client):
    d = client.get("/api/bootstrap/officer_log")
    assert d.status_code == 200, d.get_json()
    ids = {o["id"] for o in d.get_json()["officer_index"]}
    assert {"OFF-001", "OFF-002"}.issubset(ids)


def test_bootstrap_officer_index_excludes_archived_officers(client):
    """قايمة الاختيار دي لعرض سجل ضابط حاليًا شغّال — ضابط خرج من القوة
    زمان يفضل ينفع تتفرّج على سجله القديم من رابط مباشر (`?officer=`)
    بس مايتزحلقش في القايمة نفسها."""
    r = client.post("/api/person/OFF-002/remove", json={"leave_date": "2026-02-01", "reason": ""})
    assert r.status_code == 200, r.get_json()

    d = client.get("/api/bootstrap/officer_log")
    ids = {o["id"] for o in d.get_json()["officer_index"]}
    assert "OFF-001" in ids
    assert "OFF-002" not in ids

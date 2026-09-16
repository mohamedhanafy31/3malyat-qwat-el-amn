"""المأموريات — كيان له دورة حياة، مختلف عن الخدمة المتكررة."""


def _add(client, **over):
    body = {"name": "مأمورية اختبار"}
    body.update(over)
    return client.post("/api/missions", json=body)


def test_new_mission_defaults_to_planned_with_no_members(client):
    r = _add(client)
    assert r.status_code == 201
    body = r.get_json()
    assert body["status"] == "مخططة"
    assert body["members"] == []


def test_name_is_required(client):
    assert client.post("/api/missions", json={}).status_code == 400


def test_members_must_be_real_officers(client):
    r = _add(client, member_ids=["OFF-001", "OFF-999"])
    assert r.status_code == 400


def test_valid_members_resolve_to_names(client):
    r = _add(client, member_ids=["OFF-001", "OFF-002"])
    assert r.status_code == 201
    names = {m["name"] for m in r.get_json()["members"]}
    assert names == {"أحمد محمد", "محمود علي"}


def test_invalid_start_date_is_rejected(client):
    assert _add(client, start="مش تاريخ").status_code == 400


def test_status_moves_through_the_lifecycle(client):
    mid = _add(client).get_json()["id"]
    for status in ("بدأت", "عادت", "أغلقت"):
        r = client.patch(f"/api/missions/{mid}", json={"status": status})
        assert r.status_code == 200
        assert r.get_json()["status"] == status


def test_unknown_status_is_rejected(client):
    mid = _add(client).get_json()["id"]
    assert client.patch(f"/api/missions/{mid}", json={"status": "حالة مخترعة"}).status_code == 400


def test_editing_unknown_mission_404s(client):
    assert client.patch("/api/missions/MSN-999", json={"name": "س"}).status_code == 404


def test_delete_removes_the_mission(client):
    mid = _add(client).get_json()["id"]
    assert client.delete(f"/api/missions/{mid}").status_code == 200
    assert client.delete(f"/api/missions/{mid}").status_code == 404


def test_list_filters_by_status(client):
    a = _add(client, name="أ").get_json()["id"]
    _add(client, name="ب")
    client.patch(f"/api/missions/{a}", json={"status": "بدأت"})

    started = client.get("/api/missions?status=بدأت").get_json()["missions"]
    assert [m["id"] for m in started] == [a]

    planned = client.get("/api/missions?status=مخططة").get_json()["missions"]
    assert len(planned) == 1


def test_lifecycle_is_recorded_in_the_change_log(client):
    mid = _add(client).get_json()["id"]
    client.patch(f"/api/missions/{mid}", json={"status": "بدأت"})
    client.delete(f"/api/missions/{mid}")

    entries = client.get(f"/api/changes?entity=mission&entity_id={mid}").get_json()["entries"]
    actions = [e["action"] for e in entries]
    assert actions == ["delete", "update", "create"]

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


# ---------- دورة الحياة اتجاه واحد (#9) ----------

def test_jumping_over_a_stage_is_rejected(client):
    """من «مخططة» مباشرة لـ«أغلقت» — من غير ما تعدّي بـ«بدأت» و«عادت»."""
    mid = _add(client).get_json()["id"]
    r = client.patch(f"/api/missions/{mid}", json={"status": "أغلقت"})
    assert r.status_code == 400
    assert "أغلقت" in r.get_json()["error"]


def test_a_closed_mission_cannot_move_back(client):
    mid = _add(client).get_json()["id"]
    for status in ("بدأت", "عادت", "أغلقت"):
        client.patch(f"/api/missions/{mid}", json={"status": status})
    r = client.patch(f"/api/missions/{mid}", json={"status": "مخططة"})
    assert r.status_code == 400


def test_cancelling_is_allowed_from_any_open_stage(client):
    mid = _add(client).get_json()["id"]
    client.patch(f"/api/missions/{mid}", json={"status": "بدأت"})
    r = client.patch(f"/api/missions/{mid}", json={"status": "ألغيت"})
    assert r.status_code == 200


def test_setting_the_same_status_again_is_a_no_op(client):
    mid = _add(client).get_json()["id"]
    r = client.patch(f"/api/missions/{mid}", json={"status": "مخططة"})
    assert r.status_code == 200


# ---------- الأعضاء لازم يكونوا على القوة يوم بداية المأمورية (#9) ----------

def test_member_not_on_the_force_at_start_is_rejected(client):
    client.patch("/api/person/OFF-002", json={"join_date": "2026-05-01"})
    r = _add(client, member_ids=["OFF-002"], start="2026-04-10")
    assert r.status_code == 400
    assert "على القوة" in r.get_json()["error"]


def test_members_are_not_date_checked_when_no_start_is_set(client):
    """مالوش تاريخ بداية بعد؟ الأعضاء ينفع يتحطوا من غير أي فحص تاريخ —
    زي ما كان قبل كده."""
    client.patch("/api/person/OFF-002", json={"join_date": "2026-05-01"})
    r = _add(client, member_ids=["OFF-002"])
    assert r.status_code == 201


def test_member_on_force_at_start_is_accepted(client):
    r = _add(client, member_ids=["OFF-001"], start="2026-04-10")
    assert r.status_code == 201


# ---------- تنبيه: مكلّف بخدمة وهو في مأمورية بدأت (#9) ----------

def test_officer_on_a_started_mission_gets_flagged_if_assigned_a_service(client):
    mid = _add(client, member_ids=["OFF-001"], start="2026-04-10").get_json()["id"]
    client.patch(f"/api/missions/{mid}", json={"status": "بدأت"})

    client.post("/api/assignments/2026-04-12",
               json={"name": "دورية", "kind": "خارجية", "officer_ids": ["OFF-001"]})
    warnings = client.get("/api/board/2026-04-12").get_json()["warnings"]
    assert any(w["kind"] == "مأمورية" and w["officer_id"] == "OFF-001" for w in warnings)


def test_no_warning_before_the_mission_even_starts(client):
    mid = _add(client, member_ids=["OFF-001"], start="2026-04-10").get_json()["id"]
    client.patch(f"/api/missions/{mid}", json={"status": "بدأت"})

    client.post("/api/assignments/2026-04-09",
               json={"name": "دورية", "kind": "خارجية", "officer_ids": ["OFF-001"]})
    warnings = client.get("/api/board/2026-04-09").get_json()["warnings"]
    assert not any(w["kind"] == "مأمورية" for w in warnings)


def test_no_warning_once_the_mission_has_returned(client):
    mid = _add(client, member_ids=["OFF-001"], start="2026-04-10").get_json()["id"]
    client.patch(f"/api/missions/{mid}", json={"status": "بدأت"})
    client.patch(f"/api/missions/{mid}", json={"status": "عادت"})

    client.post("/api/assignments/2026-04-12",
               json={"name": "دورية", "kind": "خارجية", "officer_ids": ["OFF-001"]})
    warnings = client.get("/api/board/2026-04-12").get_json()["warnings"]
    assert not any(w["kind"] == "مأمورية" for w in warnings)

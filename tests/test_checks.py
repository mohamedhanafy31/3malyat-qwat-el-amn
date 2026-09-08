"""فحوصات اليوم — تنبيهات مش موانع.

المراجعة طلّعت إن مفيش أي فحص تعارض. لكن الأرشيف نفسه بيوضّح إن معظم
«التعارضات» النظرية شغل عادي: يومية 20/8 فيها ضابط على «تبة ضرب النار +
كنترول الازهر ليل» — خدمتين في نفس الفترة، ومقصودة. فالفحوصات بتنبّه
ومابتمنعش، والممنوع الوحيد هو التكرار الحرفي.
"""
DAY = "2026-04-10"


def _add(client, **over):
    body = {"service_id": "SVC-001", "shift": "صباحية"}
    body.update(over)
    return client.post(f"/api/assignments/{DAY}", json=body)


def _warnings(client, day=DAY):
    return client.get(f"/api/board/{day}").get_json()["warnings"]


def _kinds(client, day=DAY):
    return {w["kind"] for w in _warnings(client, day)}


def test_exact_duplicate_is_the_only_hard_block(client):
    _add(client, officer_ids=["OFF-002"])
    r = _add(client, officer_ids=["OFF-002"])
    assert r.status_code == 409
    assert "نفس الخدمة" in r.get_json()["error"]


def test_same_officer_on_two_services_same_shift_is_allowed(client):
    """ده شغل عادي في الوورد — بيتنبّه بس مش بيتمنع."""
    client.post("/api/services", json={"name": "خدمة تانية", "kind": "خارجية",
                                        "section": "الخدمات الطارئة"})
    second = client.get("/api/bootstrap/catalog").get_json()["services"][-1]
    assert _add(client, officer_ids=["OFF-002"]).status_code == 201
    assert _add(client, service_id=second["id"], officer_ids=["OFF-002"]).status_code == 201
    assert "ازدحام" in _kinds(client)


def test_assigning_an_officer_on_leave_warns(client):
    """OFF-001 عنده راحة يوم 2026-01-10 في الـfixture."""
    day = "2026-01-10"
    r = client.post(f"/api/assignments/{day}",
                    json={"service_id": "SVC-001", "officer_ids": ["OFF-001"]})
    assert r.status_code == 201, "التكليف بيتقبل — التنبيه مش منع"
    assert "راحة" in _kinds(client, day)


def test_status_plus_assignment_warns(client):
    client.put(f"/api/duty/{DAY}/OFF-002", json={"status": "انتداب"})
    _add(client, officer_ids=["OFF-002"])
    assert "حالة" in _kinds(client)


def test_service_that_needs_an_officer_and_has_none_warns(client):
    _add(client, officer_ids=[])
    warn = next(w for w in _warnings(client) if w["kind"] == "شاغرة")
    assert "دورية خارجية" in warn["text"]


def test_a_clean_day_has_no_warnings(client):
    _add(client, officer_ids=["OFF-002"])
    assert _warnings(client) == []


def test_editing_into_a_duplicate_is_blocked_too(client):
    first = _add(client, officer_ids=["OFF-001"]).get_json()
    second = _add(client, officer_ids=["OFF-002"]).get_json()
    r = client.patch(f"/api/assignments/{DAY}/{second['id']}",
                     json={"officer_ids": ["OFF-001"]})
    assert r.status_code == 409
    # والخانة الأصلية مالهاش دعوة
    assert first["officer_ids"] == ["OFF-001"]

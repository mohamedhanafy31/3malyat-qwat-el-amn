"""قيادة الإدارة — المدير والوكيل.

المنصب مش خدمة في الكتالوج، فالمدير والوكيل بيظهروا في قسم «عمل بالإدارة»
المحسوب — وده بالظبط اللي الوورد بيعمله: بيكتبهم في القسم ده كل يوم بنص
عملهم («مدير الادارة» / «وكيل الادارة»)، مش كخدمة في الخدمات الأساسية.

قبل كده كان السيستم بيزرع لهم خانات على اللوحة أول ما اليوم يتجهّز، فكانت
النتيجة غير متسقة: 18 يوم فيهم خانة «مدير الاداره» و17 فيهم «وكيل الاداره»
والباقي لأ — رغم إن الوورد بيكتبهم في كل يوم من الـ101.
"""

DIRECTOR, DEPUTY = "مدير الإدارة", "وكيل الإدارة"


def _set(client, role, officer_id):
    return client.patch("/api/command", json={role: officer_id})


def _admin_work(client, day):
    b = client.get(f"/api/board/{day}").get_json()
    return next(s for s in b["sections"] if s["name"] == "عمل بالإدارة")["rows"]


def test_command_shows_in_admin_work_every_day(client):
    _set(client, DIRECTOR, "OFF-001")
    _set(client, DEPUTY, "OFF-002")
    for day in ("2026-04-01", "2026-04-02", "2026-07-15"):
        rows = _admin_work(client, day)
        assert {(r["id"], r["text"]) for r in rows} == {
            ("OFF-001", DIRECTOR), ("OFF-002", DEPUTY)}, day


def test_officer_on_rest_moves_to_the_rest_section(client):
    """المدير في راحة بيتنقل لقسم «الراحات» زي أي ضابط — مش بيفضل في
    «عمل بالإدارة» ولا بيختفي."""
    _set(client, DIRECTOR, "OFF-001")
    b = client.get("/api/board/2026-01-10").get_json()   # OFF-001 في راحة يومها
    sections = {s["name"]: s["rows"] for s in b["sections"]}
    assert "OFF-001" not in {r["id"] for r in sections["عمل بالإدارة"]}
    assert "OFF-001" in {r["id"] for r in sections["الراحات"]}


def test_command_officer_with_a_service_stays_in_admin_work_too(client):
    _set(client, DIRECTOR, "OFF-001")
    client.post("/api/assignments/2026-04-03",
                json={"name": "دورية خارجية", "kind": "خارجية", "officer_ids": ["OFF-001"]})
    assert "OFF-001" in {r["id"] for r in _admin_work(client, "2026-04-03")}


def test_changing_command_updates_the_automatic_admin_officer(client):
    """عمل بالإدارة يقرأ شاغل المنصب المؤرّخ لليوم، مش تكليف خدمة."""
    day = client.get("/api/data").get_json()["meta"]["today"]
    _set(client, DIRECTOR, "OFF-001")
    assert "OFF-001" in {r["id"] for r in _admin_work(client, day)}

    _set(client, DIRECTOR, "OFF-002")
    ids = {r["id"] for r in _admin_work(client, day)}
    assert "OFF-002" in ids and "OFF-001" not in ids


def test_same_officer_cannot_hold_two_posts(client):
    _set(client, DIRECTOR, "OFF-001")
    assert _set(client, DEPUTY, "OFF-001").status_code == 409


def test_medical_and_search_are_group_roles_with_checkbox_style_selection(client):
    """«طبي» و«بحث» تحت «قيادة الإدارة» برضو، بس جماعيين — عكس مدير/وكيل
    الإدارة، أكتر من ضابط ممكن يشيلوا نفس المنصب في نفس الوقت
    (`PATCH /api/command-groups` بقايمة معرّفات كاملة، مش تعيين مفرد)."""
    r = client.patch("/api/command-groups", json={"طبي": ["OFF-001", "OFF-002"]})
    assert r.status_code == 200, r.get_json()
    assert set(r.get_json()["طبي"]) == {"OFF-001", "OFF-002"}

    d = client.get("/api/data").get_json()
    assert set(d["command_groups"]["طبي"]) == {"OFF-001", "OFF-002"}
    assert d["command_groups"]["بحث"] == []


def test_command_groups_rejects_unknown_role_and_non_list_and_missing_officer(client):
    assert client.patch("/api/command-groups",
                        json={"منصب مخترع": ["OFF-001"]}).status_code == 400
    assert client.patch("/api/command-groups", json={"طبي": "OFF-001"}).status_code == 400
    assert client.patch("/api/command-groups", json={"طبي": ["OFF-999"]}).status_code == 404


def test_command_groups_replace_membership_entirely(client):
    """كل نداء بيستبدل الأعضاء بالكامل — مش إضافة تراكمية."""
    client.patch("/api/command-groups", json={"طبي": ["OFF-001", "OFF-002"]})
    client.patch("/api/command-groups", json={"طبي": ["OFF-002"]})
    d = client.get("/api/data").get_json()
    assert d["command_groups"]["طبي"] == ["OFF-002"]


def test_rejects_unknown_role_and_missing_officer(client):
    assert client.patch("/api/command", json={"منصب مخترع": "OFF-001"}).status_code == 400
    assert _set(client, DIRECTOR, "OFF-999").status_code == 404


def test_command_exposed_in_api_data(client):
    _set(client, DIRECTOR, "OFF-001")
    d = client.get("/api/data").get_json()
    assert d["command"][DIRECTOR] == "OFF-001"
    assert d["meta"]["command_roles"] == [DIRECTOR, DEPUTY]
    assert d["meta"]["group_roles"] == ["طبي", "بحث"]

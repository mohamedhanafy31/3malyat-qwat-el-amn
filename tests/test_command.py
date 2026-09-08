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
        assert {r["id"] for r in _admin_work(client, day)} == {"OFF-001", "OFF-002"}, day


def test_officer_on_rest_moves_to_the_rest_section(client):
    """المدير في راحة بيتنقل لقسم «الراحات» زي أي ضابط — مش بيفضل في
    «عمل بالإدارة» ولا بيختفي."""
    _set(client, DIRECTOR, "OFF-001")
    b = client.get("/api/board/2026-01-10").get_json()   # OFF-001 في راحة يومها
    sections = {s["name"]: s["rows"] for s in b["sections"]}
    assert "OFF-001" not in {r["id"] for r in sections["عمل بالإدارة"]}
    assert "OFF-001" in {r["id"] for r in sections["الراحات"]}


def test_command_officer_with_a_service_leaves_admin_work(client):
    _set(client, DIRECTOR, "OFF-001")
    client.post("/api/assignments/2026-04-03",
                json={"service_id": "SVC-001", "officer_ids": ["OFF-001"]})
    assert "OFF-001" not in {r["id"] for r in _admin_work(client, "2026-04-03")}


def test_changing_command_does_not_rewrite_the_archive(client):
    """المنصب بيتغيّر مع حركة الضباط، والأيام القديمة بتفضل زي ما هي لأن
    اللي بيحدد ظهور الضابط في «عمل بالإدارة» هو تكليفاته في اليوم ده
    مش المنصب الحالي."""
    _set(client, DIRECTOR, "OFF-001")
    day = "2026-04-04"
    client.post(f"/api/assignments/{day}",
                json={"service_id": "SVC-001", "officer_ids": ["OFF-001"]})
    before = {r["id"] for r in _admin_work(client, day)}

    _set(client, DIRECTOR, "OFF-002")
    assert {r["id"] for r in _admin_work(client, day)} == before


def test_same_officer_cannot_hold_two_posts(client):
    _set(client, DIRECTOR, "OFF-001")
    assert _set(client, DEPUTY, "OFF-001").status_code == 409


def test_rejects_unknown_role_and_missing_officer(client):
    assert client.patch("/api/command", json={"منصب مخترع": "OFF-001"}).status_code == 400
    assert _set(client, DIRECTOR, "OFF-999").status_code == 404


def test_command_exposed_in_api_data(client):
    _set(client, DIRECTOR, "OFF-001")
    d = client.get("/api/data").get_json()
    assert d["command"][DIRECTOR] == "OFF-001"
    assert d["meta"]["command_roles"] == [DIRECTOR, DEPUTY]

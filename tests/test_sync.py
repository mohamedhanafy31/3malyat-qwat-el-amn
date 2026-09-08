"""الربط بين اللوحة المختصرة ويومية التشغيل في الاتجاهين."""

DAY = "2026-04-10"


def _summary(client, day=DAY):
    return client.get(f"/api/duty/{day}").get_json()["summary"]


def _row(client, officer_id, day=DAY):
    d = client.get(f"/api/duty/{day}").get_json()
    return next(r for r in d["rows"] if r["id"] == officer_id)


def _board_entries(client, day=DAY):
    b = client.get(f"/api/board/{day}").get_json()
    return [e for c in b["categories"] for e in c["entries"]]


# ---------- اللوحة -> يومية التشغيل ----------

def test_assigning_on_board_moves_officer_out_of_net(client):
    """ده بالظبط اللي كان مكسور: حطّيت ضابط على خدمة من اللوحة، وفضل
    محسوب صافي في جدول الإجمالي وظاهر في «عمل بالإدارة»."""
    assert _summary(client)["صافي"] == 2
    client.post(f"/api/board/{DAY}/entries", json={
        "service": "دورية خارجية", "category": "الخدمات الأساسية",
        "shift": "صباحية", "officer_id": "OFF-002"})

    s = _summary(client)
    assert s["صافي"] == 1
    assert s["خارجية"]["صباحية"] == 1
    assert s["balanced"] is True
    assert _row(client, "OFF-002")["group"] == "خارجية"


def test_removing_board_entry_returns_officer_to_net(client):
    r = client.post(f"/api/board/{DAY}/entries", json={
        "service": "دورية خارجية", "category": "الخدمات الأساسية",
        "shift": "صباحية", "officer_id": "OFF-002"})
    entry_id = r.get_json()["id"]
    client.delete(f"/api/board/{DAY}/entries/{entry_id}")

    assert _summary(client)["صافي"] == 2
    assert _row(client, "OFF-002")["group"] == "صافي"


def test_reassigning_entry_updates_both_officers(client):
    r = client.post(f"/api/board/{DAY}/entries", json={
        "service": "دورية خارجية", "category": "الخدمات الأساسية",
        "shift": "صباحية", "officer_id": "OFF-002"})
    entry_id = r.get_json()["id"]
    client.patch(f"/api/board/{DAY}/entries/{entry_id}", json={"officer_id": "OFF-001"})

    assert _row(client, "OFF-002")["group"] == "صافي"
    assert _row(client, "OFF-001")["group"] == "خارجية"
    assert _summary(client)["balanced"] is True


def test_clearing_officer_from_entry_frees_him(client):
    r = client.post(f"/api/board/{DAY}/entries", json={
        "service": "دورية خارجية", "category": "الخدمات الأساسية",
        "shift": "صباحية", "officer_id": "OFF-002"})
    entry_id = r.get_json()["id"]
    client.patch(f"/api/board/{DAY}/entries/{entry_id}", json={"officer_id": ""})
    assert _row(client, "OFF-002")["group"] == "صافي"


def test_admin_post_is_not_treated_as_a_service(client):
    """المناصب الإدارية (مش في الكتالوج) مالهاش تصنيف في جدول الإجمالي،
    فالضابط لازم يفضل صافي — ده مقصود مش سهو."""
    client.post(f"/api/board/{DAY}/entries", json={
        "service": "مدير الإدارة", "category": "أدوار بالإدارة",
        "officer_id": "OFF-002"})
    assert _row(client, "OFF-002")["group"] == "صافي"
    assert _summary(client)["balanced"] is True


def test_board_edit_preserves_taqseera_and_note(client):
    """التقصيرة/الملاحظة حالة الضابط نفسه — المزامنة ما تمسحهاش."""
    client.put(f"/api/duty/{DAY}/OFF-002", json={
        "items": [], "taqseera": True, "note": "خرج بدري"})
    client.post(f"/api/board/{DAY}/entries", json={
        "service": "دورية خارجية", "category": "الخدمات الأساسية",
        "shift": "صباحية", "officer_id": "OFF-002"})

    row = _row(client, "OFF-002")
    assert row["taqseera"] is True
    assert row["note"] == "خرج بدري"


# ---------- يومية التشغيل -> اللوحة ----------

def test_duty_assignment_appears_on_board(client):
    services = client.get("/api/data").get_json()["services"]
    svc = next(s for s in services if s["name"] == "دورية خارجية")
    client.put(f"/api/duty/{DAY}/OFF-002", json={
        "items": [{"service_id": svc["id"], "shift": "ليلية"}]})

    mine = [e for e in _board_entries(client) if e["officer_id"] == "OFF-002"]
    assert [(e["service"], e["shift"]) for e in mine] == [("دورية خارجية", "ليلية")]


def test_unassigning_in_duty_leaves_the_slot_vacant(client):
    """الخدمة نفسها لسه مطلوبة — الخانة تفضل على اللوحة بس من غير ضابط،
    عشان تبان إنها محتاجة بديل بدل ما تختفي بالسكوت."""
    services = client.get("/api/data").get_json()["services"]
    svc = next(s for s in services if s["name"] == "دورية خارجية")
    client.put(f"/api/duty/{DAY}/OFF-002", json={
        "items": [{"service_id": svc["id"], "shift": "ليلية"}]})
    client.put(f"/api/duty/{DAY}/OFF-002", json={"items": []})

    slot = next(e for e in _board_entries(client) if e["service"] == "دورية خارجية")
    assert slot["officer_id"] is None


def test_round_trip_is_stable(client):
    """تكليف من اليومية ثم مزامنة عكسية ما يكررش الخانات ولا يقلب الأرقام."""
    services = client.get("/api/data").get_json()["services"]
    svc = next(s for s in services if s["name"] == "دورية خارجية")
    for _ in range(3):
        client.put(f"/api/duty/{DAY}/OFF-002", json={
            "items": [{"service_id": svc["id"], "shift": "صباحية"}]})

    mine = [e for e in _board_entries(client) if e["officer_id"] == "OFF-002"]
    assert len(mine) == 1
    assert _summary(client)["balanced"] is True

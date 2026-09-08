"""قيادة الإدارة — المدير والوكيل، تشغيلهم الثابت اليومي وتغييرهم."""

DIRECTOR, DEPUTY = "مدير الإدارة", "وكيل الإدارة"


def _admin_card(client, day):
    b = client.get(f"/api/board/{day}").get_json()
    return next(c for c in b["categories"] if c["name"] == "أدوار بالإدارة")


def _set(client, role, officer_id):
    return client.patch("/api/command", json={role: officer_id})


def test_command_seeded_into_a_brand_new_day(client):
    _set(client, DIRECTOR, "OFF-001")
    _set(client, DEPUTY, "OFF-002")
    card = _admin_card(client, "2026-04-01")
    assert [(e["service"], e["officer_id"]) for e in card["entries"]] == [
        (DIRECTOR, "OFF-001"), (DEPUTY, "OFF-002")]


def test_officer_on_rest_is_skipped(client):
    _set(client, DIRECTOR, "OFF-001")
    _set(client, DEPUTY, "OFF-002")
    # OFF-001 عنده راحة يوم 2026-01-10 في الـfixture
    card = _admin_card(client, "2026-01-10")
    holders = [e["officer_id"] for e in card["entries"]]
    assert "OFF-001" not in holders
    assert "OFF-002" in holders


def test_unset_role_adds_nothing(client):
    _set(client, DIRECTOR, "OFF-001")
    _set(client, DEPUTY, None)
    card = _admin_card(client, "2026-04-02")
    assert [e["officer_id"] for e in card["entries"]] == ["OFF-001"]


def test_reassigning_does_not_rewrite_already_saved_days(client):
    """اليوم اللي اتحفظ بالفعل بيفضل زي ما هو — تغيير القيادة بيأثر على
    الأيام الجديدة بس، عشان الأرشيف ما يتغيّرش بأثر رجعي."""
    _set(client, DIRECTOR, "OFF-001")
    day = "2026-04-03"
    client.post(f"/api/board/{day}/entries", json={"service": "خدمة", "category": "الخدمات الطارئة"})
    before = [e["officer_id"] for e in _admin_card(client, day)["entries"]]
    assert before == ["OFF-001"]

    _set(client, DIRECTOR, "OFF-002")
    after = [e["officer_id"] for e in _admin_card(client, day)["entries"]]
    assert after == ["OFF-001"], "اليوم المحفوظ مالوش دعوة بالتغيير الجديد"

    fresh = [e["officer_id"] for e in _admin_card(client, "2026-04-04")["entries"]]
    assert fresh == ["OFF-002"], "اليوم الجديد بياخد القيادة الحالية"


def test_deleting_command_entry_does_not_resurrect_it(client):
    _set(client, DIRECTOR, "OFF-001")
    day = "2026-04-05"
    entry = _admin_card(client, day)["entries"][0]
    assert client.delete(f"/api/board/{day}/entries/{entry['id']}").status_code == 200
    assert _admin_card(client, day)["entries"] == []


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

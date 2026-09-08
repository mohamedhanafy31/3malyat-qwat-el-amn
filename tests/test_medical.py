"""ضباط العيادة الطبية — حالة خاصة: تشغيلهم "طبية" (موجود/راحة) تلقائيًا
كل يوم جديد، ومن غير ما يغيّروا حساب أي يوم متسجّل بالفعل."""


def _set(client, ids):
    return client.patch("/api/medical-officers", json={"officer_ids": ids})


def test_auto_medical_on_a_blank_day(client):
    _set(client, ["OFF-001", "OFF-002"])
    d = client.get("/api/duty/2026-05-01").get_json()
    rows = {r["id"]: r for r in d["rows"]}
    assert rows["OFF-001"]["group"] == "طبية"
    assert rows["OFF-001"]["bucket"] == "موجود"
    assert rows["OFF-002"]["group"] == "طبية"
    assert d["summary"]["طبية"] == {"موجود": 2, "راحة": 0}
    assert d["summary"]["صافي"] == 0
    assert d["summary"]["balanced"] is True


def test_medical_officer_on_leave_shows_as_rest_not_khawarej(client):
    _set(client, ["OFF-001"])
    client.post("/api/leaves", json={
        "person_id": "OFF-001", "type": "أسبوعية",
        "start": "2026-05-02", "end": "2026-05-02"})
    d = client.get("/api/duty/2026-05-02").get_json()
    row = next(r for r in d["rows"] if r["id"] == "OFF-001")
    assert row["group"] == "طبية"
    assert row["bucket"] == "راحة"
    assert d["summary"]["طبية"]["راحة"] == 1
    assert d["summary"]["خوارج"]["راحة"] == 0


def test_explicit_status_overrides_auto_medical_on_blank_day(client):
    """اليوم لسه فاضي كله، لكن الضابط اتحدد له انتداب صريح — الصريح يغلب."""
    _set(client, ["OFF-001"])
    client.put("/api/duty/2026-05-03/OFF-001", json={"items": [], "status": "انتداب"})
    row = next(r for r in client.get("/api/duty/2026-05-03").get_json()["rows"]
               if r["id"] == "OFF-001")
    assert row["group"] == "خوارج" and row["bucket"] == "انتداب"


def test_any_recorded_duty_that_day_disables_auto_fill_for_everyone(client):
    """أول ما يوم يبقى فيه أي تكليف حقيقي مسجّل (لأي حد)، بيبقى يوم "متابَع
    بإيد الموظف" — الافتراضي التلقائي بيتوقف لكل الضباط في نفس اليوم،
    عشان محدش يفاجأ بتغيير حساب يوم هو شخصيًا بيسجّله بنفسه. (تكليف بقايمة
    فاضية مالوش تأثير فعلي — مش بيسجّل حاجة أصلًا — فمش الحالة المقصودة هنا.)"""
    _set(client, ["OFF-001"])
    client.put("/api/duty/2026-05-04/OFF-002", json={
        "items": [{"service_id": "SVC-001", "shift": "صباحية"}]})
    row = next(r for r in client.get("/api/duty/2026-05-04").get_json()["rows"]
               if r["id"] == "OFF-001")
    assert row["group"] == "صافي"


def test_officer_not_on_force_that_day_is_skipped(client):
    """OFF-002 join_date is 2020-01-01 in the fixture; a day before that
    means he wasn't on the force, so he shouldn't appear at all."""
    _set(client, ["OFF-002"])
    d = client.get("/api/duty/2019-01-01").get_json()
    assert all(r["id"] != "OFF-002" for r in d["rows"])


def test_archived_days_are_never_altered_by_the_setting(client):
    """أهم اختبار: تفعيل الميزة على أي يوم متسجّل بالفعل (فيه duties) —
    زي أيام الأرشيف — ميغيرش حسابه خالص، حتى لو ضابط العيادة نفسه مالوش
    تكليف مسجّل فيه يومها."""
    day = "2026-05-05"
    client.put(f"/api/duty/{day}/OFF-002", json={
        "items": [{"service_id": "SVC-001", "shift": "صباحية"}]})
    before = client.get(f"/api/duty/{day}").get_json()
    row_before = next(r for r in before["rows"] if r["id"] == "OFF-001")
    assert row_before["group"] == "صافي"          # مالوش تكليف يومها

    _set(client, ["OFF-001"])                       # فعّل الميزة دلوقتي
    after = client.get(f"/api/duty/{day}").get_json()
    row_after = next(r for r in after["rows"] if r["id"] == "OFF-001")
    assert row_after == row_before, "يوم متسجّل بالفعل لازم يفضل زي ما هو"


def test_set_medical_officers_validates(client):
    assert _set(client, "OFF-001").status_code == 400        # مش list
    assert _set(client, ["OFF-999"]).status_code == 404
    assert _set(client, ["OFF-001", "OFF-001"]).status_code == 200
    assert client.get("/api/medical-officers").status_code == 405  # PATCH only


def test_exposed_in_api_data(client):
    _set(client, ["OFF-001"])
    d = client.get("/api/data").get_json()
    assert d["medical_officers"] == ["OFF-001"]
    assert d["meta"]["medical_badge"]

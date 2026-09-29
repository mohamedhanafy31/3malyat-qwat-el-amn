"""ضباط العيادة الطبية — عمود «الخدمات الطبية» في جدول الإجمالي.

الوورد فيه عمود ثابت للطبية بخانتين (موجود/راحة)، وضابط العيادة بيفضل
فيه حتى وهو في راحة: يومية 31/8 بتكتب «راحة» في خانة الطبية مش في خانة
الخوارج (محمود عبد الله «عمل» → موجود، محمد وليد «راحة» → راحة).

الاكتشاف بقى من مصدرين (`backend/duty.py::summarise`) — عضو في منصب
«طبي» الجماعي في قيادة الإدارة (`PATCH /api/command-groups`، أكتر من
ضابط ممكن يشيلوه في نفس الوقت عكس مدير/وكيل الإدارة)، أو خدمة اليوم
تصنيفها «طبية». التحديد اليدوي القديم لليوم بالذات
(`PUT /api/duty/<day>/<id>` بـ`medical: true`) والفحص على نص المنصب
(`MEDICAL_POSTS`) اتشالوا الاتنين لصالح المنصب الموحّد ده.
"""

MEDICAL = "طبي"


def _set_medical(client, *officer_ids):
    return client.patch("/api/command-groups", json={MEDICAL: list(officer_ids)})


def _row(client, officer_id, day):
    d = client.get(f"/api/duty/{day}").get_json()
    return next(r for r in d["rows"] if r["id"] == officer_id)


def test_medical_officers_fill_the_medical_column(client):
    """أكتر من ضابط ممكن يشيلوا منصب «طبي» في نفس الوقت."""
    _set_medical(client, "OFF-001", "OFF-002")
    d = client.get("/api/duty/2026-05-01").get_json()
    rows = {r["id"]: r for r in d["rows"]}
    assert rows["OFF-001"]["group"] == "طبية" and rows["OFF-001"]["bucket"] == "موجود"
    assert rows["OFF-002"]["group"] == "طبية"
    assert d["summary"]["طبية"] == {"موجود": 2, "راحة": 0}
    assert d["summary"]["صافي"] == 0
    assert d["summary"]["balanced"] is True


def test_the_role_holder_counts_as_medical_on_any_day(client):
    """عكس التحديد اليدوي القديم لليوم بالذات — منصب «طبي» زي مدير/وكيل
    الإدارة، مش حاجة بتتحدد يوم بيوم."""
    _set_medical(client, "OFF-001")
    assert _row(client, "OFF-001", "2026-05-01")["group"] == "طبية"
    assert _row(client, "OFF-001", "2026-05-02")["group"] == "طبية"


def test_medical_officer_on_leave_stays_in_the_medical_column(client):
    """الوورد بيكتب راحته في خانة الطبية مش في خانة الخوارج."""
    _set_medical(client, "OFF-001")
    client.post("/api/leaves", json={
        "person_id": "OFF-001", "type": "أسبوعية",
        "start": "2026-05-02", "end": "2026-05-02"})
    d = client.get("/api/duty/2026-05-02").get_json()
    row = next(r for r in d["rows"] if r["id"] == "OFF-001")
    assert (row["group"], row["bucket"]) == ("طبية", "راحة")
    assert d["summary"]["طبية"]["راحة"] == 1
    assert d["summary"]["خوارج"]["راحة"] == 0


def test_explicit_status_wins_over_the_medical_default(client):
    """حالة مكتوبة بالإيد لليوم ده بالذات بتغلب أي افتراض."""
    _set_medical(client, "OFF-001")
    client.put("/api/duty/2026-05-03/OFF-001", json={"status": "انتداب"})
    row = _row(client, "OFF-001", "2026-05-03")
    assert (row["group"], row["bucket"]) == ("خوارج", "انتداب")


def test_a_service_of_kind_medical_also_counts(client):
    """خدمة تصنيفها «طبية» بتحسب الضابط طبية برضو، حتى لو مش عضو في منصب
    «طبي» أصلًا — زي حد تاني غطّى العيادة يوم بعينه."""
    client.post("/api/assignments/2026-05-06", json={
        "name": "عيادة المعسكر", "kind": "طبية", "officer_ids": ["OFF-002"]})
    assert _row(client, "OFF-002", "2026-05-06")["group"] == "طبية"


def test_changing_the_medical_role_holders_does_not_reach_back_into_a_saved_day(client):
    """عرض محسوب زي مدير/وكيل الإدارة — تغيير أعضاء المنصب النهاردة بيسري
    على كل الأيام (القديمة والجديدة) لأنه مش تكليف مخزّن ليوم بعينه."""
    _set_medical(client, "OFF-001")
    assert _row(client, "OFF-001", "2026-05-04")["group"] == "طبية"

    _set_medical(client, "OFF-002")   # استبدال كامل — OFF-001 مابقاش عضو
    assert _row(client, "OFF-001", "2026-05-04")["group"] != "طبية"
    assert _row(client, "OFF-002", "2026-05-04")["group"] == "طبية"


def test_medical_role_does_not_boost_rank_order(client):
    """عكس مدير/وكيل الإدارة — عضو منصب «طبي» مايتقدّمش في ترتيب أي
    قايمة ضباط، هو مجرد تسمية مش أعلى تنظيميًا."""
    _set_medical(client, "OFF-002")   # OFF-002 نقيب، OFF-001 عقيد في الـfixture
    active = client.get("/api/data").get_json()["officers"]["active"]
    assert [o["id"] for o in active] == ["OFF-001", "OFF-002"]

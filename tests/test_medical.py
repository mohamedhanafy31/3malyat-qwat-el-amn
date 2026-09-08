"""ضباط العيادة الطبية — عمود «الخدمات الطبية» في جدول الإجمالي.

الوورد فيه عمود ثابت للطبية بخانتين (موجود/راحة)، وضابط العيادة بيفضل
فيه حتى وهو في راحة: يومية 31/8 بتكتب «راحة» في خانة الطبية مش في خانة
الخوارج (محمود عبد الله «عمل» → موجود، محمد وليد «راحة» → راحة).

الاكتشاف بقى من **المنصب الفعّال في اليوم ده** (رئيس العيادة الطبية /
انتداب من قطاع الخدمات الطبية) بدل قايمة أيدي ثابتة — القايمة الثابتة
كانت بتطبّق تشكيلة النهاردة على كل الأيام القديمة بأثر رجعي.
"""


def _set(client, ids):
    return client.patch("/api/medical-officers", json={"officer_ids": ids})


def _row(client, officer_id, day):
    d = client.get(f"/api/duty/{day}").get_json()
    return next(r for r in d["rows"] if r["id"] == officer_id)


def test_medical_officers_fill_the_medical_column(client):
    _set(client, ["OFF-001", "OFF-002"])
    d = client.get("/api/duty/2026-05-01").get_json()
    rows = {r["id"]: r for r in d["rows"]}
    assert rows["OFF-001"]["group"] == "طبية" and rows["OFF-001"]["bucket"] == "موجود"
    assert rows["OFF-002"]["group"] == "طبية"
    assert d["summary"]["طبية"] == {"موجود": 2, "راحة": 0}
    assert d["summary"]["صافي"] == 0
    assert d["summary"]["balanced"] is True


def test_medical_officer_on_leave_stays_in_the_medical_column(client):
    """الوورد بيكتب راحته في خانة الطبية مش في خانة الخوارج."""
    _set(client, ["OFF-001"])
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
    _set(client, ["OFF-001"])
    client.put("/api/duty/2026-05-03/OFF-001", json={"status": "انتداب"})
    row = _row(client, "OFF-001", "2026-05-03")
    assert (row["group"], row["bucket"]) == ("خوارج", "انتداب")


def test_medical_post_alone_is_enough(client):
    """من غير ما تحطه في القايمة: المنصب نفسه بيحدد الخانة."""
    client.patch("/api/person/OFF-002", json={"post": "رئيس العيادة الطبية",
                                              "effective_from": "2026-05-04"})
    assert _row(client, "OFF-002", "2026-05-04")["group"] == "طبية"


def test_seconded_from_the_medical_sector_also_counts(client):
    client.patch("/api/person/OFF-002", json={"post": "انتداب من قطاع الخدمات الطبية",
                                              "effective_from": "2026-05-05"})
    assert _row(client, "OFF-002", "2026-05-05")["group"] == "طبية"


def test_a_post_change_does_not_reach_back_into_the_archive(client):
    """المنصب بيتغيّر مع حركة الضباط — الأيام اللي قبل تاريخ السريان
    لازم تفضل بمنصبه القديم، وإلا كل يومية قديمة تتطبع ببيانات النهاردة."""
    client.patch("/api/person/OFF-002", json={"post": "رئيس العيادة الطبية",
                                              "effective_from": "2026-05-10"})
    assert _row(client, "OFF-002", "2026-05-09")["group"] == "صافي"
    assert _row(client, "OFF-002", "2026-05-10")["group"] == "طبية"


def test_medical_list_rejects_unknown_or_archived_officer(client):
    assert _set(client, ["OFF-999"]).status_code == 404


def test_medical_list_is_deduplicated(client):
    out = _set(client, ["OFF-001", "OFF-001", "OFF-002"]).get_json()
    assert out == ["OFF-001", "OFF-002"]

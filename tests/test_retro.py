"""تعديل بأثر رجعي على أيام مقفولة — راحة بتاريخ فات لازم سبب مكتوب،
وبتتسجّل في سجل التغييرات (`backend/retro.py`).

«النهاردة» بتتحرّك بـ`frozen_today` عشان نضمن يوم فعليًا مقفول (زي
`test_day_close.py` بالظبط) — أيام الاختبارات كلها 2026 وأبعد من
«النهاردة» المثبّتة الافتراضية (2019-01-01)، فمن غيرها كل يوم بيبقى
جاي (مفتوح) ومفيش حاجة نختبرها.
"""
CLOSED_DAY = "2026-04-10"     # قبل «النهاردة» بعد ما نحرّكها
TODAY = "2026-04-15"


def _entries(client, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    return client.get(f"/api/changes{'?' + q if q else ''}").get_json()["entries"]


def test_leave_over_a_closed_day_needs_a_reason(client, frozen_today):
    frozen_today(TODAY)
    r = client.post("/api/leaves", json={
        "person_id": "OFF-002", "type": "أسبوعية",
        "start": CLOSED_DAY, "end": CLOSED_DAY})
    assert r.status_code == 409
    body = r.get_json()
    assert body["needs_reason"] is True
    assert body["closed_days"] == [CLOSED_DAY]


def test_leave_over_a_closed_day_succeeds_with_a_reason_and_is_logged(client, frozen_today):
    frozen_today(TODAY)
    r = client.post("/api/leaves", json={
        "person_id": "OFF-002", "type": "أسبوعية",
        "start": CLOSED_DAY, "end": CLOSED_DAY},
        headers={"X-Retro-Reason": "نسيان تسجيل الراحة وقتها"})
    assert r.status_code == 201, r.get_data(as_text=True)

    entries = _entries(client)
    retro = [e for e in entries if e["action"] == "retro"]
    assert len(retro) == 1
    assert retro[0]["reason"] == "نسيان تسجيل الراحة وقتها"
    assert CLOSED_DAY in retro[0]["text"]


def test_a_leave_fully_in_the_future_needs_no_reason(client, frozen_today):
    frozen_today(TODAY)
    r = client.post("/api/leaves", json={
        "person_id": "OFF-002", "type": "أسبوعية",
        "start": "2026-05-01", "end": "2026-05-01"})
    assert r.status_code == 201, r.get_data(as_text=True)
    assert [e for e in _entries(client) if e["action"] == "retro"] == []


def test_editing_a_leave_out_of_a_closed_day_still_needs_a_reason(client, frozen_today):
    """تعديل بيقصّر راحة كانت بتغطي يوم مقفول برضو أثر رجعي — المدى
    القديم مهم برضو مش المدى الجديد بس."""
    frozen_today(TODAY)
    created = client.post("/api/leaves", json={
        "person_id": "OFF-002", "type": "أسبوعية",
        "start": "2026-05-01", "end": "2026-05-01"},
        ).get_json()

    # عدّل المدى بحيث القديم يشمل يوم مقفول (بتعديل الحقلين الاتنين)
    r = client.patch(f"/api/leaves/{created['id']}",
                     json={"start": CLOSED_DAY, "end": CLOSED_DAY})
    assert r.status_code == 409
    assert r.get_json()["needs_reason"] is True


def test_deleting_a_leave_covering_a_closed_day_needs_a_reason(client, frozen_today):
    frozen_today(TODAY)
    created = client.post("/api/leaves", json={
        "person_id": "OFF-002", "type": "أسبوعية",
        "start": CLOSED_DAY, "end": CLOSED_DAY},
        headers={"X-Retro-Reason": "تسجيل أولي"}).get_json()

    r = client.delete(f"/api/leaves/{created['id']}")
    assert r.status_code == 409
    assert r.get_json()["needs_reason"] is True

    r = client.delete(f"/api/leaves/{created['id']}",
                      headers={"X-Retro-Reason": "غلط في التسجيل"})
    assert r.status_code == 200


# ---------- نفس المبدأ على التحاق الفرقة ----------

def test_course_term_over_a_closed_day_needs_a_reason(client, frozen_today):
    frozen_today(TODAY)
    course = client.post("/api/courses", json={"name": "فرقة اختبار"}).get_json()
    r = client.post("/api/course-terms", json={
        "course_id": course["id"], "officer_id": "OFF-002",
        "start": CLOSED_DAY, "end": CLOSED_DAY})
    assert r.status_code == 409
    assert r.get_json()["needs_reason"] is True

    r = client.post("/api/course-terms", json={
        "course_id": course["id"], "officer_id": "OFF-002",
        "start": CLOSED_DAY, "end": CLOSED_DAY},
        headers={"X-Retro-Reason": "سجل ورقي وصل متأخر"})
    assert r.status_code == 201, r.get_data(as_text=True)
    assert any(e["action"] == "retro" and e["entity"] == "course_term"
               for e in _entries(client))


# ---------- الكشف الشهري — سبب واحد للكشف كله ----------

def test_monthly_roster_over_a_closed_day_needs_one_reason_for_the_batch(client, frozen_today):
    frozen_today(TODAY)
    client.patch("/api/person/OFF-001", json={"rest_system": "شهرية"})
    r = client.post("/api/leaves/monthly", json={
        "entries": [{"officer_id": "OFF-001", "start": CLOSED_DAY}]})
    assert r.status_code == 409
    assert r.get_json()["needs_reason"] is True

    r = client.post("/api/leaves/monthly", json={
        "entries": [{"officer_id": "OFF-001", "start": CLOSED_DAY}]},
        headers={"X-Retro-Reason": "كشف وصل متأخر من المديرية"})
    assert r.status_code == 200
    body = r.get_json()
    assert len(body["created"]) == 1

    assert any(e["action"] == "retro" and e["entity"] == "leave" for e in _entries(client))
    # كل راحة اتسجّلت من الكشف بتتسجّل «create» برضو زي أي راحة عادية
    assert any(e["action"] == "create" and e["entity"] == "leave" for e in _entries(client))


def test_monthly_roster_fully_in_the_future_needs_no_reason(client, frozen_today):
    frozen_today(TODAY)
    client.patch("/api/person/OFF-001", json={"rest_system": "شهرية"})
    r = client.post("/api/leaves/monthly", json={
        "entries": [{"officer_id": "OFF-001", "start": "2026-06-01"}]})
    assert r.status_code == 200
    assert len(r.get_json()["created"]) == 1


# ---------- سريان تعديل بيانات الضابط بتاريخ فات ----------

def test_backdated_rank_change_over_a_closed_day_needs_a_reason(client, frozen_today):
    """المنصب سريانه من يوم مقفول بالفعل — أيامه دلوقتي هتتطبع برتبة/منصب
    جديد كان مختلف وقت التأكيد."""
    frozen_today(TODAY)
    r = client.patch("/api/person/OFF-001",
                     json={"role": "مقدم", "effective_from": CLOSED_DAY})
    assert r.status_code == 409
    assert r.get_json()["needs_reason"] is True


def test_backdated_rank_change_succeeds_with_a_reason_and_is_logged(client, frozen_today):
    frozen_today(TODAY)
    r = client.patch("/api/person/OFF-001",
                     json={"role": "مقدم", "effective_from": CLOSED_DAY},
                     headers={"X-Retro-Reason": "تصحيح تاريخ الترقية"})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert any(e["action"] == "retro" and e["entity"] == "person" for e in _entries(client))


def test_effective_from_today_or_later_needs_no_reason(client, frozen_today):
    frozen_today(TODAY)
    r = client.patch("/api/person/OFF-001",
                     json={"role": "مقدم", "effective_from": TODAY})
    assert r.status_code == 200


# ---------- الحذف النهائي ----------

def test_permanent_delete_over_closed_days_needs_a_reason(client, frozen_today):
    frozen_today(TODAY)
    client.post(f"/api/assignments/{CLOSED_DAY}", json={
        "name": "خدمة اختبار", "kind": "خارجية", "officer_ids": ["OFF-001"]})
    client.post("/api/person/OFF-001/remove",
               json={"leave_date": "2026-04-14", "cleanup": True})

    r = client.delete("/api/person/OFF-001")
    assert r.status_code == 409
    assert r.get_json()["needs_reason"] is True

    r = client.delete("/api/person/OFF-001", headers={"X-Retro-Reason": "تنظيف الأرشيف"})
    assert r.status_code == 200, r.get_data(as_text=True)
    entries = _entries(client)
    assert any(e["action"] == "delete" and e["entity"] == "person" for e in entries)
    assert any(e["action"] == "retro" and e["entity"] == "person" for e in entries)


def test_permanent_delete_with_no_closed_day_activity_needs_no_reason(client, frozen_today):
    frozen_today(TODAY)
    client.post("/api/person/OFF-002/remove", json={"leave_date": "2026-06-01"})
    r = client.delete("/api/person/OFF-002")
    assert r.status_code == 200, r.get_data(as_text=True)
    assert any(e["action"] == "delete" and e["entity"] == "person" for e in _entries(client))

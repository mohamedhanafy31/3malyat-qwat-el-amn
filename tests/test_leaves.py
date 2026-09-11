import json


def test_add_leave_success(client):
    r = client.post("/api/leaves", json={
        "person_id": "OFF-002", "type": "أسبوعية",
        "start": "2026-02-01", "end": "2026-02-01",
    })
    assert r.status_code == 201
    assert r.get_json()["id"] == "LV-002"


def test_overlap_rejected(client):
    r = client.post("/api/leaves", json={
        "person_id": "OFF-001", "type": "أسبوعية",
        "start": "2026-01-10", "end": "2026-01-10",
    })
    assert r.status_code == 409


def test_invalid_type_rejected(client):
    r = client.post("/api/leaves", json={
        "person_id": "OFF-002", "type": "نوع غير موجود",
        "start": "2026-02-01", "end": "2026-02-01",
    })
    assert r.status_code == 400


def test_source_field_preserved_on_edit(client, data_file):
    r = client.patch("/api/leaves/LV-001", json={"note": "تعديل تجريبي"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["source"] == "من الأرشيف"
    assert body["note"] == "تعديل تجريبي"

    saved = json.loads(data_file.read_text(encoding="utf-8"))
    lv = next(l for l in saved["leaves"] if l["id"] == "LV-001")
    assert lv["source"] == "من الأرشيف"


def test_non_dict_json_payload_returns_400_not_500(client):
    """قبل الإصلاح: get_json(silent=True) or {} كان بيسيب array زي ما هو
    (truthy)، فأي .get() بعدها كان بيرمي 500 بدل خطأ تحقق نظيف."""
    r = client.post("/api/leaves", json=[1, 2, 3])
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_delete_nonexistent_leave_404(client):
    assert client.delete("/api/leaves/LV-999").status_code == 404


def test_restore_person_keeps_old_leaves_on_the_archived_record(client):
    """الاستعادة بتفتح **فترة خدمة جديدة** تاريخ انضمامها النهاردة، فالراحات
    القديمة بتفضل على سجل الأرشيف اللي حصلت فيه.

    قبل كده كانت بتتنقل للسجل الجديد، وده كان بيخلّف راحات تاريخها قبل تاريخ
    الانضمام المسجّل (وبيفضّي تاريخ سجل الأرشيف بالكامل)."""
    r_lv = client.post("/api/leaves", json={
        "person_id": "OFF-002", "type": "أسبوعية",
        "start": "2026-05-01", "end": "2026-05-02"
    })
    assert r_lv.status_code == 201
    lv_id = r_lv.get_json()["id"]

    r_arch = client.post("/api/person/OFF-002/remove",
                         json={"reason": "إنهاء خدمة", "leave_date": "2026-05-03"})
    assert r_arch.status_code == 200

    r_rest = client.post("/api/person/OFF-002/restore")
    assert r_rest.status_code == 201
    restored = r_rest.get_json()
    restored_id = restored["id"]

    assert restored_id != "OFF-002"                     # معرّف جديد مايتكررش
    assert restored["previous_archive_id"] == "OFF-002"  # الرابط بالسجل القديم

    from backend.store import load_data
    lv_entry = next(l for l in load_data()["leaves"] if l["id"] == lv_id)
    assert lv_entry["person_id"] == "OFF-002"
    # ومفيش راحة سابقة لتاريخ انضمام السجل الجديد
    assert lv_entry["start"] < restored["join_date"]


def test_restored_person_gets_a_fresh_unused_id(client):
    """معرّف الشخص كان `تاريخ-اليوم + رقم الأقدمية` وفحص التكرار على القوة بس،
    فضابط متأرشف وبديله بنفس رقم الأقدمية في نفس اليوم كانوا بياخدوا نفس الـid
    بالظبط — وحذف سجل الأرشيف كان بيمسح راحات السجل النشط معاه."""
    body = {"name": "ضابط", "code": "DUP-1", "phone": "0100",
            "join_date": "2026-01-01", "type": "officer", "role": "نقيب"}
    first = client.post("/api/person", json=body)
    assert first.status_code == 201
    first_id = first.get_json()["id"]

    assert client.post(f"/api/person/{first_id}/remove", json={}).status_code == 200

    second = client.post("/api/person", json=body)
    assert second.status_code == 201
    assert second.get_json()["id"] != first_id


def test_leaves_stats_filtering(client):
    r = client.get("/api/leaves/stats?type=أسبوعية")
    assert r.status_code == 200
    res = r.get_json()
    assert "summary" in res
    assert "meta_options" in res
    assert res["by_type"].get("أسبوعية", 0) > 0
    # All counted leaves must be of type "أسبوعية"
    assert res["summary"]["total"] == res["by_type"].get("أسبوعية", 0)


def test_leaves_stats_returns_only_what_the_page_draws(client):
    """صفحة الإحصائيات للضباط، وكل مفتاح راجع منها له رسم في الواجهة.

    الحقول اللي كانت بتتحسب وماحدش بيقراها (تزامن الراحات، الالتزام بالكشف
    الشهري، مقارنة ضباط/أفراد) اتشالت — نص زمن الدالة كان رايح فيها."""
    res = client.get("/api/leaves/stats").get_json()
    assert set(res) == {"summary", "by_type", "by_month", "by_weekday",
                        "duration_buckets", "status_counts", "cumulative",
                        "top_officers", "meta_options"}
    s = res["summary"]
    assert s["total"] == sum(res["by_type"].values())
    assert s["total"] == sum(res["status_counts"].values())
    assert s["current"] == res["status_counts"]["جارية"]


def test_leaves_stats_weekday_matches_the_real_calendar(client):
    """توزيع الأيام كان مزاح يوم كامل: القايمة كانت بادئة بـ«الأحد» في
    الإندكس صفر بينما date.weekday() بيبدأ بالاثنين."""
    from datetime import date
    names = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
    leaves = client.get("/api/bootstrap/leaves").get_json()["leaves"]
    expected = {}
    for lv in leaves:
        key = names[date.fromisoformat(lv["start"]).weekday()]
        expected[key] = expected.get(key, 0) + 1
    assert client.get("/api/leaves/stats").get_json()["by_weekday"] == expected


def test_monthly_roster_lists_only_monthly_and_half_monthly_officers(client):
    """المفتاح لازم يكون "roster" مش "officers" — core.js's paintNavCounts()
    بتفترض إن أي مفتاح "officers" شكله {active, archive}، فقايمة مسطّحة
    باسم "officers" كانت بتوقّع bootstrap() كله بالسكوت في المتصفح."""
    client.patch("/api/person/OFF-001", json={"rest_system": "شهرية"})
    out = client.get("/api/bootstrap/leaves_monthly").get_json()
    assert "officers" not in out
    ids = {o["id"] for o in out["roster"]}
    assert ids == {"OFF-001"}
    assert out["roster"][0]["status"] == "due"
    assert out["roster"][0]["current"] is None


def test_monthly_roster_create_uses_rest_system_and_duration(client):
    client.patch("/api/person/OFF-001", json={"rest_system": "شهرية"})
    r = client.post("/api/leaves/monthly", json={
        "entries": [{"officer_id": "OFF-001", "start": "2030-06-01"}]})
    assert r.status_code == 200
    body = r.get_json()
    assert len(body["created"]) == 1 and not body["errors"]
    lv = body["created"][0]
    assert lv["type"] == "شهرية" and lv["start"] == "2030-06-01" and lv["end"] == "2030-06-07"

    out = client.get("/api/bootstrap/leaves_monthly").get_json()
    row = out["roster"][0]
    assert row["status"] == "upcoming"
    assert row["current"] == {"start": "2030-06-01", "end": "2030-06-07"}


def test_monthly_roster_partial_failure_does_not_block_other_rows(client):
    client.patch("/api/person/OFF-001", json={"rest_system": "شهرية"})
    r = client.post("/api/leaves/monthly", json={"entries": [
        {"officer_id": "OFF-001", "start": "2030-06-01"},
        {"officer_id": "OFF-999", "start": "2030-06-01"},
    ]})
    body = r.get_json()
    assert len(body["created"]) == 1
    assert len(body["errors"]) == 1
    assert body["errors"][0]["officer_id"] == "OFF-999"


def test_monthly_roster_overlap_rejected(client):
    client.patch("/api/person/OFF-001", json={"rest_system": "شهرية"})
    client.post("/api/leaves/monthly",
                json={"entries": [{"officer_id": "OFF-001", "start": "2030-06-01"}]})
    r = client.post("/api/leaves/monthly",
                     json={"entries": [{"officer_id": "OFF-001", "start": "2030-06-03"}]})
    body = r.get_json()
    assert not body["created"]
    assert "متداخلة" in body["errors"][0]["error"]




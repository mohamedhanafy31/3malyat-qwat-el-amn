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


def test_restore_person_transfers_leaves(client):
    # Add a leave for OFF-002
    r_lv = client.post("/api/leaves", json={
        "person_id": "OFF-002", "type": "أسبوعية",
        "start": "2026-05-01", "end": "2026-05-02"
    })
    assert r_lv.status_code == 201
    lv_id = r_lv.get_json()["id"]

    # Archive OFF-002 via /remove endpoint
    r_arch = client.post("/api/person/OFF-002/remove", json={"reason": "إنهاء خدمة", "leave_date": "2026-05-03"})
    assert r_arch.status_code == 200


    # Restore OFF-002
    r_rest = client.post("/api/person/OFF-002/restore")
    assert r_rest.status_code == 201
    restored_id = r_rest.get_json()["id"]

    # Check that leave's person_id is updated to restored_id
    from backend.store import load_data
    leaves = load_data()["leaves"]
    lv_entry = next(l for l in leaves if l["id"] == lv_id)
    assert lv_entry["person_id"] == restored_id


def test_leaves_stats_filtering(client):
    r = client.get("/api/leaves/stats?type=أسبوعية")
    assert r.status_code == 200
    res = r.get_json()
    assert "summary" in res
    assert "meta_options" in res
    assert res["by_type"].get("أسبوعية", 0) > 0
    # All counted leaves must be of type "أسبوعية"
    assert res["summary"]["total"] == res["by_type"].get("أسبوعية", 0)


def test_leaves_stats_category_filter_matches_real_officers(client):
    """قبل الإصلاح: officer_ids كانت بتتحسب من data.get("officers", [])
    كأنها قايمة مسطّحة، بينما هي {"active":[...], "archive":[...]} —
    فأي فلترة بـcategory=officers كانت بترجع صفر دايمًا."""
    total = client.get("/api/leaves/stats").get_json()["summary"]["total"]
    officers_total = client.get("/api/leaves/stats?category=officers").get_json()["summary"]["total"]
    personnel_total = client.get("/api/leaves/stats?category=personnel").get_json()["summary"]["total"]
    assert officers_total > 0
    assert officers_total + personnel_total == total


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




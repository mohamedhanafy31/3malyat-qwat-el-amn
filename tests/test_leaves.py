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



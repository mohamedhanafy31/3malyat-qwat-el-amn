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
    r = client.delete("/api/leaves/LV-999")
    assert r.status_code == 404

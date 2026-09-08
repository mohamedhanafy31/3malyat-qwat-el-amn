import json


def test_get_board_does_not_write(client, data_file):
    before = data_file.read_text(encoding="utf-8")
    r = client.get("/api/board/2026-03-01")
    assert r.status_code == 200
    after = data_file.read_text(encoding="utf-8")
    assert before == after, "GET يجب ألا يعدّل data.json خالص (idempotent read)"


def test_add_edit_delete_entry_round_trip(client):
    r = client.post("/api/board/2026-03-01/entries", json={
        "service": "خدمة اختبار", "category": "الخدمات الطارئة",
    })
    assert r.status_code == 201
    entry_id = r.get_json()["id"]

    r2 = client.patch(f"/api/board/2026-03-01/entries/{entry_id}", json={"note": "ملاحظة"})
    assert r2.status_code == 200
    assert r2.get_json()["note"] == "ملاحظة"

    r3 = client.delete(f"/api/board/2026-03-01/entries/{entry_id}")
    assert r3.status_code == 200

    r4 = client.delete(f"/api/board/2026-03-01/entries/{entry_id}")
    assert r4.status_code == 404


def test_entries_get_unique_sequential_ids(client):
    ids = []
    for _ in range(3):
        r = client.post("/api/board/2026-03-02/entries", json={
            "service": "خدمة", "category": "الخدمات الطارئة",
        })
        ids.append(r.get_json()["id"])
    assert len(set(ids)) == 3


def test_single_write_per_mutating_request(client, monkeypatch):
    """قبل الإصلاح: أول فتح ليوم جديد جوه add_board_entry كان بيسبب حفظتين
    (واحدة جوه get_day_services وواحدة في نهاية الراوت) بدل حفظة واحدة."""
    from backend import store
    calls = []
    orig = store._write
    def counting(data):
        calls.append(1)
        orig(data)
    monkeypatch.setattr(store, "_write", counting)

    r = client.post("/api/board/2026-03-03/entries", json={
        "service": "خدمة", "category": "الخدمات الطارئة",
    })
    assert r.status_code == 201
    assert len(calls) == 1


def test_unknown_day_entry_404(client):
    r = client.patch("/api/board/2026-03-01/entries/DS-9999", json={"note": "x"})
    assert r.status_code == 404

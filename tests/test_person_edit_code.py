"""تعديل شخص على القوة مع بيانات قديمة فيها رقم أقدمية مكرر.

السبب: `edit_person` كان بيرفض أي تعديل لو فيه سجل نشط تاني بنفس الرقم،
حتى لو الرقم ما اتغيّرش. دلوقتي الرفض بس لما الرقم **يتغيّر** لرقم تاني.
"""
import json


def _with_legacy_duplicate(data_file):
    data = json.loads(data_file.read_text())
    data["officers"][1]["code"] = data["officers"][0]["code"]     # OFF-001 و OFF-002 نفس الرقم
    data_file.write_text(json.dumps(data, ensure_ascii=False))


def _officers(client):
    return client.get("/api/bootstrap/officers").get_json()["officers"]["active"]


def test_unchanged_legacy_duplicate_code_can_be_edited_in_place(client, data_file):
    _with_legacy_duplicate(data_file)
    before = len(_officers(client))

    r = client.patch("/api/person/OFF-002", json={
        "name": "محمود علي المعدّل", "code": "1", "phone": "0101"})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["id"] == "OFF-002"

    after = _officers(client)
    assert len(after) == before
    row = next(o for o in after if o["id"] == "OFF-002")
    assert row["name"] == "محمود علي المعدّل"
    assert row["code"] == "1"


def test_changing_code_to_another_active_code_is_rejected(client, data_file):
    r = client.patch("/api/person/OFF-002", json={"code": "1"})
    assert r.status_code == 409
    row = next(o for o in _officers(client) if o["id"] == "OFF-002")
    assert row["code"] == "2"


def test_changing_code_to_a_free_code_is_accepted(client, data_file):
    r = client.patch("/api/person/OFF-002", json={"code": "77"})
    assert r.status_code == 200
    assert next(o for o in _officers(client) if o["id"] == "OFF-002")["code"] == "77"


def test_new_officer_with_duplicate_code_is_rejected(client, data_file):
    before = len(_officers(client))
    r = client.post("/api/person", json={
        "name": "ضابط جديد", "code": "1", "phone": "0102",
        "join_date": "2026-01-01", "type": "officer", "role": "نقيب"})
    assert r.status_code == 409
    assert len(_officers(client)) == before

from io import BytesIO

from docx import Document

from backend.models import Officer
from backend.people_export import build_docx
from backend.utils import MAX_LEN


def _officer_payload(**extra):
    return {"type": "officer", "name": "أحمد علي", "role": "رائد",
            "code": "2026001", "phone": "01012345678",
            "join_date": "2026-01-01", "section": "القوة", **extra}


def test_officer_address_model_round_trip_and_legacy_default():
    legacy = {"id": "OFF-1", "name": "أحمد", "code": "1", "role": "رائد",
              "join_date": "2026-01-01"}
    old = Officer.from_dict(legacy)
    assert old.address == ""
    assert old.as_dict() == legacy

    current = {**legacy, "address": "شارع النيل"}
    model = Officer.from_dict(current)
    assert model.address == "شارع النيل"
    assert model.as_dict() == current
    assert not model.validate()


def test_officer_address_is_created_updated_preserved_and_returned(client):
    response = client.post("/api/person", json=_officer_payload(address="  شارع النيل  "))
    assert response.status_code == 201
    officer_id = response.json["id"]
    assert response.json["address"] == "شارع النيل"

    updated = client.patch(f"/api/person/{officer_id}", json={"post": "العمليات"})
    assert updated.status_code == 200
    assert updated.json["address"] == "شارع النيل"

    bootstrap = client.get("/api/bootstrap/officers").json
    assert next(o for o in bootstrap["officers"]["active"] if o["id"] == officer_id)["address"] == "شارع النيل"

    changed = client.patch(f"/api/person/{officer_id}", json={"address": "  مساكن المعسكر  "})
    assert changed.status_code == 200
    assert changed.json["address"] == "مساكن المعسكر"


def test_officer_address_length_is_checked_on_create_and_update(client):
    too_long = "ع" * (MAX_LEN["address"] + 1)
    created = client.post("/api/person", json=_officer_payload(address=too_long))
    assert created.status_code == 400
    assert "أطول من الحد المسموح" in created.json["error"]

    created = client.post("/api/person", json=_officer_payload())
    officer_id = created.json["id"]
    updated = client.patch(f"/api/person/{officer_id}", json={"address": too_long})
    assert updated.status_code == 400
    assert "أطول من الحد المسموح" in updated.json["error"]


def test_officer_export_includes_address_column_and_value():
    content = build_docx({"officers": [{"id": "OFF-1", "role": "رائد", "name": "أحمد",
                                         "code": "1", "address": "شارع النيل",
                                         "status": "active"}],
                          "command": {}}, "officers", "2026-11-02")
    table = next(t for t in Document(BytesIO(content)).tables
                 if t.rows and t.rows[0].cells[0].text == "م")
    headers = [cell.text for cell in table.rows[0].cells]
    assert headers == ["م", "الرتبة", "الاسم", "الأقدمية", "العمل المسند",
                       "العنوان", "نظام الراحة", "الهاتف"]
    assert "شارع النيل" in [cell.text for cell in table.rows[1].cells]

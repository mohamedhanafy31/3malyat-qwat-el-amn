def _officer(client, section="الحراسات المشددة", **extra):
    body = {
        "name": "ضابط قسم",
        "code": "9001",
        "phone": "01012345678",
        "join_date": "2026-01-01",
        "type": "officer",
        "role": "نقيب",
        "section": section,
        **extra,
    }
    return client.post("/api/person", json=body)


def test_new_officer_can_be_added_to_a_new_section_and_section_is_suggested(client):
    created = _officer(client, "قسم العمليات الجديد", new_section=True)
    assert created.status_code == 201, created.get_json()
    assert created.get_json()["section"] == "قسم العمليات الجديد"

    meta = client.get("/api/bootstrap/officers").get_json()["meta"]
    assert "قسم العمليات الجديد" in meta["officer_sections"]


def test_unknown_section_requires_explicit_new_section_flag(client):
    response = _officer(client, "قسم غير معتمد")
    assert response.status_code == 400
    assert "قسم جديد" in response.get_json()["error"]

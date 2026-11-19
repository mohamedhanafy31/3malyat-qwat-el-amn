def test_outsiders_page_and_register_include_status_and_leave_records(client):
    page = client.get("/outsiders")
    assert page.status_code == 200
    assert "قسم الخوارج" in page.get_data(as_text=True)
    assert "outsiders.js" in page.get_data(as_text=True)

    started = client.put("/api/duty/2026-05-01/OFF-002",
                         json={"status": "غياب", "status_start_time": "08:35"})
    assert started.status_code == 200, started.get_json()
    body = client.get("/api/bootstrap/outsiders").get_json()
    absence = next(row for row in body["outsiders"]
                   if row.get("person_id") == "OFF-002" and row.get("status") == "غياب")
    leave = next(row for row in body["outsiders"]
                 if row.get("id") == "LV-001")
    assert absence["record_kind"] == "status"
    assert absence["duration"]["precision"] == "minutes"
    assert absence["start_time"] == "08:35"
    assert leave["record_kind"] == "leave"
    assert leave["duration"]["text"] == "1 يوم"


def test_outsiders_register_includes_course_terms(client, data_file):
    import json

    data = json.loads(data_file.read_text())
    data["courses"] = [{"id": "CRS-001", "name": "فرقة الحراسات",
                        "kind": "تخصصية", "place": "مركز التدريب"}]
    data["course_terms"] = [{"id": "CT-0001", "course_id": "CRS-001",
                             "officer_id": "OFF-002", "start": "2026-05-01",
                             "end": "2026-05-03", "note": ""}]
    data_file.write_text(json.dumps(data, ensure_ascii=False))

    rows = client.get("/api/bootstrap/outsiders").get_json()["outsiders"]
    course = next(row for row in rows if row.get("id") == "CT-0001")
    assert course["status"] == "فرقة"
    assert course["title"] == "فرقة الحراسات"
    assert course["duration"]["text"] == "3 يوم"

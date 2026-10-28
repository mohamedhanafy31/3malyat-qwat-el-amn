"""تشغيل ضباط البحث وحالة الطبي من نافذة «الحالة» في يومية الضباط."""
import io
import json

from docx import Document

from backend.duty_export import _daily_text


def _set_groups(data_file, *, search=(), medical=()):
    data = json.loads(data_file.read_text())
    data["command_groups"] = {"بحث": list(search), "طبي": list(medical)}
    data.pop("command_history", None)
    data_file.write_text(json.dumps(data, ensure_ascii=False))


def _row(client, officer_id, day):
    response = client.get(f"/api/duty/{day}")
    assert response.status_code == 200
    return next(row for row in response.get_json()["rows"] if row["id"] == officer_id)


def _export_text(client, day, officer_name):
    response = client.get(f"/api/duty/{day}/export.docx")
    assert response.status_code == 200
    document = Document(io.BytesIO(response.data))
    for row in document.tables[0].rows:
        if any(cell.text == officer_name for cell in row.cells):
            return " | ".join(cell.text for cell in row.cells)
    raise AssertionError(f"officer row not found in export: {officer_name}")


def test_research_service_is_daily_and_can_be_saved_then_cleared(client, data_file):
    _set_groups(data_file, search=["OFF-001"])
    day = "2026-03-01"

    blank = _row(client, "OFF-001", day)
    assert blank["research"] is True
    assert blank["text"] == "تشغيله ـــــــــــــــــــــ"
    assert _daily_text(blank) == "تشغيله ـــــــــــــــــــــ"
    assert "تشغيله ـــــــــــــــــــــ" in _export_text(client, day, "أحمد محمد")

    saved = client.put(f"/api/duty/{day}/OFF-001", json={
        "research_service": "متابعة تحريات",
        "research_time": "08:15",
    })
    assert saved.status_code == 200
    assigned = next(row for row in saved.get_json()["rows"] if row["id"] == "OFF-001")
    assert assigned["research_service"] == "متابعة تحريات"
    assert assigned["research_time"] == "8:15ص"
    assert assigned["text"] == "متابعة تحريات — انتظام 8:15ص"
    assert _daily_text(assigned) == "متابعة تحريات — انتظام 8:15ص"
    assert "متابعة تحريات — انتظام 8:15ص" in _export_text(client, day, "أحمد محمد")

    # خدمة البحث لا تتوارث حتى لو اليوم التالي مفيهوش ملف يوم أصلًا.
    assert _row(client, "OFF-001", "2026-03-02")["text"] == "تشغيله ـــــــــــــــــــــ"

    cleared = client.put(f"/api/duty/{day}/OFF-001", json={
        "research_service": "", "research_time": "",
    })
    assert cleared.status_code == 200
    cleared_row = next(row for row in cleared.get_json()["rows"] if row["id"] == "OFF-001")
    assert cleared_row["research_service"] == ""
    assert cleared_row["research_time"] == ""
    assert cleared_row["text"] == "تشغيله ـــــــــــــــــــــ"


def test_medical_state_inherits_until_an_explicit_change(client, data_file):
    _set_groups(data_file, medical=["OFF-002"])

    first = client.put("/api/duty/2026-03-01/OFF-002", json={"medical_state": "راحة"})
    assert first.status_code == 200
    day3 = _row(client, "OFF-002", "2026-03-03")
    assert (day3["medical_state"], day3["medical_state_from"]) == ("راحة", "2026-03-01")
    assert day3["text"] == "راحة"
    assert day3["group"] == "طبية" and day3["bucket"] == "راحة"
    assert day3["medical_state"] == _row(client, "OFF-002", "2026-03-02")["medical_state"]

    changed = client.put("/api/duty/2026-03-04/OFF-002", json={
        "medical_state": "انتداب", "medical_deputation_text": "مستشفى السويس العام",
    })
    assert changed.status_code == 200
    day5 = _row(client, "OFF-002", "2026-03-05")
    assert (day5["medical_state"], day5["medical_state_from"]) == ("انتداب", "2026-03-04")
    assert day5["medical_deputation_text"] == "مستشفى السويس العام"
    assert day5["text"] == "مستشفى السويس العام"
    assert (day5["group"], day5["bucket"]) == ("خوارج", "انتداب")
    assert _daily_text(day5) == "مستشفى السويس العام"


def test_medical_summary_counts_rest_and_deputation(client, data_file):
    _set_groups(data_file, medical=["OFF-002"])
    assert client.put("/api/duty/2026-03-01/OFF-002",
                      json={"medical_state": "راحة"}).status_code == 200
    rest = client.get("/api/duty/2026-03-03").get_json()["summary"]
    assert rest["طبية"] == {"موجود": 0, "راحة": 1}
    assert rest["خوارج"]["انتداب"] == 0

    assert client.put("/api/duty/2026-03-04/OFF-002", json={
        "medical_state": "انتداب", "medical_deputation_text": "",
    }).status_code == 200
    deputed = client.get("/api/duty/2026-03-05").get_json()
    assert deputed["summary"]["طبية"] == {"موجود": 0, "راحة": 0}
    assert deputed["summary"]["خوارج"]["انتداب"] == 1
    row = next(item for item in deputed["rows"] if item["id"] == "OFF-002")
    assert row["text"] == "انتداب"


def test_real_leave_overrides_inherited_medical_deputation(client, data_file):
    _set_groups(data_file, medical=["OFF-001"])
    assert client.put("/api/duty/2026-01-09/OFF-001", json={
        "medical_state": "انتداب", "medical_deputation_text": "تشغيل خارجي",
    }).status_code == 200

    row = _row(client, "OFF-001", "2026-01-10")
    assert row["medical_state"] == "انتداب"       # القيمة موروثة، لكن الإجازة أقوى
    assert row["leave"]["raw_type"] == "أسبوعية"
    assert (row["group"], row["bucket"]) == ("طبية", "راحة")
    assert row["text"] == ""
    assert _daily_text(row) == row["leave"]["type"]


def test_special_fields_are_rejected_for_officers_outside_the_groups(client):
    research = client.put("/api/duty/2026-03-01/OFF-001", json={
        "research_service": "خدمة", "research_time": "8ص",
    })
    assert research.status_code == 400
    assert "ليس ضمن مجموعة البحث" in research.get_json()["error"]

    medical = client.put("/api/duty/2026-03-01/OFF-002", json={"medical_state": "راحة"})
    assert medical.status_code == 400
    assert "ليس ضمن مجموعة الطبي" in medical.get_json()["error"]

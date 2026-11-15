"""إعلان الضابط منفصل عن تشغيله، ومحدد بيوم اليومية."""

import io

from docx import Document

from backend.assignments import set_officer_state
from backend.models.day import OfficerDayState

DAY = "2026-03-01"


def _row(client, day=DAY):
    return next(row for row in client.get(f"/api/duty/{day}").get_json()["rows"]
                if row["id"] == "OFF-001")


def _doc_text(response):
    doc = Document(io.BytesIO(response.data))
    return "\n".join([p.text for p in doc.paragraphs] + [
        cell.text for table in doc.tables for row in table.rows for cell in row.cells])


def test_announced_is_stored_even_when_it_is_the_only_state():
    state = OfficerDayState(announced="phone")
    assert state.announced == "phone"
    assert state.empty is False  # لو اتعامل كفاضي الريبو بيمسح الإعلان عند الحفظ
    data = {}
    set_officer_state(data, DAY, "OFF-001", announced="phone")
    assert data["day_officers"][DAY]["OFF-001"]["announced"] == "phone"
    assert OfficerDayState(**data["day_officers"][DAY]["OFF-001"]).empty is False


def test_toggle_preserves_other_state_and_reports_count_and_audit(client):
    client.put(f"/api/duty/{DAY}/OFF-001", json={"note": "متابعة", "status": "غياب"})
    response = client.put(f"/api/duty/{DAY}/OFF-001", json={"announced": "phone"})
    assert response.status_code == 200
    row = _row(client)
    assert row["announced"] == "phone"
    assert row["note"] == "متابعة" and row["status"] == "غياب"
    payload = response.get_json()
    assert (payload["announced_count"], payload["announced_phone"],
            payload["announced_message"], payload["total"]) == (1, 1, 0, 2)
    entries = client.get("/api/changes", query_string={"entity": "officer_state", "entity_id": "OFF-001"}).get_json()["entries"]
    entry = next(item for item in entries if "إعلان الضابط" in item["text"])
    assert f"إعلان الضابط {row['name']} تليفونيًا" in entry["text"]
    count = len(entries)
    client.put(f"/api/duty/{DAY}/OFF-001", json={"announced": "phone"})
    assert len(client.get("/api/changes", query_string={"entity": "officer_state", "entity_id": "OFF-001"}).get_json()["entries"]) == count
    client.put(f"/api/duty/{DAY}/OFF-001", json={"announced": ""})
    assert _row(client)["announced"] == ""
    entries = client.get("/api/changes", query_string={"entity": "officer_state", "entity_id": "OFF-001"}).get_json()["entries"]
    assert any("إلغاء إعلان الضابط" in e["text"] for e in entries)


def test_phone_to_message_change_logs_method_and_counts(client):
    client.put(f"/api/duty/{DAY}/OFF-001", json={"announced": "phone"})
    response = client.put(f"/api/duty/{DAY}/OFF-001", json={"announced": "message"})
    assert response.status_code == 200
    payload = response.get_json()
    assert _row(client)["announced"] == "message"
    assert (payload["announced_count"], payload["announced_phone"],
            payload["announced_message"]) == (1, 0, 1)
    entries = client.get("/api/changes", query_string={"entity": "officer_state", "entity_id": "OFF-001"}).get_json()["entries"]
    assert any(f"إعلان الضابط {_row(client)['name']} برسالة" in e["text"] for e in entries)


def test_invalid_announcement_method_is_rejected(client):
    for value in ("carrier-pigeon", True, False):
        response = client.put(f"/api/duty/{DAY}/OFF-001", json={"announced": value})
        assert response.status_code == 400
        assert "طريقة إعلان الضابط" in response.get_json()["error"]
    assert _row(client)["announced"] == ""


def test_announcement_is_not_carried_and_clear_state_removes_it(client):
    client.put(f"/api/duty/{DAY}/OFF-001", json={"announced": "message"})
    assert _row(client, "2026-03-02")["announced"] == ""
    client.delete(f"/api/duty/{DAY}/OFF-001")
    assert _row(client)["announced"] == ""


def test_closed_day_rejects_announcement(client):
    client.post(f"/api/day-status/{DAY}/close", json={})
    assert client.put(f"/api/duty/{DAY}/OFF-001", json={"announced": "phone"}).status_code == 409


def test_announcement_does_not_change_board_or_duty_export_text(client):
    before = _doc_text(client.get(f"/api/duty/{DAY}/export.docx"))
    board_before = client.get(f"/api/board/{DAY}").get_json()
    client.put(f"/api/duty/{DAY}/OFF-001", json={"announced": "phone"})
    after = _doc_text(client.get(f"/api/duty/{DAY}/export.docx"))
    board_after = client.get(f"/api/board/{DAY}").get_json()
    assert after == before
    assert board_after["sections"] == board_before["sections"]

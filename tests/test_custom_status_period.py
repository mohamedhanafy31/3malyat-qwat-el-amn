"""حالة حرة مخصصة بمدة ثابتة، مع الحفاظ على الحالة الحرة اليومية."""
from io import BytesIO

from docx import Document

from backend.board_export import _presentation_sections, status_period_text
from backend.duty_export import _daily_text
from backend.store import assemble


OFFICER = "OFF-002"
START = "2026-05-01"


def _row(client, day, officer_id=OFFICER):
    body = client.get(f"/api/duty/{day}").get_json()
    return next(row for row in body["rows"] if row["id"] == officer_id)


def _periods():
    return assemble().get("officer_status_periods") or []


def _board_outsider(client, day, officer_id=OFFICER):
    board = client.get(f"/api/board/{day}").get_json()
    outsiders = next(section for section in board["sections"] if section["name"] == "الخوارج")
    return board, next(row for row in outsiders["rows"] if row["id"] == officer_id)


def _docx_text(response):
    document = Document(BytesIO(response.data))
    return "\n".join(cell.text for table in document.tables for row in table.rows for cell in row.cells)


def test_custom_period_is_one_record_and_flows_through_all_views_and_exports(client):
    status = "راحة تشغيلية"
    fixed_text = "راحة بعد مأمورية"
    saved = client.put(f"/api/duty/{START}/{OFFICER}", json={
        "status": status, "note": fixed_text, "status_period": True,
        "status_end": "2026-05-03",
    })
    assert saved.status_code == 200, saved.get_json()
    periods = _periods()
    assert len(periods) == 1
    assert periods[0]["status"] == status
    assert periods[0]["custom"] is True
    assert periods[0]["details"] == fixed_text
    assert periods[0]["end"] == "2026-05-03"

    for day in ("2026-05-01", "2026-05-02", "2026-05-03"):
        row = _row(client, day)
        assert (row["group"], row["bucket"], row["status"], row["text"]) == (
            "خوارج", status, status, fixed_text)
        assert row["note"] == fixed_text
        assert row["persistent_status"]["details"] == fixed_text

        board, outsider = _board_outsider(client, day)
        assert outsider["reason"] == status
        assert status_period_text(outsider["status_period"]) == fixed_text
        presentation = _presentation_sections(board["sections"])
        presented = next(section for section in presentation if section["name"] == "الخوارج")
        assert next(item for item in presented["rows"] if item["id"] == OFFICER)["detail"] == fixed_text

        assert fixed_text in _docx_text(client.get(f"/api/board/{day}/export.docx"))
        assert fixed_text in _docx_text(client.get(f"/api/duty/{day}/export.docx"))
        assert _daily_text(row) == fixed_text

    after = _row(client, "2026-05-04")
    assert after["status"] == "" and after["persistent_status"] is None


def test_custom_period_can_be_edited_from_the_middle_without_new_record(client):
    first = client.put(f"/api/duty/{START}/{OFFICER}", json={
        "status": "تكليف ميداني", "note": "النسخة الأولى", "status_period": True,
        "status_end": "2026-05-05",
    })
    assert first.status_code == 200, first.get_json()
    period_id = _periods()[0]["id"]

    edited = client.put("/api/duty/2026-05-03/OFF-002", json={
        "status": "تكليف ميداني", "note": "النسخة المعدلة", "status_period": True,
        "status_end": "2026-05-07",
    })
    assert edited.status_code == 200, edited.get_json()
    periods = _periods()
    assert len(periods) == 1
    assert periods[0]["id"] == period_id
    assert (periods[0]["start"], periods[0]["end"], periods[0]["details"]) == (
        START, "2026-05-07", "النسخة المعدلة")
    assert _row(client, "2026-05-04")["text"] == "النسخة المعدلة"
    events = [event for event in assemble().get("change_log") or []
              if event.get("entity") == "officer_status_period"]
    assert events[-1]["action"] == "update"
    assert "تعديل" in events[-1]["text"]


def test_custom_period_supports_stop_and_cancel(client):
    client.put(f"/api/duty/{START}/{OFFICER}", json={
        "status": "تغطية مؤقتة", "note": "نص ثابت", "status_period": True,
        "status_end": "2026-05-10",
    })
    stopped = client.post("/api/duty/2026-05-05/OFF-002/stop-status", json={})
    assert stopped.status_code == 200, stopped.get_json()
    assert [(p["start"], p["end"]) for p in _periods()] == [(START, "2026-05-04")]
    assert _row(client, "2026-05-05")["persistent_status"] is None

    client.put("/api/duty/2026-05-10/OFF-002", json={
        "status": "تغطية مؤقتة", "note": "تسجيل آخر", "status_period": True,
        "status_end": "2026-05-12",
    })
    cancelled = client.post("/api/duty/2026-05-11/OFF-002/cancel-status", json={})
    assert cancelled.status_code == 200, cancelled.get_json()
    assert [(p["start"], p["end"]) for p in _periods()] == [(START, "2026-05-04")]
    events = [event for event in assemble().get("change_log") or []
              if event.get("entity") == "officer_status_period"]
    assert events[-1]["action"] == "delete"


def test_one_day_custom_status_keeps_note_in_detailed_outsiders(client):
    status = "تكليف يومي"
    note = "ملاحظة اليوم فقط"
    saved = client.put(f"/api/duty/{START}/{OFFICER}", json={"status": status, "note": note})
    assert saved.status_code == 200, saved.get_json()
    assert _periods() == []

    row = _row(client, START)
    assert row["status_source"] == "day" and row["note"] == note
    board, outsider = _board_outsider(client, START)
    assert outsider["status_period"] is None
    assert outsider["reason"] == status
    presentation = _presentation_sections(board["sections"])
    presented = next(section for section in presentation if section["name"] == "الخوارج")
    assert next(item for item in presented["rows"] if item["id"] == OFFICER)["detail"] == note
    assert note in _docx_text(client.get(f"/api/board/{START}/export.docx"))
    assert note in _docx_text(client.get(f"/api/duty/{START}/export.docx"))
    assert _row(client, "2026-05-02")["status"] == ""


def test_builtin_bounded_status_remains_a_bounded_period(client):
    saved = client.put(f"/api/duty/{START}/{OFFICER}", json={
        "status": "طارئة", "status_end": "2026-05-03",
    })
    assert saved.status_code == 200, saved.get_json()
    period = _periods()[0]
    assert "custom" not in period
    assert _row(client, "2026-05-02")["persistent_status"]["kind"] == "bounded"

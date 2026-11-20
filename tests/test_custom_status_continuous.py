"""الحالة المخصصة المستمرة: مدى مفتوح بنص ثابت حتى الإنهاء أو الإلغاء."""
from datetime import date, timedelta
from io import BytesIO

from docx import Document

from backend.board_export import _presentation_sections, status_period_text
from backend.duty_export import _daily_text
from backend.store import assemble
from backend.status_periods import duration


OFFICER = "OFF-002"
START = "2026-06-01"
STATUS = "راحة خاصة"
TEXT = "راحة أحمد فوزي حتى الإلغاء"


def _days(start, count):
    first = date.fromisoformat(start)
    return [(first + timedelta(days=offset)).isoformat() for offset in range(count)]


def _row(client, day, officer_id=OFFICER):
    return next(row for row in client.get(f"/api/duty/{day}").get_json()["rows"]
                if row["id"] == officer_id)


def _periods():
    return assemble().get("officer_status_periods") or []


def _outsider(client, day, officer_id=OFFICER):
    board = client.get(f"/api/board/{day}").get_json()
    section = next(item for item in board["sections"] if item["name"] == "الخوارج")
    return board, next(item for item in section["rows"] if item["id"] == officer_id)


def _docx_text(response):
    document = Document(BytesIO(response.data))
    return "\n".join(cell.text for table in document.tables for row in table.rows for cell in row.cells)


def _start(client, day=START, note=TEXT, **extra):
    return client.put(f"/api/duty/{day}/{OFFICER}", json={
        "status": STATUS, "note": note, "status_period": True,
        "status_mode": "continuous", **extra,
    })


def test_custom_continuous_flows_through_daily_board_word_and_roster(client):
    saved = _start(client)
    assert saved.status_code == 200, saved.get_json()
    period = _periods()[0]
    assert (period["custom"], period["details"], period["end"], period["mode"]) == (
        True, TEXT, "", "continuous")
    events = [event for event in assemble().get("change_log") or []
              if event.get("entity") == "officer_status_period"]
    assert "مستمرة" in events[-1]["text"]

    for day in _days(START, 41):
        row = _row(client, day)
        assert (row["group"], row["bucket"], row["status"], row["text"], row["note"]) == (
            "خوارج", STATUS, STATUS, TEXT, TEXT)
        assert row["persistent_status"]["kind"] == "continuous"
        assert row["persistent_status"]["open_ended"] is True
        assert row["persistent_status"]["legacy_open"] is False

    before = _row(client, "2026-05-31")
    assert before["status"] == "" and before["persistent_status"] is None

    board, outsider = _outsider(client, START)
    assert outsider["reason"] == STATUS
    assert outsider["status_period"]["details"] == TEXT
    presented = _presentation_sections(board["sections"])
    section = next(item for item in presented if item["name"] == "الخوارج")
    assert next(item for item in section["rows"] if item["id"] == OFFICER)["detail"] == TEXT
    assert TEXT in _docx_text(client.get(f"/api/board/{START}/export.docx"))
    assert TEXT in _docx_text(client.get(f"/api/duty/{START}/export.docx"))
    assert _daily_text(_row(client, START)) == TEXT

    roster = client.get(f"/api/assignments-roster/{START}").get_json()
    assert OFFICER not in {item["id"] for item in roster["rows"]}
    assert OFFICER not in {item["id"] for item in roster["all_rows"]}
    roster_docx = _docx_text(client.get(f"/api/assignments-roster/{START}/export.docx"))
    assert "محمود علي" not in roster_docx

    outsider_register = client.get("/api/bootstrap/outsiders").get_json()["outsiders"]
    register_row = next(item for item in outsider_register if item["status"] == STATUS)
    assert register_row["open_ended"] is True and register_row["duration"]["precision"] == "days"
    assert duration(period, today="2026-07-11")["days"] == 41


def test_custom_continuous_edit_and_mode_switch_keep_one_record(client):
    assert _start(client).status_code == 200
    period_id = _periods()[0]["id"]

    edited = _start(client, "2026-06-12", note="نص معدل من منتصف المدة")
    assert edited.status_code == 200, edited.get_json()
    assert len(_periods()) == 1 and _periods()[0]["id"] == period_id
    assert _periods()[0]["details"] == "نص معدل من منتصف المدة"

    bounded = client.put(f"/api/duty/2026-06-12/{OFFICER}", json={
        "status": STATUS, "note": "نص الفترة", "status_period": True,
        "status_mode": "bounded", "status_end": "2026-06-20",
    })
    assert bounded.status_code == 200, bounded.get_json()
    assert len(_periods()) == 1 and _periods()[0]["id"] == period_id
    assert _periods()[0]["end"] == "2026-06-20"
    assert _row(client, "2026-06-20")["persistent_status"]["kind"] == "bounded"
    assert _row(client, "2026-06-21")["persistent_status"] is None

    continuous = _start(client, "2026-06-15", note="عاد للاستمرار")
    assert continuous.status_code == 200, continuous.get_json()
    assert len(_periods()) == 1 and _periods()[0]["id"] == period_id
    assert _periods()[0]["end"] == ""
    assert _row(client, "2026-07-25")["persistent_status"]["details"] == "عاد للاستمرار"


def test_custom_continuous_rejects_end_and_locked_start(client):
    with_end = client.put(f"/api/duty/{START}/{OFFICER}", json={
        "status": STATUS, "note": TEXT, "status_period": True,
        "status_mode": "continuous", "status_end": "2026-06-03",
    })
    assert with_end.status_code == 400
    assert "مستمرة" in with_end.get_json()["error"]
    assert _periods() == []

    locked_day = "2026-05-15"
    assert client.post(f"/api/day-status/{locked_day}/close", json={}).status_code in (200, 201)
    locked = _start(client, locked_day)
    assert locked.status_code == 409
    assert _periods() == []


def test_custom_continuous_stop_preserves_history_and_cancel_removes_everywhere(client):
    assert _start(client).status_code == 200
    stopped = client.post(f"/api/duty/2026-06-10/{OFFICER}/stop-status", json={})
    assert stopped.status_code == 200, stopped.get_json()
    assert [(p["start"], p["end"]) for p in _periods()] == [(START, "2026-06-09")]
    assert _row(client, "2026-06-09")["text"] == TEXT
    assert _row(client, "2026-06-10")["persistent_status"] is None

    cancelled_history = client.post(f"/api/duty/2026-06-05/{OFFICER}/cancel-status", json={})
    assert cancelled_history.status_code == 200, cancelled_history.get_json()
    assert _periods() == []

    assert _start(client, "2026-06-15", note="نص سيُلغى").status_code == 200
    cancelled = client.post(f"/api/duty/2026-06-20/{OFFICER}/cancel-status", json={})
    assert cancelled.status_code == 200, cancelled.get_json()
    assert _periods() == []
    assert "نص سيُلغى" not in _docx_text(client.get("/api/board/2026-06-20/export.docx"))
    assert _row(client, "2026-06-20")["persistent_status"] is None


def test_custom_continuous_and_builtin_continuous_use_existing_overlap_rule(client):
    assert _start(client).status_code == 200
    sick = client.put(f"/api/duty/2026-06-05/{OFFICER}", json={"status": "مرضي"})
    assert sick.status_code == 200, sick.get_json()
    periods = {period["status"]: period for period in _periods()}
    assert periods[STATUS]["end"] == "2026-06-04"
    assert periods["مرضي"]["end"] == ""
    assert _row(client, "2026-06-04")["status"] == STATUS
    assert _row(client, "2026-06-05")["status"] == "مرضي"

    custom_again = _start(client, "2026-06-08", note="بعد المرضي")
    assert custom_again.status_code == 200, custom_again.get_json()
    periods = {period["status"]: period for period in _periods()}
    assert periods["مرضي"]["end"] == "2026-06-07"
    assert periods[STATUS]["end"] == ""
    assert _row(client, "2026-06-07")["status"] == "مرضي"
    assert _row(client, "2026-06-08")["status"] == STATUS


def test_custom_open_period_text_falls_back_to_start_in_board_export():
    assert status_period_text({"custom": True, "details": "", "start": START}) == "من 1/6"

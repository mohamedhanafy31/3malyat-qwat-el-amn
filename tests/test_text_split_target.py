"""تقسيم تغطية الهدف/المعسكر الفرعي بعبارتين نصيتين حرتين."""
import io
from pathlib import Path
from urllib.parse import quote

from docx import Document

from backend.store import load_data


DAY = "2026-04-10"
TARGET = "سوميد"
TEXT_SPLIT = [
    {"officer_id": "OFF-001", "label": "لحين انتهاء المباراة"},
    {"officer_id": "OFF-002", "label": "عقب الانتهاء من المباراة"},
]
TIME_SPLIT = [
    {"officer_id": "OFF-001", "until": "16:00"},
    {"officer_id": "OFF-002", "from": "16:00"},
]
SECTION = "ضابط عظيم وأمن المعسكر الفرعي"
SHIFT = "صباحية"


def _put_target(client, body):
    return client.put(f"/api/board/{DAY}/target/{TARGET}", json=body)


def _put_slot(client, body):
    return client.put(f"/api/board/{DAY}/slot/{quote(SECTION)}/{quote(SHIFT)}", json=body)


def _board_section(client, name):
    return next(s for s in client.get(f"/api/board/{DAY}").get_json()["sections"]
                if s["name"] == name)


def _target(client):
    return next(r for r in _board_section(client, "الأهداف")["rows"] if r["name"] == TARGET)


def _slot(client):
    return next(r for r in _board_section(client, SECTION)["rows"]
                if r.get("slot") and r["shift"] == SHIFT)


def _duty_rows(client):
    return {row["id"]: row for row in client.get(f"/api/duty/{DAY}").get_json()["rows"]}


def _docx_text(client):
    document = Document(io.BytesIO(client.get(f"/api/board/{DAY}/export.docx").data))
    return "\n".join(
        paragraph.text
        for table in document.tables
        for row in table.rows
        for cell in row.cells
        for paragraph in cell.paragraphs
    )


def test_text_split_target_round_trips_and_reaches_all_daily_views(client):
    response = _put_target(client, {"periods": TEXT_SPLIT})
    assert response.status_code == 200, response.get_data(as_text=True)

    stored = next(row for row in load_data([DAY])["day_assignments"][DAY]
                  if row["name"] == TARGET)
    assert stored["periods"] == TEXT_SPLIT
    row = _target(client)
    assert row["periods"] == TEXT_SPLIT
    assert [officer["period_label"] for officer in row["officers"]] == [
        "لحين انتهاء المباراة", "عقب الانتهاء من المباراة"
    ]

    duty = _duty_rows(client)
    assert duty["OFF-001"]["services"][0]["period_label"] == TEXT_SPLIT[0]["label"]
    assert duty["OFF-002"]["services"][0]["period_label"] == TEXT_SPLIT[1]["label"]


def test_text_split_is_stored_for_the_subcamp_slot(client):
    response = _put_slot(client, {"periods": TEXT_SPLIT})
    assert response.status_code == 200, response.get_data(as_text=True)
    assert _slot(client)["periods"] == TEXT_SPLIT
    assert [officer["period_label"] for officer in _slot(client)["officers"]] == [
        item["label"] for item in TEXT_SPLIT
    ]


def test_text_split_keeps_both_officers_when_target_defaults_are_calculated(client):
    assert _put_target(client, {"periods": TEXT_SPLIT}).status_code == 200
    from backend.target_defaults import _target_map

    data = load_data([DAY])
    row = next(row for row in data["day_assignments"][DAY] if row["name"] == TARGET)
    assert _target_map([row], [TARGET])[TARGET] == ["OFF-001", "OFF-002"]


def test_text_split_validation_requires_two_different_officers_and_two_short_labels(client):
    invalid = [
        [{"officer_id": "OFF-001", "label": "لحين فقط"},
         {"officer_id": "OFF-001", "label": "عقب فقط"}],
        [{"officer_id": "OFF-001", "label": ""},
         {"officer_id": "OFF-002", "label": "عقب النهاية"}],
        [{"officer_id": "OFF-001", "label": "لحين النهاية"},
         {"officer_id": "OFF-002", "label": "س" * 81}],
        [{"officer_id": "OFF-001", "label": "لحين النهاية"},
         {"officer_id": "OFF-002", "from": "16:00"}],
        [{"officer_id": "OFF-001", "label": "لحين\nالنهاية"},
         {"officer_id": "OFF-002", "label": "عقب النهاية"}],
    ]
    for periods in invalid:
        response = _put_target(client, {"periods": periods})
        assert response.status_code == 400, (periods, response.get_data(as_text=True))


def test_text_labels_are_printed_next_to_the_correct_names_in_detailed_daily(client):
    assert _put_target(client, {"periods": TEXT_SPLIT}).status_code == 200
    text = _docx_text(client)
    assert "عقيد/ أحمد محمد لحين انتهاء المباراة" in text
    assert "نقيب/ محمود علي عقب الانتهاء من المباراة" in text


def test_text_split_can_be_replaced_by_time_and_then_cleared(client):
    assert _put_target(client, {"periods": TEXT_SPLIT}).status_code == 200
    assert _put_target(client, {"periods": TIME_SPLIT}).status_code == 200
    assert _target(client)["periods"] == TIME_SPLIT
    assert [officer["period_label"] for officer in _target(client)["officers"]] == [
        "حتى 4م", "من 4م"
    ]

    assert _put_target(client, {"officer_ids": ["OFF-001", "OFF-002"], "periods": []}).status_code == 200
    assert _target(client)["periods"] == []
    assert all("period_label" not in officer for officer in _target(client)["officers"])


def test_confirm_diff_mentions_text_labels(client):
    assert _put_target(client, {"officer_ids": ["OFF-001", "OFF-002"]}).status_code == 200
    assert client.post(f"/api/board/{DAY}/confirm").status_code == 201
    assert _put_target(client, {"periods": TEXT_SPLIT}).status_code == 200
    assert client.post(f"/api/board/{DAY}/confirm").status_code == 201
    entries = client.get("/api/changes").get_json()["entries"]
    assignment_changes = [entry for entry in entries if entry.get("entity") == "assignment"]
    assert any("لحين انتهاء المباراة" in entry["text"]
               and "عقب الانتهاء من المباراة" in entry["text"]
               for entry in assignment_changes)


def test_text_split_modal_keeps_the_old_time_payload_and_adds_text_controls():
    root = Path(__file__).resolve().parents[1]
    modal = (root / "templates/partials/target_modal.html").read_text(encoding="utf-8")
    board = (root / "static/js/board.js").read_text(encoding="utf-8")
    assert "التقسيم بـ:" in modal
    assert 'id="tgSplitByTime"' in modal and 'id="tgSplitByText"' in modal
    assert 'id="tgFirstLabel"' in modal and 'id="tgSecondLabel"' in modal
    assert 'body.periods = [{officer_id: first, until: at}, {officer_id: second, from: at}];' in board
    assert 'label: firstLabel' in board and 'label: secondLabel' in board

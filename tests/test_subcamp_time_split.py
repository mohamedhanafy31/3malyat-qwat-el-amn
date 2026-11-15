"""تقسيم فترة «ضابط عظيم وأمن المعسكر الفرعي» بالوقت بين ضابطين (زي الأهداف)."""
import io
from urllib.parse import quote

from docx import Document

from backend.store import load_data

DAY = "2026-04-10"
SECTION = "ضابط عظيم وأمن المعسكر الفرعي"
SHIFT = "صباحية"
SPLIT = [{"officer_id": "OFF-001", "until": "16:00"},
         {"officer_id": "OFF-002", "from": "16:00"}]


def _put(client, body, section=SECTION, shift=SHIFT):
    return client.put(f"/api/board/{DAY}/slot/{quote(section)}/{quote(shift)}", json=body)


def _slot(client, section=SECTION, shift=SHIFT):
    sections = client.get(f"/api/board/{DAY}").get_json()["sections"]
    block = next(s for s in sections if s["name"] == section)
    return next(r for r in block["rows"] if r.get("slot") and r["shift"] == shift)


def _docx_text(client):
    doc = Document(io.BytesIO(client.get(f"/api/board/{DAY}/export.docx").data))
    out = []

    def walk(tables):
        for table in tables:
            for row in table.rows:
                for cell in row.cells:
                    out.extend(p.text for p in cell.paragraphs)
                    walk(cell.tables)

    walk(doc.tables)
    return "\n".join(out)


def test_subcamp_slot_split_is_stored_and_shown_with_period_labels(client):
    response = _put(client, {"periods": SPLIT})
    assert response.status_code == 200, response.get_data(as_text=True)
    stored = next(r for r in load_data([DAY])["day_assignments"][DAY] if r["section"] == SECTION)
    assert stored["periods"] == SPLIT and stored["officer_ids"] == ["OFF-001", "OFF-002"]
    row = _slot(client)
    assert [o["period_label"] for o in row["officers"]] == ["حتى 4م", "من 4م"]
    assert row["periods"] == SPLIT


def test_split_service_line_in_duty_roster_carries_the_period(client):
    _put(client, {"periods": SPLIT})
    rows = {r["id"]: r for r in client.get(f"/api/duty/{DAY}").get_json()["rows"]}
    first = rows["OFF-001"]["services"][0]
    second = rows["OFF-002"]["services"][0]
    assert first["period_label"] == "حتى 4م" and second["period_label"] == "من 4م"


def test_split_appears_in_the_detailed_daily_word_export(client):
    _put(client, {"periods": SPLIT})
    text = _docx_text(client)
    assert "حتى 4م" in text and "من 4م" in text


def test_clearing_and_changing_the_split(client):
    _put(client, {"periods": SPLIT})
    _put(client, {"officer_ids": ["OFF-001", "OFF-002"], "periods": []})
    assert _slot(client)["periods"] == []
    _put(client, {"periods": SPLIT})
    _put(client, {"officer_ids": ["OFF-001"]})
    row = _slot(client)
    assert row["periods"] == [] and len(row["officers"]) == 1


def test_split_validation_and_other_blocks_reject_it(client):
    assert _put(client, {"periods": [SPLIT[0]]}).status_code == 400
    mismatch = [SPLIT[0], {"officer_id": "OFF-002", "from": "17:00"}]
    assert _put(client, {"periods": mismatch}).status_code == 400
    assert _put(client, {"periods": SPLIT, "officer_ids": ["OFF-001"]}).status_code == 400
    # ضابط عظيم الإدارة وأمن الإدارة: مفيش تقسيم
    assert _put(client, {"periods": SPLIT}, section="ضابط عظيم الإدارة").status_code == 400
    assert _put(client, {"periods": SPLIT}, section="ضابط الأمن بالإدارة").status_code == 400
    assert _slot(client)["vacant"] is True

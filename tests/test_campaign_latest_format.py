from io import BytesIO

from docx import Document
from docx.oxml.ns import qn

from backend.campaign_export import CHECKPOINT_SPANS, DELIVERY_SPANS, GRID_WIDTHS, LAST_FIT, build_docx


def _text(doc):
    return [cell.text for row in doc.tables[0].rows for cell in row.cells]


def test_latest_format_shape_and_mapping():
    payload = {
        "date": "2026-09-29",
        "posts": [{"number": "10.", "name": "بوابة", "driver_text": "مجند حر",
                    "plate_text": "3279ب13", "type_text": "مايك ايفكو", "vehicle": None}],
        "lorries": [{"name": "الإفطار + المحور", "driver": {"kind": "text", "name": "سائق"},
                     "vehicle": {"plate": "ب15/5217", "type": "لوري", "origin": "internal"}}],
        "services": [], "daily": [], "appointments": [],
        "plates": {"rows": [["ب13/9416", "", "ب14/7895", "", "", "", ""]]},
    }
    doc = Document(BytesIO(build_docx(payload).read()))
    table = doc.tables[0]
    assert table.rows[0].cells[0]._tc.find(qn('w:tcPr')).find(qn('w:gridSpan')).get(qn('w:val')) == '15'
    spans = [tc.find(qn('w:tcPr')).find(qn('w:gridSpan'))
             for tc in table.rows[1]._tr.findall(qn('w:tc'))]
    assert [node.get(qn('w:val')) if node is not None else None for node in spans[:5]] == [None, '3', '4', '3', '4']
    assert len(table.rows[-1]._tr.findall('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tc')) == 7
    assert table.rows[0].cells[0].text == "يومية المركبات اليوم الثلاثاء 29/9/2026م"
    values = _text(doc)
    assert "10." in values and "3279ب13" in values and "5217" in values
    assert "مايك ايفكو" in values and "ـــــ" not in values
    assert [c.width.twips for c in table.rows[0].cells[:1]] == [sum(GRID_WIDTHS)]
    assert LAST_FIT["ratio"] <= .94


def test_latest_format_empty_day_is_reopenable_and_one_page():
    payload = {"date": "2026-09-29", "posts": [], "lorries": [], "services": [],
               "daily": [], "appointments": [], "plates": {"rows": []}}
    doc = Document(BytesIO(build_docx(payload).read()))
    assert len(doc.tables) == 1
    assert len(doc.tables[0].rows) == 4
    assert LAST_FIT["ratio"] <= .94


def test_latest_format_worst_case_fits():
    post = {"number": "11.", "name": "ارتكاز طويل", "driver_text": "سائق", "vehicle": None,
            "plate_text": "1234ب13", "type_text": "بيك اب"}
    delivery = {"name": "خدمة طويلة", "driver": {"kind": "text", "name": "سائق"},
                "vehicle": {"plate": "ب15/5217", "type": "بيك اب دوبل كبينة", "origin": "internal"}}
    payload = {"date": "2026-09-29", "posts": [post] * 11, "lorries": [delivery] * 4,
               "services": [delivery] * 20, "daily": [delivery] * 16,
               "appointments": [delivery] * 3,
               "plates": {"rows": [["x"] * 7] * 3}}
    Document(BytesIO(build_docx(payload).read()))
    assert LAST_FIT["ratio"] <= .94

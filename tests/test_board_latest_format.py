import io
from datetime import date, timedelta
from pathlib import Path

import pytest
from docx import Document

from backend.board_export import LAST_FIT, build_docx
from tools.fidelity.board import read_docx, signature


ARCHIVE = Path("../../2026/9/29/29.docx")


def _generated(board=None):
    payload = board or {"date": "2026-09-28", "sections": []}
    raw = build_docx(payload).getvalue()
    return raw, read_docx_from_bytes(raw)


def read_docx_from_bytes(raw):
    document = Document(io.BytesIO(raw))
    table = document.tables[0]
    assert len(table.rows) == 34
    return document


def test_latest_structure_matches_929_archive_except_corrected_bottom_margin():
    """أعمدة/صفوف/الصفحة زي آخر يوم في الأرشيف (29/9). عروض الأعمدة بتتغيّر
    يدويًا من يوم للتاني في الأرشيف (28/9 غير 29/9) فمش بنقارنها؛ والدمج
    الرأسي بيتبع بيانات اليوم."""
    if not ARCHIVE.is_file():
        pytest.skip("latest archive is not available")
    raw, document = _generated()
    generated_path = Path("/tmp/board-latest-structure-test.docx")
    generated_path.write_bytes(raw)
    archive = signature(read_docx(ARCHIVE))
    current = signature(read_docx(generated_path))
    assert current["columns"] == archive["columns"] == 6
    assert current["grid_widths"] == ["1694", "9", "2974", "711", "2129", "3248"]
    assert current["row_count"] == archive["row_count"] == 34
    for key in ("w", "h", "orient", "top", "right", "left"):
        assert current["page"][key] == archive["page"][key]
    assert current["page"]["bottom"] == "142"
    assert LAST_FIT["ratio"] <= 0.94


def test_latest_structure_is_identical_for_all_days():
    signatures = []
    start = date(2026, 8, 1)
    for offset in range(60):
        day = (start + timedelta(days=offset)).isoformat()
        raw = build_docx({"date": day, "sections": []}).getvalue()
        path = Path(f"/tmp/board-structure-{offset}.docx")
        path.write_bytes(raw)
        current = signature(read_docx(path))
        current["page"] = {key: value for key, value in current["page"].items()
                           if key != "bottom"}
        signatures.append(current)
    assert all(item == signatures[0] for item in signatures)


def test_empty_latest_export_has_no_placeholder_dash():
    raw, document = _generated()
    text = "\n".join(cell.text for row in document.tables[0].rows for cell in row.cells)
    assert "—" not in text
    assert len(raw) > 1000
    assert LAST_FIT["ratio"] <= 0.94


def _board_with_tail(admin_count, outsiders):
    admin = [{"id": f"O{i}", "name": f"ضابط {i}", "role": "رائد", "text": f"عمل {i}"}
             for i in range(admin_count)]
    return {"date": "2026-10-05", "sections": [
        {"name": "عمل بالإدارة", "type": "admin", "rows": admin},
        {"name": "الراحات", "type": "officers", "rows": [
            {"id": f"R{i}", "name": f"مستريح {i}", "role": "نقيب", "type": "شهرية"}
            for i in range(outsiders)]},
    ]}


def _tail_texts(document):
    table = document.tables[0]
    return [[cell.text for cell in _unique(row)] for row in table.rows[20:]]


def _unique(row):
    """الخلايا الفعلية في الـXML (مش الأسماء المستعارة للدمج الرأسي)."""
    from docx.table import _Cell
    return [_Cell(tc, row.table) for tc in row._tr.tc_lst]


def test_default_tail_keeps_the_official_34_rows():
    _, document = _generated(_board_with_tail(3, 2))
    assert len(document.tables[0].rows) == 34


def test_many_admin_work_rows_grow_the_table_instead_of_being_dropped():
    raw = build_docx(_board_with_tail(16, 0)).getvalue()
    document = Document(io.BytesIO(raw))
    rows = _tail_texts(document)
    assert len(document.tables[0].rows) == 20 + 3 + 16
    text = "\n".join(" | ".join(row) for row in rows)
    for i in range(16):
        assert f"عمل {i}" in text
    assert LAST_FIT["ratio"] <= 0.94


def test_many_outsiders_grow_the_table_and_merge_their_status_vertically():
    from docx.oxml.ns import qn

    raw = build_docx(_board_with_tail(0, 18)).getvalue()
    document = Document(io.BytesIO(raw))
    table = document.tables[0]
    assert len(table.rows) == 20 + 18
    text = "\n".join(" | ".join(row) for row in _tail_texts(document))
    for i in range(18):
        assert f"مستريح {i}" in text
    # «راحة» مكتوبة مرة واحدة في أول صف والباقي continue فاضي
    first = _unique(table.rows[20])[-3]
    marks = [_unique(table.rows[i])[-3]._tc.tcPr.find(qn("w:vMerge")) for i in range(20, 38)]
    assert first.text == "راحة" and all(mark is not None for mark in marks)
    assert marks[0].get(qn("w:val")) == "restart"
    assert all(_unique(table.rows[i])[-3].text == "" for i in range(21, 38))
    assert LAST_FIT["ratio"] <= 0.94


def test_header_shading_in_row_22_covers_only_the_admin_header():
    _, document = _generated(_board_with_tail(2, 4))
    from docx.oxml.ns import qn
    cells = _unique(document.tables[0].rows[22])
    fills = [c._tc.tcPr.find(qn("w:shd")) is not None for c in cells]
    assert fills == [True, False, False, False]

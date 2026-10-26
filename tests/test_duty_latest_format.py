from io import BytesIO
from pathlib import Path

import pytest
from docx import Document

from backend.duty_export import LAST_FIT, _daily_text, build_docx
from tools.fidelity.duty import _structure, load_docx


ARCHIVE = Path(__file__).parents[3] / "2026/9/29/29-9-2026.docx"


def _summary():
    return {
        "أصل القوة": 1,
        "خارجية": {"صباحية": 0, "ليلية": 0, "بحث": 0},
        "داخلية": {"صباحية": 0, "ليلية": 0},
        "طبية": {"موجود": 0, "راحة": 0},
        "خوارج": {key: 0 for key in ("تقصيرة", "راحة", "طارئة", "غياب", "مرضي", "فرقة", "انتداب")},
        "حراسات": 0,
        "صافي": 1,
        "net_names": ["ignored by exporter"],
    }


def _duty(rest_system="أسبوعية", rest_day=None):
    return {"date": "2026-09-29", "summary": _summary(), "rows": [{
        "section": "القوة", "role": "ملازم أول", "name": "الاسم الكامل للضابط",
        "post": "عمل بالإدارة", "rest_system": rest_system, "rest_day": rest_day,
        "group": "صافي", "services": [], "status": "", "note": "",
    }]}


def test_latest_geometry_and_one_page_fit():
    output = build_docx(_duty()).getvalue()
    document = Document(BytesIO(output))
    assert len(document.tables[0].rows) == 37
    assert len(document.tables[1].rows) == 4
    assert document.tables[0].columns[0].width.twips == 574
    assert document.tables[1].columns[15].width.twips == 1834
    assert LAST_FIT["ratio"] <= .94
    assert len(Document(BytesIO(output)).tables) == 2


def test_latest_mapping_uses_full_roster_name_and_dash_rest():
    document = Document(BytesIO(build_docx(_duty()).getvalue()))
    row = document.tables[0].rows[1]
    assert row.cells[1].text == "م.اول"
    assert row.cells[2].text == "الاسم الكامل للضابط"
    assert row.cells[5].text == "------------"
    assert document.tables[1].rows[0].cells[15].text == "الصافي"


def test_open_status_prints_name_and_start_day_only():
    row = {"status": "مرضي", "status_source": "period", "persistent_status": {
        "status": "مرضي", "start": "2026-10-23", "end": "",
    }}
    assert _daily_text(row) == "مرضي من يوم 23/10/2026"


def test_bounded_status_keeps_start_and_end_days():
    row = {"status": "طارئة", "status_source": "period", "persistent_status": {
        "status": "طارئة", "start": "2026-10-23", "end": "2026-10-25",
    }}
    assert _daily_text(row) == "طارئة من 23/10/2026 حتى 25/10/2026"


def test_archive_structure_signature_matches_latest_template_when_available():
    if not ARCHIVE.exists():
        pytest.skip("latest archive is not present")
    # Compare the template's fixed XML geometry directly; content is filled in
    # separately and must not change grids, merges, or page setup.
    from backend.duty_export import TEMPLATE
    assert _structure(load_docx(ARCHIVE)) == _structure(load_docx(TEMPLATE))

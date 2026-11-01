from io import BytesIO
from zipfile import ZipFile
from urllib.parse import unquote

from docx import Document

from backend.formation import build
from backend.formation_export import LAST_FIT, PageFitError, build_docx


DAY = "2026-10-20"


def _data():
    return {
        "counts_template": {"entries": [
            {"id": "CNT-1", "name": "أساسية", "block": "صباحية", "count": 3, "weapon": "الى"},
            {"id": "CNT-2", "name": "ليلية خدمة", "block": "ليلية", "count": 2, "weapon": "الي + كلبش"},
        ]},
        "day_assignments": {DAY: [
            {"id": "A1", "name": "طارئة 11", "section": "الخدمات الطارئة", "shift": "صباحية",
             "time": "11:59ص", "conscript_count": 2, "weapon": "ف"},
            {"id": "A2", "name": "طارئة ظهر", "section": "الخدمات الطارئة", "shift": "صباحية",
             "time": "12ظ", "conscript_count": 9, "weapon": "ف"},
            {"id": "A3", "name": "بدون", "section": "الخدمات الطارئة", "shift": "صباحية",
             "time": "", "conscript_count": 1, "weapon": "الي"},
        ]},
        "day_afraad": {}, "service_counts": {},
    }


def _xml(output):
    return ZipFile(BytesIO(output.getvalue())).read("word/document.xml").decode()


def test_dto_slots_weapons_time_boundary_and_no_time():
    result = build(_data(), DAY, "morning")
    assert [b["name"] for b in result["blocks"]] == ["أساسية", "طارئة 11", "بدون"]
    assert result["blocks"][0]["weapons"] == ["آلي"] * 3
    assert result["blocks"][1]["time"] == "11:59ص"
    assert result["blocks"][2]["time"] == "بدون ميعاد"
    assert result["warnings"]
    assert result["title"] == "خط تشكيل صباحي عن يوم الثلاثاء الموافق 20/10/2026م"


def test_docx_portrait_rtl_title_slots_and_emergency_section():
    output = build_docx(build(_data(), DAY, "morning"))
    document = Document(BytesIO(output.getvalue()))
    assert document.sections[0].orientation == 0
    table = document.tables[0]
    assert len(table.columns) == 7
    rows = [[cell.text for cell in row.cells] for row in table.rows]
    texts = [cell for row in rows for cell in row]
    assert "1-" in texts and "2-" in texts and "3-" in texts
    assert "طارئة 11 (11:59ص)" in texts
    assert "خدمات طارئة قبل 12ظ" in texts
    xml = _xml(output)
    assert xml.count("bidiVisual") >= 1
    assert "خط تشكيل صباحي عن يوم الثلاثاء الموافق 20/10/2026م" in xml


def test_night_uses_basic_pm_and_totals():
    result = build(_data(), DAY, "night")
    assert [b["name"] for b in result["blocks"]] == ["ليلية خدمة"]
    assert result["blocks"][0]["weapons"] == ["آلي", "كلبش"]
    output = build_docx(result)
    assert LAST_FIT["page_count"] == 1 and LAST_FIT["halves"] == 2


def _blocks(n, count=1):
    return [{"name": f"خدمة {i}", "title": f"خدمة {i}", "count": count,
             "weapons": ["آلي"] * count, "kind": "basic", "time": ""} for i in range(n)]


def test_more_columns_instead_of_tiny_font():
    dto = {"title": "اختبار", "shift": "night", "day": DAY, "blocks": _blocks(120),
           "totals": {"services": 120, "conscripts": 120}, "warnings": []}
    build_docx(dto)
    assert LAST_FIT["page_count"] == 1
    assert LAST_FIT["halves"] in (3, 4) and LAST_FIT["size_pt"] >= 6.5


def test_big_services_go_to_a_separate_page_and_split_with_continuation():
    blocks = _blocks(3) + [{"name": "ندوة", "title": "ندوة", "count": 80, "weapons": [],
                            "kind": "basic", "time": ""}]
    dto = {"title": "خط تشكيل صباحي عن يوم الأربعاء الموافق 26/8/2026م", "shift": "night", "day": DAY,
           "blocks": blocks, "totals": {"services": 4, "conscripts": 83}, "warnings": []}
    output = build_docx(dto)
    assert LAST_FIT["page_count"] == 2
    text = output.getvalue()
    document = Document(BytesIO(text))
    cells = {cell.text for table in document.tables for row in table.rows for cell in row.cells}
    assert "ندوة (تابع)" in cells and "15" not in cells
    assert any("(الخدمات الكبيرة)" in p.text for p in document.paragraphs)
    first_page = {cell.text for row in document.tables[0].rows for cell in row.cells}
    assert "ندوة" not in first_page


def test_impossible_page_raises():
    heavy = {"title": "اختبار", "shift": "night", "day": DAY, "blocks": _blocks(400),
             "totals": {"services": 400, "conscripts": 400}, "warnings": []}
    try:
        build_docx(heavy)
    except PageFitError as exc:
        assert "صفحة واحدة" in str(exc)
    else:
        raise AssertionError("expected PageFitError")


def test_formation_routes_return_canonical_download_names(client):
    for route, name in (("formation-morning", "خط تشكيل صبح.docx"),
                        ("formation-night", "خط تشكيل ليل.docx")):
        response = client.get(f"/api/ops/{DAY}/{route}.docx")
        assert response.status_code == 200
        assert unquote(response.headers["Content-Disposition"].split("filename*=")[-1].removeprefix("UTF-8''")) == name

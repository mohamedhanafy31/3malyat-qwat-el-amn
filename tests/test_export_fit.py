import io

import pytest
from docx import Document
from openpyxl import Workbook

from backend.export_fit import (PageFitError, TextMeter, configure_xlsx_one_page,
                                 estimate_table_height, fit_table)


def test_meter_single_line_and_wrap_height():
    total, heights = estimate_table_height([[{"text": "نص", "size_pt": 10}]], [100])
    assert 11.4 <= heights[0] <= 15
    wrapped, _ = estimate_table_height([[{"text": "كلمة " * 30, "size_pt": 10}]], [30])
    assert wrapped > total


def test_estimator_handles_colspan_and_vertical_merge():
    total, heights = estimate_table_height([
        [{"text": "عنوان طويل", "colspan": 2, "size_pt": 10}],
        [{"text": "", "rowspan": 2, "size_pt": 24}, {"text": "x", "size_pt": 6}],
        [{"text": "y", "size_pt": 6}],
    ], [30, 70])
    assert total == pytest.approx(sum(heights))
    assert heights[1] + heights[2] >= 24 * 1.1499


def test_fit_table_shrinks_and_rejects_impossible_table():
    result = fit_table({"rows": [[{"text": "كلمة " * 8, "size_pt": 18}] for _ in range(8)],
                        "grid_widths_pt": [80]}, 500)
    assert result.scale < 1
    with pytest.raises(PageFitError):
        fit_table({"rows": [[{"text": "سطر " * 8, "size_pt": 40}] for _ in range(3)],
                   "grid_widths_pt": [10]}, 20)


def test_xlsx_one_page_configuration():
    wb = Workbook()
    ws = wb.active
    ws["B2"] = "x"
    configure_xlsx_one_page(ws)
    assert ws.sheet_properties.pageSetUpPr.fitToPage is True
    assert (ws.page_setup.fitToWidth, ws.page_setup.fitToHeight) == (1, 1)
    assert ws.page_setup.orientation == "landscape"
    assert ws.page_setup.paperSize == 9
    assert "$A$1" in str(ws.print_area) and "$B$2" in str(ws.print_area)


@pytest.fixture
def fake_fonts(monkeypatch):
    """يبدّل قائمة المرشحين بقائمة وهمية ويعدّ مرات المسح الفعلي."""
    monkeypatch.setattr(TextMeter, "_selected", {})
    monkeypatch.setattr(TextMeter, "_selected_for", None)
    scans = []
    original = TextMeter._select_font_path

    def counting(self, key, bold, candidates):
        scans.append((key, bold))
        return original(self, key, bold, candidates)

    monkeypatch.setattr(TextMeter, "_select_font_path", counting)

    def use(paths):
        monkeypatch.setattr(TextMeter, "_all_paths", paths)
        return paths
    return use, scans


def test_font_path_identical_lookups_scan_candidates_once(fake_fonts):
    use, scans = fake_fonts
    use(["/f/DejaVuSans.ttf", "/f/arial.ttf", "/f/Arial-Bold.ttf"])
    first = TextMeter()._font_path("Arial")
    assert TextMeter()._font_path("ARIAL") == TextMeter()._font_path("arial", 0) == first
    assert scans == [("arial", False)]
    TextMeter()._font_path(None, False)          # None → "arial" نفس الاختيار
    assert scans == [("arial", False)]
    TextMeter()._font_path("Arial", True)
    TextMeter()._font_path("Arial", 1)
    assert scans == [("arial", False), ("arial", True)]


def test_font_path_keeps_priority_and_bold_ordering(fake_fonts):
    use, _ = fake_fonts
    use(["/f/arial/DejaVuSans.ttf",               # المجلد لا يُحسب، الاسم فقط
         "/f/z/ArialBold.ttf", "/f/z/ARIAL.ttf", "/f/a/Arial-Bold.ttf",
         "/f/Times New Roman.ttf", "/f/NotoSansArabic-Regular.ttf"])
    meter = TextMeter()
    assert meter._font_path("Arial") == "/f/z/ARIAL.ttf"              # العادي للعادي (مش ArialBold)
    assert meter._font_path("Arial", True) == "/f/a/Arial-Bold.ttf"   # عريض ثم أبجدي
    assert meter._font_path("Times New Roman") == "/f/Times New Roman.ttf"
    assert meter._font_path("Sultan bold") == "/f/z/ARIAL.ttf"        # بديل arial أولًا
    assert meter._font_path("dejavu") == "/f/arial/DejaVuSans.ttf"
    for name in ("Arial", "Times New Roman", "Sultan bold", "Missing", "noto sans arabic"):
        for bold in (False, True):
            assert meter._font_path(name, bold) == meter._select_font_path(
                (name or "Arial").lower(), bold, TextMeter._all_paths)

    use(["/f/Foo.ttf", "/f/Bar-Bold.ttf"])
    assert meter._font_path("Missing") == "/f/Foo.ttf"                # أول مرشح
    assert meter._font_path("Missing", True) == "/f/Foo.ttf"
    use([])
    assert meter._font_path("Arial") is None
    assert meter._font("Arial", 10, False) is None


def test_font_path_cache_never_leaks_after_candidates_change(fake_fonts):
    use, scans = fake_fonts
    use(["/f/arial.ttf"])
    assert TextMeter()._font_path("Arial") == "/f/arial.ttf"
    use(["/g/Arial-Regular.ttf"])                                     # قائمة جديدة
    assert TextMeter()._font_path("Arial") == "/g/Arial-Regular.ttf"
    paths = use(["/h/DejaVuSans.ttf"])
    assert TextMeter()._font_path("Arial") == "/h/DejaVuSans.ttf"
    paths.insert(0, "/h/arial.ttf")                                   # تعديل في المكان
    assert TextMeter()._font_path("Arial") == "/h/arial.ttf"
    use([])
    assert TextMeter()._font_path("Arial") is None
    assert len(scans) == 5


@pytest.mark.parametrize("url", [
    "/api/board/2026-04-10/export.docx",
    "/api/duty/2026-04-10/export.docx",
    "/api/afraad/2026-04-10/export.docx",
    "/api/campaign/2026-04-10/export.docx",
])
def test_daily_exports_are_a4_and_reopen(client, url):
    response = client.get(url)
    assert response.status_code == 200
    doc = Document(io.BytesIO(response.data))
    section = doc.sections[0]
    assert (section.page_width.twips, section.page_height.twips) == (11906, 16838)
    assert doc.paragraphs is not None

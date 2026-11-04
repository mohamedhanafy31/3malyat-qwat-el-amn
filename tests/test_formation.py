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


def test_morning_docx_landscape_four_tables_rtl_title_slots_and_emergency_section():
    output = build_docx(build(_data(), DAY, "morning"))
    document = Document(BytesIO(output.getvalue()))
    assert document.sections[0].orientation == 1  # بالعرض
    table = document.tables[0]
    assert len(table.columns) == 4 * 3 + 3  # 4 جداول × (الاسم/التسليح/رقم السلاح) + 3 فواصل
    texts = [cell.text for row in table.rows for cell in row.cells]
    assert "1-" in texts and "2-" in texts and "3-" in texts
    assert "طارئة 11 (11:59ص)" in texts and "خدمات طارئة قبل 12ظ" in texts
    assert "الاسم" in texts and "رقم السلاح" in texts
    xml = _xml(output)
    assert "bidiVisual" in xml
    assert "خط تشكيل صباحي عن يوم الثلاثاء الموافق 20/10/2026م" in xml


def test_morning_excludes_night_times():
    data = _data()
    data["day_assignments"][DAY].append({"id": "A4", "name": "حملة ليل", "section": "الخدمات الطارئة",
                                         "shift": "صباحية", "time": "12 ليل", "conscript_count": 4})
    names = [b["name"] for b in build(data, DAY, "morning")["blocks"]]
    assert "حملة ليل" not in names


def test_basic_weapon_comes_only_from_counts_for_each_shift():
    data = _data()
    data["counts_template"]["entries"].append(
        {"id": "CNT-3", "name": "بدون تسليح", "block": "صباحية", "count": 1, "weapon": ""})
    data["reference_lists"] = {"afraad_basic": [{"since": "2026-01-01", "items": [
        {"id": "AB-1", "name": "أساسية"}, {"id": "AB-2", "name": "ليلية خدمة"},
        {"id": "AB-3", "name": "بدون تسليح"}]}]}
    data["day_afraad"] = {DAY: {key: {"weapon": "خرطوش"} for key in ("AB-1", "AB-2", "AB-3")}}
    morning = {b["name"]: b["weapons"] for b in build(data, DAY, "morning")["blocks"]}
    assert morning["أساسية"] == ["آلي"] * 3
    assert morning["بدون تسليح"] == [""]
    night = {b["name"]: b["weapons"] for b in build(data, DAY, "night")["blocks"]}
    assert night["ليلية خدمة"] == ["آلي", "كلبش"]


def test_night_uses_archive_template_and_basic_pm_strength():
    result = build(_data(), DAY, "night")
    assert [b["name"] for b in result["blocks"]] == ["ليلية خدمة"]
    assert result["blocks"][0]["weapons"] == ["آلي", "كلبش"]
    output = build_docx(result)
    document = Document(BytesIO(output.getvalue()))
    table = document.tables[0]
    assert document.sections[0].orientation == 0  # زي ملف الأرشيف
    texts = [cell.text for row in table.rows for cell in row.cells]
    # العنوان الأول بنفس شكل القالب: الخدمة + «التسليح» + «رقم السلاح»، وتحته خانتين بعدد القوام.
    assert texts[:3] == ["ليلية خدمة", "التسليح", "رقم السلاح"]
    assert "1-" in texts and "2-" in texts and "3-" not in texts
    assert LAST_FIT["page_count"] == 1


def _blocks(n, count=1):
    return [{"name": f"خدمة {i}", "title": f"خدمة {i}", "count": count,
             "weapons": ["آلي"] * count, "kind": "basic", "time": ""} for i in range(n)]


def test_heavy_morning_shrinks_font_but_stays_one_page():
    dto = {"title": "اختبار", "shift": "morning", "day": DAY, "blocks": _blocks(80),
           "totals": {"services": 80, "conscripts": 80}, "warnings": []}
    build_docx(dto)
    assert LAST_FIT["page_count"] == 1 and LAST_FIT["halves"] == 4
    assert 6.5 <= LAST_FIT["size_pt"] < 12


def test_big_services_go_to_a_separate_page_and_split_with_continuation():
    blocks = _blocks(3) + [{"name": "ندوة", "title": "ندوة", "count": 120, "weapons": [],
                            "kind": "basic", "time": ""}]
    dto = {"title": "خط تشكيل صباحي عن يوم الأربعاء الموافق 26/8/2026م", "shift": "morning", "day": DAY,
           "blocks": blocks, "totals": {"services": 4, "conscripts": 123}, "warnings": []}
    output = build_docx(dto)
    assert LAST_FIT["page_count"] == 2
    document = Document(BytesIO(output.getvalue()))
    cells = {cell.text for table in document.tables for row in table.rows for cell in row.cells}
    assert "ندوة (تابع)" in cells
    assert any("(الخدمات الكبيرة)" in p.text for p in document.paragraphs)
    first_page = {cell.text for row in document.tables[0].rows for cell in row.cells}
    assert "ندوة" not in first_page


def test_impossible_page_raises():
    heavy = {"title": "اختبار", "shift": "morning", "day": DAY, "blocks": _blocks(400),
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


def test_emergency_count_comes_only_from_the_count_field_with_one_blank_slot_minimum():
    data = _data()
    data["day_assignments"][DAY] = [
        {"id": "B1", "name": "ترحيلة الاسماعيلية", "section": "الخدمات الطارئة", "time": "8ص",
         "conscript_count": 0, "conscripts": [{"class": "مج", "count": 1}], "weapon": "آلي"},
        {"id": "B2", "name": "جنائي خاصة", "section": "الخدمات الطارئة", "time": "8ص",
         "conscript_count": 0, "weapon": "آلي"},
    ]
    blocks = {block["name"]: block for block in build(data, DAY, "morning")["blocks"]}
    # القوام («1 مج») مش بيتحسب؛ خانة فاضية واحدة لحد ما العدد يتكتب.
    assert blocks["ترحيلة الاسماعيلية"]["count"] == 1 and blocks["ترحيلة الاسماعيلية"]["weapons"] == ["آلي"]
    assert blocks["جنائي خاصة"]["count"] == 1



def test_no_serial_weapons_merge_with_the_serial_cell():
    from docx.oxml.ns import qn
    from backend.formation import _slot_weapons, has_no_serial
    for weapon in ("دونك", "كلبش", "قيد حديدي", "قيد حديدى", "درع وعصا", "درع و عصا", "عصا"):
        assert has_no_serial(weapon)
    for weapon in ("آلي", "خرطوش", "فض", ""):
        assert not has_no_serial(weapon)
    assert _slot_weapons("درع و عصا", 2) == ["درع وعصا"] * 2
    dto = {"title": "خط", "shift": "morning", "day": DAY, "blocks": [
        {"name": "مسلحة", "title": "مسلحة", "count": 1, "weapons": ["آلي"], "kind": "basic", "time": ""},
        {"name": "دونك", "title": "دونك", "count": 1, "weapons": ["دونك"], "kind": "basic", "time": ""}]}
    table = Document(BytesIO(build_docx(dto).getvalue())).tables[0]
    cells = [(tc.grid_span, "".join(t.text or "" for t in tc.iter(qn("w:t"))))
             for row in table.rows for tc in row._tr.tc_lst]
    assert (2, "دونك") in cells and (1, "آلي") in cells
    night = {**dto, "shift": "night"}
    rows = Document(BytesIO(build_docx(night).getvalue())).tables[0]._tbl.tr_lst
    texts = [[("".join(t.text or "" for t in tc.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")),
               tc.grid_span) for tc in tr.tc_lst] for tr in rows]
    # الخدمة التانية في النص الشمال: دونك خدت خانتها + خانة الرقم
    assert any(("دونك", 2) in row for row in texts)
    assert any(("آلي", 1) in row for row in texts)


def test_court_from_counts_appears_on_the_morning_line_at_8am():
    data = _data()
    data["counts_template"]["entries"].append(
        {"id": "CNT-9", "name": "المحكمة", "block": "طوارئ", "count": 5, "weapon": ""})
    blocks = build(data, DAY, "morning")["blocks"]
    court = next(block for block in blocks if block["name"] == "المحكمة")
    assert (court["count"], court["time"], court["kind"]) == (5, "8ص", "emergency")
    assert blocks.index(court) < [block["name"] for block in blocks].index("طارئة 11")
    assert not any(block["name"] == "المحكمة" for block in build(data, DAY, "night")["blocks"])
    # لو متسجلة على اللوحة كمان ماتتكررش، وميعادها الفاضي بيبقى 8ص
    data["day_assignments"][DAY].append({"id": "A9", "name": "المحكمة", "section": "الخدمات الطارئة",
                                         "shift": "صباحية", "time": "", "conscript_count": 5, "weapon": "دونك"})
    courts = [block for block in build(data, DAY, "morning")["blocks"] if block["name"] == "المحكمة"]
    assert len(courts) == 1 and courts[0]["time"] == "8ص" and courts[0]["weapons"] == ["دونك"] * 5


def test_slash_separated_weapons_go_to_consecutive_slots():
    from backend.formation import _slot_weapons
    assert _slot_weapons("آلي/فيدرال/خرطوش", 3) == ["آلي", "فيدرال", "خرطوش"]
    assert _slot_weapons("آلي/خرطوش", 2) == ["آلي", "خرطوش"]
    assert _slot_weapons("الي/فيدرال", 4) == ["آلي", "فيدرال", "فيدرال", "فيدرال"]

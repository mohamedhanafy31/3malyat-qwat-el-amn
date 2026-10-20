"""اختبارات صيغة أرشيف يومية الأفراد الأخيرة."""
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from docx import Document
from lxml import etree

from backend.afraad_export import LAST_FIT, build_docx


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = next((path for path in (ROOT / "../../2026/9/28").glob("28-9-2026 *.docx")
                if "افراد" in path.name), ROOT / "../../2026/9/28/28-9-2026 أفراد.docx")
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def _spans(row):
    return [int(node.get("{%(w)s}val" % NS))
            if (node := cell.find("w:tcPr/w:gridSpan", NS)) is not None else 1
            for cell in row._tr.findall("w:tc", NS)]


def structure_signature(document):
    section = document.sections[0]
    table = document.tables[0]
    return {
        "page": (section.page_width.twips, section.page_height.twips,
                 section.top_margin.twips, section.right_margin.twips,
                 section.bottom_margin.twips, section.left_margin.twips),
        "grid": tuple(int(column.get("{%(w)s}w" % NS))
                    for column in table._tbl.tblGrid.gridCol_lst),
        "rows": tuple(tuple(_spans(row) for row in table.rows[:23])),
    }


def _basic_rows():
    names = [f"خدمة {index}" for index in range(7)]
    names += ["كمين 109 - بيك اب", "كمين 109 - مدرعة"]
    names += [f"خدمة {index}" for index in range(9, 21)]
    return [{"name": name, "morning": {"name": "", "phone": ""},
             "night": {"name": "", "phone": ""}, "count": "", "weapon": "",
             "schedule": ""} for name in names]


def _doc(basic=None, occasional=None, officer_pairs=None):
    return Document(build_docx({"date": "2026-09-28", "basic": basic or _basic_rows(),
                                "occasional": occasional or [],
                                "officer_pairs": officer_pairs or []}))


@pytest.mark.skipif(not ARCHIVE.exists(), reason="latest archive is not present")
def test_fixed_structure_matches_28_september_archive():
    expected = structure_signature(Document(ARCHIVE))
    actual = structure_signature(_doc())
    assert actual == expected


def test_basic_mapping_109_and_literal_values():
    rows = _basic_rows()
    rows[0].update({
        "name": "خدمة حرفية",
        "morning": {"name": "نص حر / كما هو", "phone": ""},
        "count": " 2 مجند (صبح) / 3 مجند (ليل) ",
        "weapon": "الي + كلبش",
        "schedule": "11 ص حتى الانتهاء",
    })
    doc = _doc(rows)
    text = "\n".join(cell.text for row in doc.tables[0].rows for cell in row.cells)
    rows.append({"name": "كمين شرق النفق المستحدث",
                 "morning": {}, "night": {}, "count": "", "weapon": "",
                 "schedule": ""})
    doc = _doc(rows)
    text = "\n".join(cell.text for row in doc.tables[0].rows for cell in row.cells)
    assert "كمين شرق النفق المستحدث" in text
    assert "2 مجند (صبح) / 3 مجند (ليل)" in text
    assert "11 ص حتى الانتهاء" in text
    assert [cell.text for cell in doc.tables[0].rows[8].cells[:4]] == [
        "", "كمين 109", "كمين 109", "بيك اب"]
    assert [cell.text for cell in doc.tables[0].rows[9].cells[:4]] == [
        "", "كمين 109", "كمين 109", "مدرعة"]


def test_linked_personnel_phone_and_emergency_officer_label():
    rows = _basic_rows()
    rows[0]["morning"] = {"person_id": "IND-1", "name": "شريف صلاح جودة احمد",
                           "role": "أمين شرطة", "phone": "01012345678"}
    doc = _doc(rows, [{"label": "تفتيش فيصل", "officers": [{
        "name": "حسام رضوان", "short_name": "حسام رضوان", "role": "مقدم",
        "category": "officers"}], "personnel": [], "time": "9ص",
        "weapon": "دونك", "conscript_count": 1}])
    text = "\n".join(cell.text for row in doc.tables[0].rows for cell in row.cells)
    assert "ا.ش/ شريف صلاح جودة" in text
    assert "01012345678" in text
    assert "مقدم/ حسام رضوان" in text
    assert "9ص" in text
    assert '—' not in text


def test_emergency_conscript_columns_use_total_and_classes():
    doc = _doc(occasional=[{"label": "حراسة", "conscripts": [
        {"class": "حفظ نظام", "count": 5}, {"class": "دونك", "count": 5}],
        "conscript_count": 0}, {"label": "صف صريح", "conscript_count": 10}])
    rows = doc.tables[0].rows
    assert any("10" in cell.text for row in rows for cell in row.cells)
    assert any("حفظ نظام + دونك" in cell.text for row in rows for cell in row.cells)


def test_many_derived_officer_pairs_and_emergency_rows_still_fit_one_page():
    pairs = [{"label": f"خدمة ضابط {i}", "person": "مقدم/ ضابط قصير"} for i in range(7)]
    occasional = [{"label": f"طوارئ {i}", "conscript_count": 10,
                   "weapon": "حفظ نظام + دونك", "time": "9ص"} for i in range(12)]
    _doc(occasional=occasional, officer_pairs=pairs)
    assert LAST_FIT["ratio"] <= 0.94


def test_horizontal_emergency_row_uses_latest_six_cell_shape():
    doc = _doc(occasional=[{"pairs": [
        {"label": "المنطقة الحره ليل", "person": "مقدم/ حسام رضوان"},
        {"label": "بتروجيت صبح", "person": "م.اول / أحمد فوزي"},
        {"label": "قنصلية صبح", "person": "نقيب/عبدالرحمن طارق"},
    ]}])
    row = doc.tables[0].rows[23]
    assert _spans(row) == [2, 4, 2, 3, 3, 2]
    assert row.cells[0].text == "المنطقة الحره ليل"
    assert "نقيب/عبدالرحمن طارق" in [cell.text for cell in row.cells]


def test_empty_day_is_reopenable_and_fits_one_page():
    doc = _doc()
    reopened = Document(BytesIO(build_docx({"date": "2026-09-29", "basic": [],
                                             "occasional": []}).getvalue()))
    assert len(reopened.tables) == 1
    assert len(doc.tables[0].rows) == 23
    assert len(reopened.tables[0].rows) == 24
    assert LAST_FIT["ratio"] <= 0.94


def test_linked_slot_prints_short_label_not_stored_role_text():
    """الاسم المخزّن في الخانة «رتبة/ اسم»: التصدير يبني الاختصار من اسم الفرد نفسه."""
    from backend.afraad_export import _person_text
    slot = {"name": "معاون شرطة ثالث/ محمد عطية منصور نصار", "full_name": "محمد عطية منصور نصار",
            "person_id": "IND-042", "role": "معاون شرطة ثالث", "phone": "01210908819"}
    assert _person_text(slot) == "م.ش/ محمد عطية منصور\n01210908819"

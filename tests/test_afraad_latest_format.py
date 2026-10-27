"""اختبارات صيغة أرشيف يومية الأفراد الأخيرة."""
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from docx import Document
from lxml import etree

from backend.afraad_export import LAST_FIT, build_docx


ROOT = Path(__file__).resolve().parents[1]
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def _tcs(row):
    from docx.table import _Cell
    return [_Cell(tc, row) for tc in row._tr.findall("w:tc", NS)]


def _spans(row):
    return [int(node.get("{%(w)s}val" % NS))
            if (node := cell.find("w:tcPr/w:gridSpan", NS)) is not None else 1
            for cell in row._tr.findall("w:tc", NS)]


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


def _pr(ppr):
    return ppr


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
    rows = doc.tables[0].rows
    assert [c.text for c in _tcs(rows[8])[:3]] == ["", "كمين 109", "بيك اب"]
    assert [c.text for c in _tcs(rows[9])[:3]] == ["", "", "مدرعة"]   # الاسم مدموج رأسيًا


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
    assert LAST_FIT["ratio"] <= 1.0


def test_horizontal_emergency_row_has_two_pairs_per_row_like_real_files():
    doc = _doc(occasional=[{"pairs": [
        {"label": "المنطقة الحره ليل", "person": "مقدم/ حسام رضوان"},
        {"label": "بتروجيت صبح", "person": "م.اول / أحمد فوزي"},
        {"label": "قنصلية صبح", "person": "نقيب/عبدالرحمن طارق"},
    ]}])
    rows = doc.tables[0].rows
    assert _spans(rows[23]) == [4, 3, 3, 3]
    assert [c.text for c in _tcs(rows[23])] == [
        "المنطقة الحره ليل", "مقدم/ حسام رضوان", "بتروجيت صبح", "م.اول / أحمد فوزي"]
    # الزوج الناقص: خلايا فارغة بلا شرطات تعبئة
    assert [c.text for c in _tcs(rows[24])] == ["قنصلية صبح", "نقيب/عبدالرحمن طارق", "", ""]
    fills = [c.find("w:tcPr/w:shd", NS).get("{%(w)s}fill" % NS) for c in rows[23]._tr.findall("w:tc", NS)]
    assert fills == ["F2F2F2", "auto", "F2F2F2", "auto"]


def test_empty_day_is_reopenable_and_fits_one_page():
    doc = _doc()
    reopened = Document(BytesIO(build_docx({"date": "2026-09-29", "basic": [],
                                             "occasional": []}).getvalue()))
    assert len(reopened.tables) == 1
    assert len(doc.tables[0].rows) == 23        # رأس + 21 خدمة + عنوان الطوارئ
    assert len(reopened.tables[0].rows) == 24
    assert LAST_FIT["ratio"] <= 1.0


def test_linked_slot_prints_short_label_not_stored_role_text():
    """الاسم المخزّن في الخانة «رتبة/ اسم»: التصدير يبني الاختصار من اسم الفرد نفسه."""
    from backend.afraad_export import _person_text
    slot = {"name": "معاون شرطة ثالث/ محمد عطية منصور نصار", "full_name": "محمد عطية منصور نصار",
            "person_id": "IND-042", "role": "معاون شرطة ثالث", "phone": "01210908819"}
    assert _person_text(slot) == "م.ش/ محمد عطية منصور\n01210908819"


# ---- أرشيف 21-10: خصائص الشكل المنسوخة من الملف الحقيقي ----

def _all_rows(doc):
    return doc.tables[0]._tbl.findall("w:tr", NS)


def test_grid_margins_and_widths_come_from_real_template():
    doc = _doc(occasional=[{"label": "طوارئ", "conscript_count": 3, "weapon": "آلي", "time": "8ص"}])
    table = doc.tables[0]
    grid = [int(c.get("{%(w)s}w" % NS)) for c in table._tbl.tblGrid.gridCol_lst]
    assert len(grid) == 14 and grid[0] == 8 and grid[13] == 18     # الشرائح الثابتة
    logical = [grid[1], grid[2] + grid[3], grid[4] + grid[5], grid[6] + grid[7] + grid[8],
               grid[9] + grid[10], grid[11], grid[12]]
    from backend.afraad_export import LOGICAL_RANGES
    for width, (low, high) in zip(logical, LOGICAL_RANGES):
        assert low <= width <= high
    assert table._tbl.tblPr.find("w:tblW", NS).get("{%(w)s}w" % NS) == "11217"
    assert doc.sections[0].top_margin.twips == 284
    for tr in _all_rows(doc):
        pr = tr.find("w:trPr", NS)
        counts = {}
        for tag in ("gridBefore", "gridAfter"):
            node = pr.find("w:" + tag, NS) if pr is not None else None
            counts[tag] = int(node.get("{%(w)s}val" % NS)) if node is not None else 0
        before = counts["gridBefore"]
        spans = 0
        for tc in tr.findall("w:tc", NS):
            gs = tc.find("w:tcPr/w:gridSpan", NS)
            n = int(gs.get("{%(w)s}val" % NS)) if gs is not None else 1
            width = int(tc.find("w:tcPr/w:tcW", NS).get("{%(w)s}w" % NS))
            start = before + spans
            spans += n
            assert abs(width - sum(grid[start:start + n])) <= 4
        assert before + spans + counts["gridAfter"] == len(grid)


def test_no_exact_heights_no_arial_no_extra_trailing_paragraph():
    doc = _doc(occasional=[{"label": "طوارئ", "conscript_count": 3, "weapon": "آلي", "time": "8ص"}])
    xml = etree.tostring(doc.element).decode()
    assert "hRule" not in xml
    assert "Arial" not in xml
    body_paragraphs = [c for c in doc.element.body if c.tag.endswith("}p")]
    assert len(body_paragraphs) == 3          # العنوان + فقرة فاصلة + الفقرة الختامية الحقيقية


def test_serial_column_keeps_auto_numbering_and_name_phone_are_two_paragraphs():
    rows = _basic_rows()
    rows[0]["morning"] = {"name": "م.ش/ محمد", "phone": "01000000000"}
    doc = _doc(rows)
    tr = _all_rows(doc)[1]
    first = tr.findall("w:tc", NS)[0]
    assert first.find("w:p/w:pPr/w:numPr/w:numId", NS).get("{%(w)s}val" % NS) == "4"
    assert first.find("w:p/w:pPr/w:pStyle", NS).get("{%(w)s}val" % NS) == "ListParagraph"
    morning = tr.findall("w:tc", NS)[2]
    paragraphs = morning.findall("w:p", NS)
    assert ["".join(t.text for t in p.iter("{%(w)s}t" % NS)) for p in paragraphs] == ["م.ش/ محمد", "01000000000"]
    for p in paragraphs:
        spacing = p.find("w:pPr/w:spacing", NS)
        assert spacing.get("{%(w)s}before" % NS) == "20" and spacing.get("{%(w)s}after" % NS) == "20"


def test_fonts_follow_real_file_per_area_and_title_is_real_style():
    doc = _doc(occasional=[{"label": "طوارئ", "conscript_count": 3, "weapon": "آلي", "time": "8ص"}])
    rows = _all_rows(doc)
    base = rows[1].findall("w:tc", NS)[1].find("w:p/w:r/w:rPr/w:rFonts", NS)
    assert base.get("{%(w)s}cs" % NS) == "Times New Roman" and base.get("{%(w)s}ascii" % NS) is None
    emergency = rows[-1].findall("w:tc", NS)[0].find("w:p/w:r/w:rPr/w:rFonts", NS)
    assert emergency.get("{%(w)s}ascii" % NS) == "Bahnschrift SemiBold"
    assert emergency.get("{%(w)s}cs" % NS) in (None, "Times New Roman")
    title = doc.paragraphs[0]._p.find("w:r/w:rPr", NS)
    assert title.find("w:rFonts", NS).get("{%(w)s}cs" % NS) == "AdvertisingExtraBold"
    assert title.find("w:u", NS) is not None and title.find("w:rtl", NS) is not None
    assert int(title.find("w:sz", NS).get("{%(w)s}val" % NS)) in (20, 24)
    assert title.find("w:sz", NS) is not None
    assert "الأربعاء" in doc.paragraphs[0].text or "28/9/2026" in doc.paragraphs[0].text


def test_sizes_stay_in_real_range_and_fit_failure_only_when_impossible():
    occasional = [{"label": f"طوارئ {i}", "conscript_count": 10, "weapon": "آلي", "time": "9ص"}
                  for i in range(300)]
    from backend.export_fit import PageFitError
    with pytest.raises(PageFitError):
        _doc(occasional=occasional)
    _doc(occasional=occasional[:20])
    sizes = {int(n.get("{%(w)s}val" % NS)) for n in _doc().element.iter("{%(w)s}sz" % NS)}
    assert sizes <= {12, 14, 16, 18, 20, 24, 40}


def test_afraad_columns_follow_each_days_content_within_real_ranges():
    long = {"name": "فرد طويل الاسم جدا جدا جدا ومعه كلمات كثيرة اخرى هنا", "phone": "01000000000",
            "person_id": "", "role": ""}
    rows = _basic_rows()
    for index in range(4):
        rows[index] = {**rows[index], "morning": long, "night": long,
                       "count": "(1مجند) صبح + 1 سائق (1مجند) ليل"}
    _doc(basic=rows)
    wide = list(LAST_FIT["logical"])
    _doc()
    plain = list(LAST_FIT["logical"])
    assert wide != plain
    assert sum(wide) == sum(plain)

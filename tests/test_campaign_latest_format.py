from io import BytesIO

from docx import Document
from docx.oxml.ns import qn

from backend.campaign_export import CHECKPOINT_SPANS, DELIVERY_SPANS, GRID_WIDTHS, PLATE_SPANS, build_docx


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
    assert [node.get(qn('w:val')) if node is not None else None for node in spans[:5]] == [None, '2', '5', '3', '4']
    plate_tcs = table.rows[-1]._tr.findall(qn('w:tc'))
    assert [tc.grid_span for tc in plate_tcs] == PLATE_SPANS == [2, 1, 2, 2, 2, 3, 3]
    delivery_head = next(row for row in table.rows if row.cells[1].text == "الخدمة")._tr.findall(qn('w:tc'))
    assert [tc.grid_span for tc in delivery_head] == DELIVERY_SPANS == [1, 3, 6, 3, 2]
    # عرض كل خانة = مجموع أعمدتها، وهوامش الخانات صفر زي الأرشيف.
    for tr in table._tbl.tr_lst:
        column = 0
        for tc in tr.tc_lst:
            assert tc.width.twips == sum(GRID_WIDTHS[column:column + tc.grid_span])
            column += tc.grid_span
    assert table._tbl.tblPr.find(qn('w:tblCellMar')) is not None
    assert table.rows[0].cells[0].text == "يومية المركبات اليوم الثلاثاء 29/9/2026م"
    values = _text(doc)
    assert "10." in values and "3279ب13" in values and "ب15/5217" in values
    assert "مايك ايفكو" in values and "ـــــ" not in values
    assert [c.width.twips for c in table.rows[0].cells[:1]] == [sum(GRID_WIDTHS)]
    assert values.count("1.") == 1 and "1." == _delivery_rows(payload)[0][0]


def test_latest_format_empty_day_is_reopenable():
    payload = {"date": "2026-09-29", "posts": [], "lorries": [], "services": [],
               "daily": [], "appointments": [], "plates": {"rows": []}}
    doc = Document(BytesIO(build_docx(payload).read()))
    assert len(doc.tables) == 1
    assert len(doc.tables[0].rows) == 4


def test_archive_font_sizes_and_no_shrink_to_one_page():
    # الأرشيف: العنوان 14، الارتكازات 9، خطوط السير 11 — والملف بيكمّل صفحة تانية عادي.
    delivery = {"name": "خدمة", "driver": {"kind": "text", "name": "سائق"},
                "vehicle": {"plate": "ب15/5217", "type": "بيك اب", "origin": "internal"}}
    post = {"number": "1.", "name": "ارتكاز", "driver_text": "سائق", "vehicle": None,
            "plate_text": "1234ب13", "type_text": "بيك اب"}
    doc = Document(BytesIO(build_docx(_payload(posts=[post] * 12, services=[delivery] * 40)).read()))
    rows = doc.tables[0].rows
    size = lambda row, i=1: row.cells[i].paragraphs[0].runs[0].font.size.pt
    assert size(rows[0], 0) == 14 and size(rows[2]) == 9 and size(rows[-1]) == 11


def test_daily_driver_without_vehicle_spans_the_row():
    daily = [{"name": "سائق بورتوفيق", "driver": {"kind": "text", "name": "نصر محمد"}, "vehicle": None}]
    services = [{"name": "ترحيلة", "driver": {"kind": "text", "name": "عمرو"}, "vehicle": None}]
    doc = Document(BytesIO(build_docx(_payload(services=services, daily=daily)).read()))
    spans = [[tc.grid_span for tc in row._tr.tc_lst] for row in doc.tables[0].rows[-2:]]
    assert spans == [[1, 3, 6, 3, 2], [1, 5, 9]]


def _delivery_rows(payload):
    doc = Document(BytesIO(build_docx(payload).read()))
    rows = doc.tables[0].rows
    start = next(i for i, row in enumerate(rows) if row.cells[0].text == "م"
                 and row.cells[1].text == "الخدمة") + 1
    return [[c.text for c in dict.fromkeys(row.cells)] for row in rows[start:]]


def _payload(**extra):
    base = {"date": "2026-09-29", "posts": [], "lorries": [], "services": [],
            "daily": [], "appointments": [], "plates": {"rows": []}}
    base.update(extra)
    return base


def test_driver_has_rank_and_full_name():
    lorries = [
        {"name": "فيصل", "driver": {"kind": "personnel", "name": "محمود عبدالعاطي ابراهيم حسن", "role": "أمين شرطة"}},
        {"name": "القنصلية", "driver": {"kind": "personnel", "name": "علي وحيد علي", "role": "معاون أمن"}},
        {"name": "x", "driver": {"kind": "conscript", "name": "محمد عبد الرحمن سيد"}},
        {"name": "y", "driver": {"kind": "text", "name": "طارق"}},
        {"name": "z", "driver": None},
    ]
    rows = _delivery_rows(_payload(lorries=lorries))
    assert [r[2] for r in rows] == ["ا.ش/ محمود عبدالعاطي ابراهيم حسن", "م.ش/ علي وحيد علي",
                                    "مجند/ محمد عبد الرحمن سيد", "طارق", "ـــــ"]


def test_delivery_plate_has_series():
    lorry = {"name": "فيصل", "driver": None,
             "vehicle": {"plate": "ب13/9416", "type": "لوري", "origin": "internal"}}
    assert _delivery_rows(_payload(lorries=[lorry]))[0][3] == "ب13/9416"


def test_service_label_wording_matches_archive():
    lorries = [{"name": "كـ109"}, {"name": "المحور+المحكمة"},
               {"name": "فيصل + كـ109 +تفتيش الجناين"}]
    services = [{"name": "ترحيلة العاشر", "time": "7ص", "driver": None, "vehicle": None},
                {"name": "مستشفى 9ص", "time": "9ص", "driver": None, "vehicle": None},
                {"name": "قول السلام", "time": "", "driver": None, "vehicle": None},
                {"name": "نيابة عامة 1", "time": "8ص", "party": "عتاقة", "driver": None, "vehicle": None}]
    labels = [r[1] for r in _delivery_rows(_payload(lorries=lorries, services=services))]
    assert labels == ["كـــ 109", "المحور + المحكمة", "فيصل + كـــ 109 + تفتيش الجناين",
                      "ترحيلة العاشر 7ص", "مستشفى 9ص", "قول السلام", "نيابة عامة 8ص"]


def test_empty_appointment_lorries_are_not_printed():
    empty = {"name": "المديرية", "driver": None, "vehicle": None, "attached": []}
    with_driver = {"name": "الأربعين", "driver": {"kind": "text", "name": "سائق جديد"},
                   "vehicle": None, "attached": []}
    with_vehicle = {"name": "الإدارة الجديدة", "driver": None, "attached": [],
                    "vehicle": {"plate": "ب15/5217", "type": "لوري", "origin": "internal"}}
    with_service = {"name": "المديرية + تفتيش", "driver": None, "vehicle": None,
                    "attached": [{"name": "تفتيش"}]}
    rows = _delivery_rows(_payload(appointments=[empty, with_driver, with_vehicle, with_service]))
    assert [r[1] for r in rows] == ["الأربعين", "الإدارة الجديدة", "المديرية + تفتيش"]


def test_driver_prints_full_record_name_not_archive_display():
    from backend.campaign_export import _driver_text
    row = {"driver": {"kind": "personnel", "id": "IND-1", "role": "معاون أمن",
                      "name": "احمد محمود فاروق محمد عزام", "display": "احمد عزام"}}
    assert _driver_text(row) == "م.ش/ احمد محمود فاروق محمد عزام"

"""اختبارات يومية التعيينات: الحساب، الحفظ، ومسار Word."""
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from lxml import etree

from backend import assignments_roster as roster
from backend.assignments import set_officer_state
from backend.board import set_target_officers, target_row_names
from backend import store
from backend.assignments_roster_export import TEMPLATE, build_docx
from backend.export_fit import TextMeter


DAY = "2026-11-21"
SELECTION_DAY = "2026-11-22"


def test_status_text_uses_archive_vocabulary_and_out_state_wins():
    assert roster.status_text({"leave": {"raw_type": "أسبوعية"}}, DAY) == "راحة أسبوعية"
    assert roster.status_text({"leave": {"raw_type": "شهرية", "start": "2026-11-20",
                                           "end": "2026-11-26"}}, DAY) == "راحة شهرية (2/7)"
    assert roster.status_text({"leave": {"raw_type": "نصف شهرية", "start": "2026-11-20",
                                           "end": "2026-11-22"}}, DAY) == "راحة نصف شهرية (2/3)"
    assert roster.status_text({"leave": {"raw_type": "إجازة مصيف"}}, DAY) == "اجازة مصيف"
    assert roster.status_text({"course": {"name": "دورة"}}, DAY) == "فرقة"
    assert roster.status_text({"taqseera": True}, DAY) == "عمل"
    assert roster.status_text({"taqseera": True, "status": "غياب"}, DAY) == "غياب"
    fast = {"services": [{"name": "التدخل السريع — قطاع 1"}]}
    assert roster.status_text(fast, DAY) == "تدخل"
    assert roster.status_text({"services": [{"name": "تدخل سريع ليلية"}]}, DAY) == "تدخل"
    assert roster.status_text({**fast, "group": "خوارج", "bucket": "تقصيرة"}, DAY) == "تدخل"
    assert roster.status_text({**fast, "status": "غياب"}, DAY) == "غياب"


def _service(name, kind="خارجية", shift="صباحية", counted=True):
    return {"name": name, "kind": kind, "shift": shift, "counted": counted}


def test_work_status_includes_one_external_service_without_shift_word():
    row = {"services": [_service("ارتكاز بتروجيت", shift="ليلية")]}
    assert roster.status_text(row, DAY) == "عمل (ارتكاز بتروجيت)"


def test_work_status_joins_external_services_in_day_order_without_duplicates():
    row = {"services": [
        _service("ارتكاز بتروجيت صباحية"),
        _service("المنطقة الحرة", shift="ليلية"),
        _service("ارتكاز بتروجيت", shift="ليلية"),
    ]}
    assert roster.status_text(row, DAY) == "عمل (ارتكاز بتروجيت، المنطقة الحرة)"


def test_work_status_stays_plain_for_internal_guard_and_missing_services():
    assert roster.status_text({"services": [_service("داخلية", "داخلية")]}, DAY) == "عمل"
    assert roster.status_text({"services": [_service("مشرف هدف", "حراسات")]}, DAY) == "عمل"
    assert roster.status_text({}, DAY) == "عمل"


def test_intervention_status_stays_plain_even_when_service_is_external():
    row = {"services": [_service("التدخل السريع", shift="ليلية")]}
    assert roster.status_text(row, DAY) == "تدخل"


def test_explicit_work_status_uses_the_same_external_service_text():
    row = {"status": "عمل", "services": [_service("ارتكاز بتروجيت") ]}
    assert roster.status_text(row, DAY) == "عمل (ارتكاز بتروجيت)"


def _roster_data(data_file):
    data = store.load_data()
    data["officers"] = [
        {"id": "OFF-001", "name": "أحمد علي حسن", "short_name": "أحمد علي",
         "role": "عقيد", "code": "1", "join_date": "2020-01-01", "status": "active"},
        {"id": "OFF-002", "name": "محمود علي حسن", "short_name": "محمود علي",
         "role": "مقدم", "code": "2", "join_date": "2020-01-01", "status": "active"},
        {"id": "OFF-003", "name": "حسن محمود علي", "role": "رائد", "code": "3",
         "join_date": "2020-01-01", "status": "active"},
        {"id": "OFF-004", "name": "طبيب سامي حسن", "role": "نقيب", "code": "4",
         "join_date": "2020-01-01", "status": "active"},
    ]
    data["command_groups"] = {"طبي": ["OFF-004"], "بحث": []}
    data["personnel"] = [
        {"id": "IND-001", "name": "أحمد عمليات", "short_name": "أحمد عمليات",
         "role": "معاون ثالث", "post": "قسم العمليات", "join_date": "2020-01-01",
         "status": "active"},
        {"id": "IND-002", "name": "غير معني", "role": "معاون ثالث", "post": "المخازن",
         "join_date": "2020-01-01", "status": "active"},
    ]
    return data


def test_build_orders_splits_and_puts_doctors_at_the_bottom(data_file):
    payload = roster.build(_roster_data(data_file), DAY)
    assert len(payload["rows"]) == 4
    assert [item["id"] for item in payload["right"]] == ["OFF-001", "OFF-002", "OFF-003"]
    assert payload["left"] == []
    assert [row["name"] for row in payload["doctors"]] == ["طبيب سامي"]
    assert payload["rows"][-1]["name"] == "طبيب سامي"
    assert [item["id"] for item in payload["operations_members"]] == ["IND-001"]
    assert payload["config"]["ops_signer_id"] == "IND-001"


def test_roster_uses_current_force_only(data_file):
    data = _roster_data(data_file)
    data["officers"] = [
        {"id": "OFF-LIVE", "name": "حي على القوة", "role": "عقيد", "code": "1",
         "join_date": "2020-01-01", "status": "active"},
        {"id": "OFF-ARCHIVE", "name": "من الأرشيف", "role": "مقدم", "code": "2",
         "join_date": "2020-01-01", "status": "archived"},
        {"id": "OFF-LEFT", "name": "خرج قبل اليوم", "role": "رائد", "code": "3",
         "join_date": "2020-01-01", "leave_date": "2026-11-20", "status": "active"},
        {"id": "OFF-FUTURE", "name": "يلتحق بعد اليوم", "role": "نقيب", "code": "4",
         "join_date": "2026-11-22", "status": "active"},
    ]
    data["command_groups"] = {"طبي": [], "بحث": []}
    payload = roster.build(data, DAY)
    ids = {item["id"] for item in payload["all_rows"]}
    assert ids == {"OFF-LIVE"}
    assert "من الأرشيف" not in {item["name"] for item in payload["all_rows"]}


def test_outsiders_are_dropped_but_taqseera_remains_and_nonworking_doctors_are_dropped(data_file):
    data = _roster_data(data_file)
    data["leaves"].append({"id": "LV-OUT", "person_id": "OFF-002", "type": "أسبوعية",
                            "start": DAY, "end": DAY, "return_date": "2026-11-22"})
    data["officer_status_periods"] = [{
        "id": "OSP-OUT", "officer_id": "OFF-003", "status": "تكليف ميداني",
        "start": DAY, "end": DAY, "custom": True, "details": "خارج القوة",
    }]
    set_officer_state(data, DAY, "OFF-001", taqseera=True)
    set_officer_state(data, DAY, "OFF-004", status="مرضي")

    payload = roster.build(data, DAY)
    assert {item["id"] for item in payload["rows"]} == {"OFF-001"}
    assert next(item for item in payload["rows"] if item["id"] == "OFF-001")["status"] == "عمل"
    assert "OFF-004" not in {item["id"] for item in payload["doctors"]}
    assert payload["total"] == 6


def test_selection_filters_preview_and_docx_but_targets_are_immune(data_file):
    data = _roster_data(data_file)
    set_target_officers(data, DAY, "مشرف الأهداف", ["OFF-001"])
    set_officer_state(data, DAY, "OFF-003", status="غياب")
    data["day_roster"] = {DAY: {
        "central": 4, "ports": 1, "ops_signer_id": "",
        "excluded_officer_ids": ["OFF-001", "OFF-002"],
    }}

    payload = roster.build(data, DAY)
    ids = {item["id"] for item in payload["rows"]}
    assert ids == {"OFF-004"}
    assert payload["target_officer_ids"] == ["OFF-001"]
    assert payload["total"] == 7
    assert payload["selection"]["total"] == 1
    assert payload["selection"]["selected"] == 0
    assert [item["id"] for item in payload["selectable_officers"]] == ["OFF-002"]

    raw_docx = build_docx(payload).getvalue()
    document = Document(BytesIO(raw_docx))
    text = "\n".join(cell.text for row in document.tables[0].rows for cell in row.cells)
    assert "محمود علي حسن" not in text
    assert "أحمد علي حسن" not in text
    assert "أحمد علي" in text and "طبيب سامي" in text
    assert "غياب" not in text
    assert "الإجمالي: 7" in text
    assert "مشرف الأهداف" not in text
    assert any(cell.text == "الأهداف" for row in document.tables[0].rows for cell in row.cells)


def test_split_targets_move_only_the_two_split_officers_into_the_block(data_file):
    data = _roster_data(data_file)
    set_target_officers(
        data, DAY, "مشرف الأهداف", ["OFF-001", "OFF-002"],
        periods=[
            {"officer_id": "OFF-001", "label": "حتى 4م"},
            {"officer_id": "OFF-002", "label": "من 4م"},
        ],
    )
    set_target_officers(data, DAY, "سوميد", ["OFF-003"])

    payload = roster.build(data, DAY)
    assert [item["id"] for item in payload["target_items"]] == ["OFF-001", "OFF-002", "OFF-003"]
    assert [item["name"] for item in payload["target_items"]] == ["أحمد علي", "محمود علي", "حسن محمود"]
    assert payload["split_target_officer_ids"] == ["OFF-001", "OFF-002"]
    assert {item["id"] for item in payload["rows"]} == {"OFF-004"}
    assert "OFF-001" not in {item["id"] for item in payload["left"] + payload["right"]}
    assert "OFF-002" not in {item["id"] for item in payload["left"] + payload["right"]}
    assert payload["total"] == 9

    raw_docx = build_docx(payload).getvalue()
    document = Document(BytesIO(raw_docx))
    target_cell = next(cell for row in document.tables[0].rows
                       for cell in row.cells if cell.text == "الأهداف")
    assert target_cell.text == "الأهداف"
    assert "مشرف الأهداف" not in target_cell.text
    assert "سوميد" not in target_cell.text
    assert any("حسن محمود" in cell.text
               for row in document.tables[0].rows for cell in row.cells)


def test_search_officers_are_absent_from_main_list_targets_and_selection(data_file):
    data = _roster_data(data_file)
    data["command_groups"]["بحث"] = ["OFF-003"]
    set_target_officers(data, DAY, "مشرف الأهداف", ["OFF-003"])

    payload = roster.build(data, DAY)
    all_ids = {item["id"] for item in payload["rows"] + payload["all_rows"]}
    assert "OFF-003" not in all_ids
    assert "OFF-003" not in payload["target_officer_ids"]
    assert "OFF-003" not in {item["id"] for item in payload["selectable_officers"]}
    assert "OFF-003" not in {item["id"] for item in payload["rows"]}


def test_target_is_kept_even_when_its_computed_state_is_outside(data_file):
    data = _roster_data(data_file)
    set_target_officers(data, DAY, "مشرف الأهداف", ["OFF-003"])
    set_officer_state(data, DAY, "OFF-003", status="غياب")

    payload = roster.build(data, DAY)
    target = next(item for item in payload["target_items"] if item["id"] == "OFF-003")
    assert target["status"] == "غياب"
    assert "OFF-003" in payload["target_officer_ids"]


def test_selection_defaults_to_all_and_persists_with_validation(client):
    response = client.get(f"/api/assignments-roster/{SELECTION_DAY}")
    body = response.get_json()
    assert body["selection"]["total"] == 2
    assert body["selection"]["selected"] == 2
    assert all(item["selected"] for item in body["selectable_officers"])

    invalid = client.put(f"/api/assignments-roster/{SELECTION_DAY}", json={
        "central": 4, "ports": 1, "ops_signer_id": "",
        "excluded_officer_ids": ["OFF-NOT-IN-FORCE"], "revision": body["revision"]})
    assert invalid.status_code == 400, invalid.get_json()

    saved = client.put(f"/api/assignments-roster/{SELECTION_DAY}", json={
        "central": 4, "ports": 1, "ops_signer_id": "",
        "excluded_officer_ids": ["OFF-002"], "revision": body["revision"]})
    assert saved.status_code == 200
    assert saved.get_json()["selection"]["selected"] == 1
    assert saved.get_json()["total"] == 6
    refreshed = client.get(f"/api/assignments-roster/{SELECTION_DAY}").get_json()
    assert "OFF-002" not in {item["id"] for item in refreshed["rows"]}
    assert refreshed["total"] == 6


def test_excluded_officer_is_dropped_when_status_changes_from_work_to_out(data_file):
    data = _roster_data(data_file)
    data["day_roster"] = {DAY: {"excluded_officer_ids": ["OFF-002"]}}
    set_officer_state(data, DAY, "OFF-002", status="مرضي")
    payload = roster.build(data, DAY)
    assert "OFF-002" not in {item["id"] for item in payload["rows"]}
    assert "OFF-002" not in {item["id"] for item in payload["selectable_officers"]}


def test_docx_contains_title_rows_status_and_footer():
    payload = {
        "title": "كشف بأسماء السادة الضباط عن يوم السبت الموافق 21/11/2026م",
        "left": [{"number": "", "role": "عقيد", "name": "أحمد علي", "status": "عمل"}],
        "right": [{"number": 2, "role": "رائد", "name": "محمود حسن", "status": "تدخل"}],
        "doctors": [], "target_items": [], "central": 4, "ports": 1,
        "ops_signer": {"rank": "معاون ثالث", "name": "أحمد عمليات"},
        "chief": {"rank": "رائد", "name": "محمد بحر"},
        "total": 2,
    }
    raw_docx = build_docx(payload).getvalue()
    document = Document(BytesIO(raw_docx))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    text += "\n" + "\n".join(cell.text for row in document.tables[0].rows for cell in row.cells)
    assert payload["title"].replace("/2026", "/ 2026") in text
    assert "أحمد علي" in text and "تدخل" in text
    assert "( 4 ) ضابط امن مركزي" in text
    assert "( 1 ) ضابط امن مواني" in text
    xml = ZipFile(BytesIO(raw_docx)).read("word/document.xml").decode("utf-8")
    assert "قسم العمليات" in xml and "رئيس قسم العمليات" in xml
    assert "()" not in xml
    assert "الإجمالي: 2" in text
    assert len(document.tables[0].rows) >= 3

    table_xml = etree.fromstring(ZipFile(BytesIO(raw_docx)).read("word/document.xml"))
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    rows = table_xml.findall(".//w:tbl/w:tr", ns)
    total_row = rows[-1]
    assert len(total_row.findall("w:tc", ns)) == 1
    assert total_row.find("w:tc/w:tcPr/w:gridSpan", ns).get(
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val") == "8"
    assert "الإجمالي: 2" in "".join(total_row.xpath(".//w:t/text()", namespaces=ns))


def test_every_table_cell_and_merged_cell_is_centered_and_signature_shapes_are_two_edges():
    raw_docx = build_docx({
        "title": "كشف بأسماء السادة الضباط عن يوم السبت الموافق 21/11/2026م",
        "right": [], "left": [], "target_items": [], "doctors": [],
        "footer_categories": [], "total": 0,
        "ops_signer": {"rank": "معاون ثالث", "name": "أحمد عمليات"},
        "chief": {"rank": "رائد", "name": "محمد بحر"},
    }).getvalue()
    ns = {
        "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
        "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
        "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
        "v": "urn:schemas-microsoft-com:vml",
    }
    root = etree.fromstring(ZipFile(BytesIO(raw_docx)).read("word/document.xml"))
    for cell in root.findall(".//w:tbl//w:tc", ns):
        assert cell.find("w:tcPr/w:vAlign", ns).get(
            "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val") == "center"
        assert cell.find(".//w:pPr/w:jc", ns).get(
            "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val") == "center"
    assert [anchor.find("wp:docPr", ns).get("name")
            for anchor in root.findall(".//wp:anchor", ns)] == ["Text Box 4", "Text Box 5"]
    assert [shape.get("id") for shape in root.findall(".//v:shape", ns)] == [
        "Text Box 4", "Text Box 5"]
    # نفس منطق الأرشيف: إزاحة من حافة العمود الشمال (align بيتقرا غلط في LibreOffice/OnlyOffice)
    offsets = {anchor.find("wp:docPr", ns).get("name"):
               int(anchor.find("wp:positionH/wp:posOffset", ns).text)
               for anchor in root.findall(".//wp:anchor", ns)}
    assert offsets["Text Box 4"] == 0                       # قسم العمليات: أقصى الشمال
    assert offsets["Text Box 5"] == (10064 - 4000) * 635    # رئيس العمليات: أقصى اليمين (عرض العمود 10064)
    assert all(anchor.find("wp:positionH", ns).get("relativeFrom") == "column"
               for anchor in root.findall(".//wp:anchor", ns))
    assert {anchor.find("wp:extent", ns).get("cx")
            for anchor in root.findall(".//wp:anchor", ns)} == {"2540000"}
    assert {anchor.find("wp:positionV/wp:posOffset", ns).text
            for anchor in root.findall(".//wp:anchor", ns)} == {"0"}
    assert all(body.get("wrap") == "square"
               for body in root.findall(".//wps:bodyPr", ns))
    table_width = int(root.find(".//w:tbl/w:tblPr/w:tblW", ns).get(
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}w"))
    assert table_width >= 4000
    assert all("mso-position-horizontal-relative:margin;" in shape.get("style", "")
               and "width:200.00pt;" in shape.get("style", "")
               for shape in root.findall(".//v:shape", ns))
    assert "قسم العمليات" in "".join(root.xpath(".//w:t/text()", namespaces=ns))
    assert "رئيس قسم العمليات" in "".join(root.xpath(".//w:t/text()", namespaces=ns))


def test_targets_label_always_has_two_merged_rows_and_font_fits_exact_height():
    raw_docx = build_docx({
        "title": "كشف بأسماء السادة الضباط عن يوم السبت الموافق 21/11/2026م",
        "right": [{"role": "عقيد", "name": "أحمد سمير", "status": "عمل"}],
        "left": [], "target_items": [], "doctors": [],
        "footer_categories": [], "total": 1,
        "ops_signer": {}, "chief": {"rank": "رائد", "name": "محمد بحر"},
    }).getvalue()
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    root = etree.fromstring(ZipFile(BytesIO(raw_docx)).read("word/document.xml"))
    rows = root.findall(".//w:tbl/w:tr", ns)
    label = rows[1].findall("w:tc", ns)[4]
    continuation = rows[2].findall("w:tc", ns)[4]
    assert "".join(label.xpath(".//w:t/text()", namespaces=ns)) == "الأهداف"
    assert label.find("w:tcPr/w:vMerge", ns).get(
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val") == "restart"
    assert continuation.find("w:tcPr/w:vMerge", ns) is not None
    assert "".join(continuation.xpath(".//w:t/text()", namespaces=ns)) == ""
    assert label.xpath(".//w:rPr/w:sz/@w:val", namespaces=ns) == ["28", "28"]
    for row_index, row in enumerate(rows):
        height = int(row.find("w:trPr/w:trHeight", ns).get(
            "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val"))
        for cell_index, cell in enumerate(row.findall("w:tc", ns)):
            sizes = [int(value) for value in cell.xpath(
                ".//w:rPr/w:sz/@w:val", namespaces=ns)]
            if not sizes:
                continue
            span = 1
            merge = cell.find("w:tcPr/w:vMerge", ns)
            if merge is not None and merge.get(
                    "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val") == "restart":
                span = 2
            assert height * span >= max(sizes) * 12.5


def test_worst_case_table_height_fits_one_page_without_libreoffice():
    right = [{"number": i, "role": "نقيب", "name": f"ضابط {i}", "status": "عمل"}
             for i in range(1, 24)]
    left = [{"number": i, "role": "رائد", "name": f"ضابط {i}", "status": "عمل"}
            for i in range(24, 32)]
    doctors = []
    payload = {
        "title": "كشف بأسماء السادة الضباط عن يوم السبت الموافق 21/11/2026م",
        "left": left, "right": right, "doctors": doctors,
        "target_items": [{"role": "رائد", "name": "تقسيم 1", "status": "عمل"},
                         {"role": "نقيب", "name": "تقسيم 2", "status": "عمل"},
                         {"role": "مقدم", "name": "تقسيم 3", "status": "عمل"}],
        "central": 4, "ports": 1, "total": 34,
        "ops_signer": {"rank": "معاون ثالث", "name": "أحمد عمليات"},
        "chief": {"rank": "رائد", "name": "محمد بحر"},
    }
    document = Document(BytesIO(build_docx(payload).getvalue()))
    assert len(document.tables[0]._tbl.tr_lst) == 24
    heights = []
    for row in document.tables[0]._tbl.tr_lst:
        node = row.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}trPr")
        node = node.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}trHeight")
        heights.append(int(node.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val")))
    section = document.sections[0]
    assert heights == [440] * 24
    assert all(row.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}trPr")
                   .find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}trHeight")
                   .get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}hRule") == "exact"
               for row in document.tables[0]._tbl.tr_lst)


def test_row_height_budget_covers_realistic_page_sizes():
    from backend.assignments_roster_export import _available_table_height, row_height_for

    document = Document(TEMPLATE)
    available = _available_table_height(document)
    for count in (24, 32, 40, 48):
        height = row_height_for(document, count)
        assert count * height <= available
        assert height >= 225


def test_archive_row_geometry_and_cell_run_styles_are_cloned():
    payload = {
        "title": "كشف بأسماء السادة الضباط عن يوم السبت الموافق 21/11/2026م",
        "left": [{"number": 24, "role": "م.اول", "name": "اسم كامل يسار", "status": "عمل"}],
        "right": [{"number": 1, "role": "مقدم", "name": "اسم كامل يمين", "status": "تدخل"}],
        "doctors": [], "target_items": [], "central": 4, "ports": 1, "total": 2,
        "ops_signer": {}, "chief": {},
    }
    archive = Path("data/daily_files/2026/5/7/يومية تعيينات الضباط.docx")
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    q = lambda node: etree.tostring(node, method="c14n") if node is not None else b""

    def rows(source):
        source = BytesIO(source) if isinstance(source, bytes) else source
        with ZipFile(source) as z:
            root = etree.fromstring(z.read("word/document.xml"))
        return root.findall(".//w:tbl/w:tr", ns)

    expected = rows(TEMPLATE)
    actual = rows(build_docx(payload).getvalue())
    assert len(actual) == len(expected) == 24
    assert [r.find("w:trPr/w:trHeight", ns).get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val")
            for r in actual] == ["440"] * 24
    for row_index in (0, 1, 6, 15, 20):
        actual_cells = actual[row_index].findall("w:tc", ns)
        expected_cells = expected[row_index].findall("w:tc", ns)
        assert [c.find("w:tcPr/w:tcW", ns).get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}w")
                for c in actual_cells] == [c.find("w:tcPr/w:tcW", ns).get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}w")
                                            for c in expected_cells]
    assert len(actual[-1].findall("w:tc", ns)) == 1
    assert actual[-1].find("w:tc/w:tcPr/w:gridSpan", ns).get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val") == "8"


def test_archive_template_geometry_and_output_geometry_are_preserved():
    archive = Path("data/daily_files/2026/5/7/يومية تعيينات الضباط.docx")

    def xml_part(source, name):
        if isinstance(source, bytes):
            with ZipFile(BytesIO(source)) as z:
                return etree.fromstring(z.read(name))
        with ZipFile(source) as z:
            return etree.fromstring(z.read(name))

    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    template_root = xml_part(TEMPLATE, "word/document.xml")
    archive_root = xml_part(archive, "word/document.xml")
    output_root = xml_part(build_docx({
        "title": "x",
        "left": [{"number": "", "role": "رائد", "name": "أ", "status": "عمل"}
                 for _ in range(4)],
        "right": [], "doctors": [], "target_items": [],
        "central": 4, "ports": 1, "total": 0,
        "ops_signer": {}, "chief": {},
    }).getvalue(), "word/document.xml")

    canonical = lambda node: etree.tostring(node, method="c14n")
    assert canonical(template_root.find(".//w:sectPr", ns)) == canonical(archive_root.find(".//w:sectPr", ns))
    assert canonical(template_root.find(".//w:tblGrid", ns)) == canonical(archive_root.find(".//w:tblGrid", ns))
    assert canonical(output_root.find(".//w:sectPr", ns)) == canonical(template_root.find(".//w:sectPr", ns))
    assert canonical(output_root.find(".//w:tblGrid", ns)) == canonical(template_root.find(".//w:tblGrid", ns))
    for row_index in (0, 6):
        template_row = template_root.findall(".//w:tbl/w:tr", ns)[row_index]
        archive_row = archive_root.findall(".//w:tbl/w:tr", ns)[row_index]
        output_row = output_root.findall(".//w:tbl/w:tr", ns)[row_index]
        for template_cell, archive_cell, output_cell in zip(
                template_row.findall("w:tc", ns), archive_row.findall("w:tc", ns),
                output_row.findall("w:tc", ns)):
            assert canonical(template_cell.find("w:tcPr/w:tcW", ns)) == canonical(archive_cell.find("w:tcPr/w:tcW", ns))
            assert canonical(template_cell.find("w:tcPr/w:tcW", ns)) == canonical(output_cell.find("w:tcPr/w:tcW", ns))


def test_archive_package_parts_outside_document_are_kept_byte_for_byte():
    archive = Path("data/daily_files/2026/5/7/يومية تعيينات الضباط.docx")
    output = build_docx({
        "title": "كشف بأسماء السادة الضباط عن يوم السبت الموافق 21/11/2026م",
        "left": [], "right": [], "doctors": [], "target_items": [],
        "footer_categories": [], "total": 0, "ops_signer": {}, "chief": {},
    }).getvalue()
    with ZipFile(archive) as expected, ZipFile(BytesIO(output)) as actual:
        assert [name for name in expected.namelist() if name != "word/document.xml"]
        for name in expected.namelist():
            if name != "word/document.xml":
                assert actual.read(name) == expected.read(name)


def test_routes_save_defaults_and_reject_stale_revision(client):
    page = client.get("/assignments-roster")
    assert page.status_code == 200
    response = client.get(f"/api/assignments-roster/{DAY}")
    assert response.status_code == 200
    body = response.get_json()
    assert body["central"] == 4 and body["ports"] == 1
    assert client.get(f"/api/assignments-roster/{DAY}/export.docx").status_code == 200

    saved = client.put(f"/api/assignments-roster/{DAY}", json={
        "central": 7, "ports": 2, "ops_signer_id": "", "revision": body["revision"]})
    assert saved.status_code == 200
    assert saved.get_json()["central"] == 7
    stale = client.put(f"/api/assignments-roster/{DAY}", json={
        "central": 8, "ports": 1, "ops_signer_id": "", "revision": body["revision"]})
    assert stale.status_code == 409


def test_day_roster_round_trips_in_default_extras_bundle(data_file):
    def mutate(data):
        roster.store_config(data, DAY, {
            "central": 6, "ports": 3, "ops_signer_id": "IND-001"})

    store.with_data(mutate, [DAY])
    assert store.load_data([DAY])["day_roster"][DAY]["central"] == 6
    assert store.load_data([DAY])["day_roster"][DAY]["footer_categories"] == [
        {"label": "ضابط امن مركزي", "count": 6},
        {"label": "ضابط امن مواني", "count": 3},
    ]
    assert (store.day_folder(DAY) / "extras.json").exists()


def test_all_target_slots_move_every_assigned_officer_to_the_block(data_file):
    data = _roster_data(data_file)
    names = target_row_names(data, DAY)
    for index, name in enumerate(names):
        if index == 0:
            set_target_officers(data, DAY, name, ["OFF-001", "OFF-002"], periods=[
                {"officer_id": "OFF-001", "label": "حتى 4م"},
                {"officer_id": "OFF-002", "label": "من 4م"},
            ])
        else:
            set_target_officers(data, DAY, name, [f"OFF-00{(index % 3) + 1}"])
    payload = roster.build(data, DAY)
    assert set(payload["target_officer_ids"]) == {"OFF-001", "OFF-002", "OFF-003"}
    assert {item["id"] for item in payload["rows"]} == {"OFF-004"}
    assert len(payload["target_items"]) == 3
    assert {item["name"] for item in payload["target_items"]} == {
        "أحمد علي", "محمود علي", "حسن محمود"}
    assert all(item["id"] not in payload["target_officer_ids"]
               for item in payload["right"] + payload["left"])


def test_footer_categories_are_editable_migrated_and_counted(client):
    response = client.get(f"/api/assignments-roster/{SELECTION_DAY}")
    body = response.get_json()
    assert body["footer_categories"] == [
        {"label": "ضابط امن مركزي", "count": 4},
        {"label": "ضابط امن مواني", "count": 1},
    ]
    saved = client.put(f"/api/assignments-roster/{SELECTION_DAY}", json={
        "footer_categories": [{"label": "تصنيف إضافي", "count": 7}],
        "ops_signer_id": "", "revision": body["revision"],
    })
    assert saved.status_code == 200
    result = saved.get_json()
    assert result["footer_categories"] == [{"label": "تصنيف إضافي", "count": 7}]
    assert result["footer_total"] == 7
    assert result["total"] == len(result["rows"]) + len(result["target_officer_ids"]) + 7
    invalid = client.put(f"/api/assignments-roster/{SELECTION_DAY}", json={
        "footer_categories": [{"label": "", "count": 1}],
        "ops_signer_id": "", "revision": result["revision"],
    })
    assert invalid.status_code == 400


def test_real_assignment_api_service_name_is_used_by_roster_preview(client):
    created = client.post(f"/api/assignments/{SELECTION_DAY}", json={
        "name": "التدخل السريع", "kind": "خارجية", "section": "الخدمات أساسية",
        "shift": "صباحية", "officer_ids": ["OFF-001"],
        "personnel_ids": [], "allow_duplicate": True,
    })
    assert created.status_code == 201, created.get_json()
    roster_response = client.get(f"/api/assignments-roster/{SELECTION_DAY}")
    assert roster_response.status_code == 200
    row = next(item for item in roster_response.get_json()["rows"] if item["id"] == "OFF-001")
    assert row["status"] == "تدخل"


def test_external_service_status_is_shared_by_preview_targets_and_docx(data_file):
    data = _roster_data(data_file)
    data["day_assignments"] = {DAY: [{
        "id": "AS-001", "name": "ارتكاز بتروجيت", "kind": "خارجية",
        "section": "الخدمات أساسية", "shift": "ليلية", "officer_ids": ["OFF-001"],
        "personnel_ids": [], "counts_in_summary": True,
    }]}
    set_target_officers(data, DAY, "مشرف الأهداف", ["OFF-001"])

    payload = roster.build(data, DAY)
    target = next(item for item in payload["target_items"] if item["id"] == "OFF-001")
    assert target["status"] == "عمل (ارتكاز بتروجيت)"
    raw_docx = build_docx(payload).getvalue()
    document = Document(BytesIO(raw_docx))
    assert any("عمل (ارتكاز بتروجيت)" in cell.text.replace("\n", "")
               for row in document.tables[0].rows for cell in row.cells)


def test_external_assignment_api_preview_carries_joined_service_names(client):
    for name in ("ارتكاز بتروجيت", "المنطقة الحرة"):
        response = client.post(f"/api/assignments/{SELECTION_DAY}", json={
            "name": name, "kind": "خارجية", "section": "الخدمات أساسية",
            "shift": "صباحية", "officer_ids": ["OFF-001"],
            "personnel_ids": [], "allow_duplicate": True,
        })
        assert response.status_code == 201, response.get_json()
    body = client.get(f"/api/assignments-roster/{SELECTION_DAY}").get_json()
    row = next(item for item in body["rows"] if item["id"] == "OFF-001")
    assert row["status"] == "عمل (ارتكاز بتروجيت، المنطقة الحرة)"


def test_external_notes_use_text_meter_without_overflow_and_keep_grid_width():
    raw_catalog = store.load_data().get("service_catalog") or []
    names = [str(item.get("name") or "").strip() for item in raw_catalog
             if str(item.get("name") or "").strip()]
    names = sorted(dict.fromkeys(names), key=len, reverse=True)[:2]
    assert names, "the real service catalog should contain service names"
    note = f"عمل ({'، '.join(names)})"
    raw_docx = build_docx({
        "title": "كشف بأسماء السادة الضباط عن يوم السبت الموافق 21/11/2026م",
        "right": [{"number": 1, "role": "رائد", "name": "أحمد علي", "status": note}],
        "left": [], "target_items": [], "doctors": [], "footer_categories": [],
        "total": 1, "ops_signer": {}, "chief": {},
    }).getvalue()
    document = Document(BytesIO(raw_docx))
    table = document.tables[0]
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    root = etree.fromstring(ZipFile(BytesIO(raw_docx)).read("word/document.xml"))
    widths = [int(value) for value in root.xpath(
        ".//w:tbl/w:tblGrid/w:gridCol/@w:w", namespaces=ns)]
    template_root = etree.fromstring(ZipFile(TEMPLATE).read("word/document.xml"))
    template_widths = [int(value) for value in template_root.xpath(
        ".//w:tbl/w:tblGrid/w:gridCol/@w:w", namespaces=ns)]
    assert sum(widths) == sum(template_widths)
    assert widths[3] > template_widths[3]

    note_cell = next(cell for row in table.rows for cell in row.cells
                     if names[0] in cell.text)
    lines = note_cell.text.splitlines()
    note_root = etree.fromstring(note_cell._tc.xml.encode("utf-8"))
    sizes = [int(value) / 2 for value in note_root.xpath(
        ".//w:rPr/w:sz/@w:val", namespaces=ns)]
    assert len(lines) in (1, 2)
    assert sizes and min(sizes) >= 7.5
    size = min(sizes)
    meter = TextMeter()
    assert all(meter.text_width(line.strip(), size, True, "Times New Roman") <= widths[3] / 20
               for line in lines)
    row = next(row for row in table.rows if names[0] in row.cells[3].text)
    row_root = etree.fromstring(row._tr.xml.encode("utf-8"))
    height = int(row_root.xpath("./w:trPr/w:trHeight/@w:val", namespaces=ns)[0]) / 20
    assert len(lines) * size * 1.25 <= height

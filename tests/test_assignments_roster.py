"""اختبارات يومية التعيينات: الحساب، الحفظ، ومسار Word."""
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from lxml import etree

from backend import assignments_roster as roster
from backend.assignments import set_officer_state
from backend.board import set_target_officers, target_row_names
from backend import duty
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
    assert roster.status_text({"services": [{"name": "تدخل سريع ليلية"}]}, DAY) == "تدخل ليل"
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


def test_intervention_status_names_the_shift_and_keeps_unknown_plain():
    row = {"services": [_service("التدخل السريع", shift="ليلية")]}
    assert roster.status_text(row, DAY) == "تدخل ليل"
    assert roster.status_text({"services": [_service("التدخل السريع", shift="صباحية")]}, DAY) == "تدخل صبح"
    assert roster.status_text({"services": [
        _service("التدخل السريع", shift="صباحية"),
        _service("التدخل السريع", shift="ليلية"),
    ]}, DAY) == "تدخل صبح + ليل"
    assert roster.status_text({"status": "تدخل", "services": [
        _service("التدخل السريع", shift="صباحية")
    ]}, DAY) == "تدخل صبح"
    assert roster.status_text({"services": [{"name": "تدخل سريع", "shift": "غير معروفة"}]}, DAY) == "تدخل"


def test_intervention_status_is_recognized_by_roster_selection_vocabulary():
    assert all(roster.is_intervention_status(value) for value in (
        "تدخل", "تدخل صبح", "تدخل ليل", "تدخل صبح + ليل"))
    assert not roster.is_intervention_status("عمل (ارتكاز بتروجيت)")


def test_build_exposes_work_and_intervention_counts(data_file):
    data = _roster_data(data_file)
    data["day_assignments"] = {DAY: [
        {"id": "AS-AM", "name": "التدخل السريع", "kind": "خارجية",
         "shift": "صباحية", "officer_ids": ["OFF-001"], "personnel_ids": []},
        {"id": "AS-PM", "name": "التدخل السريع", "kind": "خارجية",
         "shift": "ليلية", "officer_ids": ["OFF-002"], "personnel_ids": []},
    ]}
    payload = roster.build(data, DAY)
    assert payload["counts"]["intervention"] == 2
    assert payload["counts"]["work"] == 2
    assert payload["counts"]["total"] == payload["total"]


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


def test_target_notes_reuse_officers_daily_text_for_single_and_supervisor(data_file):
    data = _roster_data(data_file)
    set_target_officers(data, DAY, "مصر للبترول", ["OFF-001"])
    set_target_officers(data, DAY, "مشرف الأهداف", ["OFF-002"])
    set_officer_state(data, DAY, "OFF-002", extra="متابعة إضافية")

    payload = roster.build(data, DAY)
    daily_rows = {row["id"]: row for row in duty.summarise(data, DAY)["rows"]}
    targets = {item["id"]: item for item in payload["target_items"]}

    assert targets["OFF-001"]["status"] == "عمل بهدف مصر للبترول"
    # الإضافة اليدوية بعد تشغيل الهدف لا تظهر في كشف التعيينات
    assert daily_rows["OFF-002"]["text"].endswith("متابعة إضافية")
    assert targets["OFF-002"]["status"] == "متابعة اعمال الاهداف"
    assert targets["OFF-001"]["status"] == daily_rows["OFF-001"]["text"]
    assert next(item for item in payload["rows"] if item["id"] == "OFF-003")["status"] == "عمل"

    raw_docx = build_docx(payload).getvalue()
    document = Document(BytesIO(raw_docx))
    cells = [" ".join(cell.text.split())
             for row in document.tables[0].rows for cell in row.cells]
    assert "عمل بهدف مصر للبترول" in cells
    assert "متابعة اعمال الاهداف" in cells
    assert not any("متابعة إضافية" in cell for cell in cells)


def test_target_notes_reuse_time_and_text_split_labels(data_file):
    data = _roster_data(data_file)
    set_target_officers(
        data, DAY, "سوميد", ["OFF-001", "OFF-002"],
        periods=[
            {"officer_id": "OFF-001", "until": "16:00"},
            {"officer_id": "OFF-002", "from": "16:00"},
        ],
    )
    set_target_officers(
        data, DAY, "كهرباء السخنة", ["OFF-003"],
        periods=[],
    )
    # Replace the one-person assignment with the supported text-split pair.
    set_target_officers(
        data, DAY, "كهرباء السخنة", ["OFF-003", "OFF-004"],
        periods=[
            {"officer_id": "OFF-003", "label": "لحين انتهاء المباراة"},
            {"officer_id": "OFF-004", "label": "عقب الانتهاء من المباراة"},
        ],
    )

    payload = roster.build(data, DAY)
    daily_rows = {row["id"]: row for row in duty.summarise(data, DAY)["rows"]}
    targets = {item["id"]: item for item in payload["target_items"]}

    assert targets["OFF-001"]["status"] == "عمل بهدف سوميد حتى 4م"
    assert targets["OFF-003"]["status"] == "عمل بهدف كهرباء السخنة لحين انتهاء المباراة"
    assert targets["OFF-004"]["status"] == "عمل بهدف كهرباء السخنة عقب الانتهاء من المباراة"
    for officer_id in ("OFF-001", "OFF-002", "OFF-003", "OFF-004"):
        assert targets[officer_id]["status"] == daily_rows[officer_id]["text"]


def test_target_note_worst_case_catalog_name_and_80_char_split_label_fits(data_file):
    target_names = target_row_names(store.load_data(), DAY)
    longest_target = max(target_names, key=len)
    split_label = ("لحين انتهاء المباراة واستمرار المهمة " * 3).strip()[:80]
    assert len(split_label) == 80
    note = f"عمل بهدف {longest_target} {split_label}"
    payload = {
        "title": "كشف بأسماء السادة الضباط عن يوم السبت الموافق 21/11/2026م",
        "right": [],
        "left": [],
        "target_items": [{"number": 24, "role": "رائد", "name": "أحمد علي", "status": note}],
        "doctors": [], "footer_categories": [], "total": 1,
        "ops_signer": {}, "chief": {},
    }
    raw_docx = build_docx(payload).getvalue()
    document = Document(BytesIO(raw_docx))
    table = document.tables[0]
    note_cell = next(cell for row in table.rows for cell in row.cells
                     if longest_target in cell.text)
    lines = note_cell.text.splitlines()
    assert " ".join(note_cell.text.split()) == note
    assert len(lines) >= 1                       # الخط ثابت: النص بيلف على أسطر والصف يطول

    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    root = etree.fromstring(ZipFile(BytesIO(raw_docx)).read("word/document.xml"))
    widths = [int(value) for value in root.xpath(
        ".//w:tbl/w:tblGrid/w:gridCol/@w:w", namespaces=ns)]
    template_root = etree.fromstring(ZipFile(TEMPLATE).read("word/document.xml"))
    template_widths = [int(value) for value in template_root.xpath(
        ".//w:tbl/w:tblGrid/w:gridCol/@w:w", namespaces=ns)]
    assert sum(widths) == sum(template_widths)
    assert widths[5] + widths[6] + widths[7] == sum(template_widths[5:8])
    assert widths[7] > template_widths[7]
    assert widths[0:5] == template_widths[0:5]

    meter = TextMeter()
    size_values = [int(value) / 2 for value in etree.fromstring(
        note_cell._tc.xml.encode("utf-8")).xpath(".//w:rPr/w:sz/@w:val", namespaces=ns)]
    assert size_values and set(size_values) == {12.0}   # الخط ما بيصغرش أبدًا
    size = 12.0
    row = next(row for row in table.rows if longest_target in row.cells[3].text or longest_target in row.cells[7].text)
    row_root = etree.fromstring(row._tr.xml.encode("utf-8"))
    height = int(row_root.xpath("./w:trPr/w:trHeight/@w:val", namespaces=ns)[0]) / 20
    assert len(lines) * size * 1.25 <= height            # الصف طال ليكفي كل الأسطر
    assert all(len(cell.text) < 1000 for row in table.rows for cell in row.cells)


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


def test_signature_boxes_use_two_word_names_while_operations_data_keeps_full_name(data_file):
    data = _roster_data(data_file)
    data["personnel"][0]["name"] = "أحمد عمليات حسن عبد الله"
    payload = roster.build(data, DAY)
    assert payload["operations_members"][0]["name"] == "أحمد عمليات حسن عبد الله"
    raw_docx = build_docx({
        "title": "كشف بأسماء السادة الضباط عن يوم السبت الموافق 21/11/2026م",
        "right": [], "left": [], "target_items": [], "doctors": [],
        "footer_categories": [], "total": 0,
        "ops_signer": {"rank": "معاون ثالث", "name": "أحمد عمليات حسن عبد الله"},
        "chief": {"rank": "رائد", "name": "محمد بحر شحاتة عبد الله", "short_name": "محمد بحر"},
    }).getvalue()
    text = ZipFile(BytesIO(raw_docx)).read("word/document.xml").decode("utf-8")
    assert "(أحمد عمليات)" in text and "(محمد بحر)" in text
    assert "أحمد عمليات حسن عبد الله" not in text
    assert "محمد بحر شحاتة عبد الله" not in text


def test_roster_page_has_responsive_and_recovery_hooks():
    root = Path(__file__).resolve().parent.parent
    html = (root / "templates/pages/assignments_roster.html").read_text(encoding="utf-8")
    js = (root / "static/js/assignments-roster.js").read_text(encoding="utf-8")
    css = (root / "static/css/pages.css").read_text(encoding="utf-8")
    assert 'class="table-scroll is-wide roster-preview-scroll"' in html
    assert 'id="rosterSelectionSearch"' in html
    assert 'id="rosterPrev"' in html and 'id="rosterNext"' in html
    assert '{% block export %}' not in html
    assert html.count('id="rosterDownload"') == 1
    assert '<details id="rosterSettings"' in html
    assert 'id="rosterSave"' in html and 'id="rosterDirty"' in html
    assert 'aria-label="اليوم السابق"' in html and 'aria-label="اليوم التالي"' in html
    assert 'data-roster-footer-error' in js
    assert 'data-roster-footer-remove aria-label="حذف التصنيف' in js
    assert 'rosterSettingsNeedOpen' in js and 'panel.open = rosterSettingsNeedOpen(data)' in js
    assert 'window.dailyFileDay = () => ROSTER_DAY' in js
    assert 'if (!value) return "";' in js
    assert "confirmDialog" in js and "stale_revision" in js
    assert "rosterIsIntervention" in js and "roster-status-chip" in js
    assert "roster-stat-chip" in js and "roster-page-stats" in js
    assert "shiftRoster(-1)" in js and "shiftRoster(1)" in js
    assert "setRosterDirty(true)" in js
    assert "person.name || person.full_name" in js
    assert ".roster-preview-scroll" in css and ".roster-selection-list" in css
    assert "position:sticky" in css and ".roster-footer-remove" in css
    assert "minmax(0,28rem)" in css and ".roster-nav-text" in css
    assert "rosterOpsSigner" in css and "background-image:var(--caret)" in css
    assert "٠" not in html + js
    assert "@media(prefers-reduced-motion:reduce)" in (root / "static/css/base.css").read_text(encoding="utf-8")

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
    assert offsets["Text Box 5"] == 0                       # رئيس قسم العمليات (الضابط): أقصى الشمال
    assert offsets["Text Box 4"] == (10064 - 4000) * 635    # بلوكامين قسم العمليات (الفرد): أقصى اليمين (عرض العمود 10064)
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
    assert body["weekday"] == "السبت"
    assert set(body["counts"]) == {"total", "work", "intervention"}
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
    assert row["status"] == "تدخل صبح"


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
    daily = next(row for row in duty.summarise(data, DAY)["rows"] if row["id"] == "OFF-001")
    assert target["status"] == daily["text"]
    raw_docx = build_docx(payload).getvalue()
    document = Document(BytesIO(raw_docx))
    expected = " ".join(daily["text"].split())
    assert any(expected in " ".join(cell.text.split())
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
                     if " ".join(cell.text.split()) == note)
    lines = note_cell.text.splitlines()
    note_root = etree.fromstring(note_cell._tc.xml.encode("utf-8"))
    sizes = [int(value) / 2 for value in note_root.xpath(
        ".//w:rPr/w:sz/@w:val", namespaces=ns)]
    assert sizes and set(sizes) == {12.0}            # الخط ثابت
    size = 12.0
    row = next(row for row in table.rows if " ".join(row.cells[3].text.split()) == note)
    row_root = etree.fromstring(row._tr.xml.encode("utf-8"))
    height = int(row_root.xpath("./w:trPr/w:trHeight/@w:val", namespaces=ns)[0]) / 20
    assert len(lines) * size * 1.25 <= height


def test_day_navigation_has_today_next_to_tomorrow():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    template = (root / "templates/pages/assignments_roster.html").read_text(encoding="utf-8")
    script = (root / "static/js/assignments-roster.js").read_text(encoding="utf-8")
    assert template.index('id="rosterToday"') < template.index('id="rosterTomorrow"')
    assert '>اليوم</button>' in template
    assert '$("#rosterToday").onclick' in script and "_localToday()" in script
    assert '"#rosterToday"' in script          # بيتعطّل وقت الحفظ زي باقي أزرار التنقل


def test_roster_follows_the_shared_work_day_and_does_not_overwrite_it_on_automatic_open():
    from pathlib import Path
    script = (Path(__file__).resolve().parent.parent / "static/js/assignments-roster.js").read_text(encoding="utf-8")
    init = script[script.index("(async function initRoster()"):]
    assert "workDay()" in init                         # بيتبع يوم العمل المشترك بين اليوميات
    assert "addDays(today, 1)" in init                 # من غير اختيار صريح: بكرة
    assert "loadRoster(day, shared !== today)" in init  # الفتح التلقائي مايحفظش بكرة كيوم عمل
    assert "async function loadRoster(day, remember = true)" in script
    assert "setPageDay(day, remember)" in script


def test_export_never_fails_on_a_long_note_the_row_grows_and_the_font_stays():
    """«ملاحظة يومية التعيينات لا تتسع» كانت بتمنع التحميل؛ والتصغير مرفوض: الصف هو اللي يطول."""
    long_note = "عمل (ارتكاز الحي الحكومي) + نقطة تفتيش كمين 109 اسفل + مأمورية نيابة عسكرية بالقاهرة"
    base = {
        "title": "كشف بأسماء السادة الضباط عن يوم الأحد الموافق 22/11/2026م",
        "left": [], "target_items": [], "doctors": [], "footer_categories": [], "total": 3,
        "ops_signer": {"rank": "م.ش", "name": "أحمد علي"},
        "chief": {"rank": "رائد", "name": "محمد بحر"},
        "right": [
            {"number": 1, "role": "عقيد", "name": "أحمد سمير محمد حمدي", "status": "عمل (ارتكاز الحي الحكومي)"},
            {"number": 2, "role": "مقدم", "name": "محمد", "status": long_note},
            {"number": 3, "role": "رائد", "name": "علي", "status": "عمل بهدف " + "كلمة_واحدة_طويلة_جدا" * 6},
        ],
    }
    raw = build_docx(base).getvalue()
    root = etree.fromstring(ZipFile(BytesIO(raw)).read("word/document.xml"))
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    document = Document(BytesIO(raw))
    texts = [" ".join(cell.text.split()) for row in document.tables[0].rows for cell in row.cells]
    assert long_note in texts
    sizes = {int(v) for v in root.xpath(".//w:tbl//w:tc[.//w:t[contains(., 'مأمورية')]]//w:sz/@w:val", namespaces=ns)}
    assert sizes == {24}                                   # 12pt لا يصغر
    heights = sorted({int(v) for v in root.xpath(".//w:tbl/w:tr/w:trPr/w:trHeight/@w:val", namespaces=ns)})
    assert len(heights) >= 2 and heights[-1] > 440         # صف طال


def test_target_block_numbering_continues_from_the_real_right_half_count():
    """الترقيم كان بيقفز لـ24 حتى لو النصف الأيمن 16 ضابط بس."""
    right = [{"number": i, "role": "رائد", "name": f"ضابط {i}", "status": "عمل"} for i in range(1, 4)]
    targets = [{"role": "مقدم", "name": "هدف أول", "status": "عمل بهدف مصر للبترول"},
               {"role": "رائد", "name": "هدف ثان", "status": "عمل بهدف سوميد"}]
    raw = build_docx({
        "title": "كشف بأسماء السادة الضباط عن يوم الأحد الموافق 22/11/2026م",
        "right": right, "left": [], "target_items": targets, "doctors": [],
        "footer_categories": [], "total": 5, "ops_signer": {}, "chief": {},
    }).getvalue()
    table = Document(BytesIO(raw)).tables[0]
    numbered = {}
    for row in table.rows:
        cells = [" ".join(cell.text.split()) for cell in row.cells]
        for index, text in enumerate(cells):
            if text in {"هدف أول", "هدف ثان"}:
                numbered[text] = cells[index - 2]
    assert numbered == {"هدف أول": "4", "هدف ثان": "5"}


def test_roster_numbers_the_overflow_half_after_the_actual_right_half(data_file):
    data = _roster_data(data_file)
    payload = roster.build(data, DAY)
    right, left = payload["right"], payload["left"]
    assert [row["number"] for row in right] == list(range(1, len(right) + 1))
    assert [row["number"] for row in left] == list(range(len(right) + 1, len(right) + len(left) + 1))


def test_note_column_widens_with_content_by_taking_width_from_the_name_column_only():
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

    def grid(status):
        raw = build_docx({
            "title": "x", "left": [], "target_items": [], "doctors": [], "footer_categories": [],
            "total": 1, "ops_signer": {}, "chief": {},
            "right": [{"number": 1, "role": "رائد", "name": "أحمد", "status": status}],
        }).getvalue()
        root = etree.fromstring(ZipFile(BytesIO(raw)).read("word/document.xml"))
        return [int(v) for v in root.xpath(".//w:tbl/w:tblGrid/w:gridCol/@w:w", namespaces=ns)]

    short, long = grid("عمل"), grid("عمل (ارتكاز الحي الحكومي) + نقطة تفتيش")
    assert long[3] > short[3]                      # الملاحظات اتوسّعت
    assert long[2] < short[2]                      # من عمود الاسم
    assert long[1] == short[1] and long[0] == short[0]   # الرتبة والرقم ثابتين
    assert sum(long) == sum(short)                 # إجمالي الشبكة ثابت

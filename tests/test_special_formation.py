import json
from io import BytesIO
from urllib.parse import quote, unquote

from docx import Document

from backend import special_formation
from backend.special_formation_export import build_docx

DAY = "2026-10-20"
MATCH = "مباراة المصري * البنك الاهلي"


def _data():
    return {
        "officers": [{"id": "OFF-001", "name": "أحمد محمد علي", "role": "مقدم", "status": "active"}],
        "personnel": [{"id": "IND-001", "name": "هاني محمد ابراهيم سالم", "role": "امين شرطة", "status": "active"}],
        "day_assignments": {DAY: [
            {"id": "A1", "name": "مدرجات الدرجة الاولي", "section": MATCH, "officer_ids": ["OFF-001"],
             "conscript_count": 3, "weapon": "رياضي", "time": "2م", "party": "استاد السويس"},
            {"id": "A2", "name": "ملاحظة الحالة", "section": MATCH, "personnel_ids": ["IND-001"],
             "conscript_count": 2, "weapon": "الي + خرطوش"},
            {"id": "A3", "name": "مرافقة الجماهير", "section": MATCH, "conscript_count": 0},
            {"id": "A4", "name": "طارئة", "section": "الخدمات الطارئة", "conscript_count": 4},
            {"id": "A5", "name": "تفتيش", "section": "تفتيشات", "conscript_count": 1},
            {"id": "A6", "name": "قديم", "section": "فرد + مج (خارجي)", "conscript_count": 1},
            {"id": "A7", "name": "قول", "section": "خطة الانتشار", "conscript_count": 5, "weapon": "فض"},
        ]},
    }


def test_sections_are_only_the_custom_events_of_the_day():
    found = special_formation.sections(_data(), DAY)
    assert [item["name"] for item in found] == [MATCH, "خطة الانتشار"]
    assert found[0] == {"name": MATCH, "posts": 3, "conscripts": 6}


def test_build_gives_head_labels_slot_weapons_and_warnings():
    payload = special_formation.build(_data(), DAY, MATCH)
    first, second, third = payload["posts"]
    assert first["head"] == "مقدم/ أحمد محمد" and first["weapons"] == ["رياضي"] * 3
    assert second["head"].endswith("هاني محمد ابراهيم") and second["weapons"] == ["آلي", "خرطوش"]
    assert third["count"] == 1   # مفيش عدد ولا قوام: خانة مجند فاضية
    assert any("مرافقة الجماهير" in warning for warning in payload["warnings"])
    assert payload["totals"] == {"posts": 3, "conscripts": 6}


def test_unknown_or_excluded_section_raises():
    for section in ("مش موجودة", "تفتيشات", "الخدمات الطارئة"):
        try:
            special_formation.build(_data(), DAY, section)
        except LookupError:
            continue
        raise AssertionError(section)


def test_slots_come_only_from_the_count_field():
    data = _data()
    # القوام مش بيتحسب: العدد من خانة «عدد المجندين» بس، وخانة فاضية لو مش مكتوب.
    data["day_assignments"][DAY][2]["conscripts"] = [{"class": "مج", "count": 2}]
    assert special_formation.build(data, DAY, MATCH)["posts"][2]["count"] == 1
    data["day_assignments"][DAY][2]["conscript_count"] = 4
    assert special_formation.build(data, DAY, MATCH)["posts"][2]["count"] == 4


def test_docx_is_a4_portrait_rtl_tables_with_numbered_slots():
    document = Document(build_docx(special_formation.build(_data(), DAY, MATCH)))
    section = document.sections[0]
    assert section.page_width < section.page_height
    tables = document.tables
    # كل خدمة في جدول لوحدها: م | الخدمة | التسليح، وخانة لكل مجند.
    assert [len(table.columns) for table in tables] == [3, 3, 3]
    assert [len(table.rows) for table in tables] == [4, 3, 2]
    header = [cell.text for cell in tables[0].rows[0].cells]
    assert header[0] == "م" and header[2] == "التسليح"
    assert "مدرجات الدرجة الاولي" in header[1] and "مقدم/ أحمد محمد" in header[1]
    assert [tables[0].rows[i].cells[0].text for i in (1, 2, 3)] == ["1.", "2.", "3."]
    assert tables[0].rows[1].cells[2].text == "رياضي"
    assert tables[0]._tbl.tblPr.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}bidiVisual") is not None


def test_route_downloads_one_file_per_event_and_ops_lists_events(client, data_file):
    stored = json.loads(data_file.read_text())
    stored.setdefault("day_assignments", {})[DAY] = _data()["day_assignments"][DAY]
    data_file.write_text(json.dumps(stored, ensure_ascii=False))
    listed = client.get(f"/api/ops/{DAY}").get_json()["special_formations"]
    assert [item["name"] for item in listed] == [MATCH, "خطة الانتشار"]
    response = client.get(f"/api/ops/{DAY}/special-formation.docx?section={quote(MATCH)}")
    assert response.status_code == 200
    name = unquote(response.headers["Content-Disposition"].split("filename*=")[-1].removeprefix("UTF-8''"))
    assert name == "خط تشكيل مباراة المصري   البنك الاهلي.docx".replace("   ", " ")
    assert Document(BytesIO(response.data)).tables
    assert client.get(f"/api/ops/{DAY}/special-formation.docx?section=x").status_code == 404


def test_special_regularity_is_landscape_and_filtered_to_one_group(client, data_file):
    stored = json.loads(data_file.read_text())
    stored.setdefault("day_assignments", {})[DAY] = _data()["day_assignments"][DAY]
    data_file.write_text(json.dumps(stored, ensure_ascii=False))
    response = client.get(f"/api/ops/{DAY}/special-regularity.docx?section={quote(MATCH)}")
    assert response.status_code == 200
    name = unquote(response.headers["Content-Disposition"].split("filename*=")[-1].removeprefix("UTF-8''"))
    assert name == "يومية انتظام مباراة المصري البنك الاهلي.docx"
    document = Document(BytesIO(response.data))
    section = document.sections[0]
    assert section.page_width > section.page_height
    assert len(document.tables) == 1          # جدول الخدمات بس، من غير جدول الضباط
    services = [row.cells[1].text for row in document.tables[0].rows[1:]]
    assert sorted(services) == sorted(["مدرجات الدرجة الاولي", "ملاحظة الحالة", "مرافقة الجماهير"])
    header = " ".join(p.text for p in section.header.paragraphs)
    assert "يومية انتظام خدمات " + MATCH in header
    other = client.get(f"/api/ops/{DAY}/special-regularity.docx?section={quote('خطة الانتشار')}")
    assert [row.cells[1].text for row in Document(BytesIO(other.data)).tables[0].rows[1:]] == ["قول"]
    for bad in ("x", "الخدمات الطارئة", "تفتيشات"):
        assert client.get(f"/api/ops/{DAY}/special-regularity.docx?section={quote(bad)}").status_code == 404


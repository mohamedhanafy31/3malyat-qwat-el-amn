"""اختبارات أمر صرف الوجبات الجافة: API، العرض، التخزين، وWord."""
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from lxml import etree

from backend import dry_meals, store
from backend import dry_meals_export
from backend.dry_meals_export import build_docx
from backend.assignments_roster_export import _OOXML_ORDER


DAY = "2026-11-21"
EARLIER = "2026-11-20"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _revision(client, day=DAY):
    response = client.get(f"/api/dry-meals/{day}")
    assert response.status_code == 200
    return response.get_json()


def _fixed(name="بوابة السويس", officers=1, personnel=2, conscripts=3, notes=""):
    return {"name": name, "officers": officers, "personnel": personnel,
            "conscripts": conscripts, "notes": notes}


def _body(payload, **overrides):
    body = {"fixed_rows": [_fixed()], "emergency_enabled": False,
            "emergency_rows": [], "ops_signer_id": "",
            "revision": payload["revision"]}
    body.update(overrides)
    return body


def test_get_payload_shape_totals_and_page(client):
    response = client.get(f"/api/dry-meals/{DAY}")
    assert response.status_code == 200
    payload = response.get_json()
    assert {"fixed_rows", "emergency_rows", "config", "pickable_services",
            "revision", "day_status", "weekday"} <= set(payload)
    # بدون يوم سابق محفوظ: الخدمات الثابتة الافتراضية من الأمر الورقي (11 وجبة)
    assert [row["name"] for row in payload["config"]["fixed_rows"]] == [
        "تمشيط حنيفة", "تمشيط أم القمر", "محور 30 يوليو",
        "قول 36 لاسلكي", "مكتب امن وطن بالسخنة"]
    assert payload["fixed_total"] == 11
    assert payload["total"] == 11
    assert client.get("/dry-meals").status_code == 200
    assert "أمر صرف وجبات جافة" in client.get("/dry-meals").get_data(as_text=True)


def test_put_validation_errors(client):
    payload = _revision(client)
    assert client.put(f"/api/dry-meals/{DAY}", json=_body(payload, fixed_rows=[_fixed(officers=1000)])).status_code == 400
    assert client.put(f"/api/dry-meals/{DAY}", json=_body(payload, fixed_rows=[_fixed("x" * 81)])).status_code == 400
    assert client.put(f"/api/dry-meals/{DAY}", json=_body(payload, fixed_rows=[_fixed()] * 13)).status_code == 400
    duplicate = [_fixed("خدمة طوارئ"), {**_fixed("خدمة طوارئ"), "officers": 2}]
    assert client.put(f"/api/dry-meals/{DAY}", json=_body(
        payload, emergency_enabled=True,
        emergency_rows=[{**row, "source": "طوارئ"} for row in duplicate],
    )).status_code == 400


def test_stale_revision_and_closed_day(client):
    payload = _revision(client)
    saved = client.put(f"/api/dry-meals/{DAY}", json=_body(payload))
    assert saved.status_code == 200
    stale = client.put(f"/api/dry-meals/{DAY}", json=_body(payload, fixed_rows=[_fixed(officers=4)]))
    assert stale.status_code == 409 and stale.get_json()["code"] == "stale_revision"
    assert client.post(f"/api/day-status/{DAY}/close", json={}).status_code == 201
    locked_payload = _revision(client)
    locked = client.put(f"/api/dry-meals/{DAY}", json=_body(locked_payload, fixed_rows=[_fixed(officers=9)]))
    assert locked.status_code == 409 and "مغلق" in locked.get_json()["error"]


def test_carry_forward_prefill_from_earlier_day(data_file, client):
    def mutate(data):
        dry_meals.store_config(data, EARLIER, {
            "fixed_rows": [_fixed("خدمة مستمرة", officers=2)],
            "emergency_enabled": False, "emergency_rows": [], "ops_signer_id": "",
        })

    store.with_data(mutate, [EARLIER])
    payload = client.get(f"/api/dry-meals/{DAY}").get_json()
    assert payload["config"]["fixed_rows"][0]["name"] == "خدمة مستمرة"
    assert payload["saved"] is False


def test_emergency_off_export_has_no_second_half_and_is_one_page(client, tmp_path):
    payload = _revision(client)
    saved = client.put(f"/api/dry-meals/{DAY}", json=_body(
        payload, fixed_rows=[_fixed("ثابت", 1, 2, 3)]))
    assert saved.status_code == 200
    response = client.get(f"/api/dry-meals/{DAY}/export.docx")
    assert response.status_code == 200
    document = Document(BytesIO(response.data))
    text = "\n".join(p.text for p in document.paragraphs)
    assert "أمر عمليات طارئ" not in text
    assert "أمر عمليات ثابت" in text
    assert "٢١/١١/٢٠٢٦" in text
    assert "ـــولتعذر" in text
    assert len(document.tables) == 2  # letterhead, fixed table; signatures are pinned in footer
    assert len(document.sections[0].footer.tables) == 1
    out = tmp_path / "dry.docx"
    out.write_bytes(response.data)
    assert out.stat().st_size > 1000


def test_emergency_on_rows_are_padded_and_totals_math(client):
    payload = _revision(client)
    emergency = [{"name": "خدمة طوارئ", "source": "طوارئ", "officers": 1,
                  "personnel": 2, "conscripts": 3, "notes": ""}]
    saved = client.put(f"/api/dry-meals/{DAY}", json=_body(
        payload, fixed_rows=[_fixed("ثابت", 2, 0, 1)], emergency_enabled=True,
        emergency_rows=emergency))
    assert saved.status_code == 200
    result = saved.get_json()
    assert result["fixed_total"] == 3 and result["emergency_total"] == 6
    assert result["total"] == 9
    document = Document(BytesIO(client.get(f"/api/dry-meals/{DAY}/export.docx").data))
    text = "\n".join(cell.text for table in document.tables for row in table.rows for cell in row.cells)
    assert "أمر عمليات طارئ" in "\n".join(p.text for p in document.paragraphs)
    assert "اجمالي الوجبـــــات الجافـــة المنصرفة" in text
    assert len(document.tables[2].rows) >= 2 + 4 + 1
    assert "٦ وجبه" in text and "٣ وجبة" in text


def test_signatures_text_and_child_order():
    raw = build_docx({
        "date": DAY, "weekday": "السبت", "fixed_rows": [_fixed()],
        "emergency_rows": [], "emergency_enabled": False,
        "ops_signer": {"rank": "معاون ثالث", "name": "أحمد عمليات"},
        "chief": {"rank": "رائد", "name": "محمد بحر"},
    }).getvalue()
    doc = Document(BytesIO(raw))
    signature_text = "\n".join(
        cell.text
        for table in [*doc.tables, *doc.sections[0].footer.tables]
        for row in table.rows for cell in row.cells
    )
    assert "بلوكامين قسم العمليات" in signature_text
    assert "رئيس قسم العمليات" in signature_text
    root = etree.fromstring(ZipFile(BytesIO(raw)).read("word/document.xml"))
    violations = []
    for name, sequence in _OOXML_ORDER.items():
        for element in root.iter(qn := f"{{{W}}}{name}"):
            tags = [etree.QName(child).localname for child in element if etree.QName(child).namespace == W]
            indexes = [sequence.index(tag) for tag in tags if tag in sequence]
            if indexes != sorted(indexes) or len(set(tags)) != len(tags):
                violations.append((name, tags))
    assert not violations


def test_export_paper_frame_font_columns_merges_and_display_digits():
    raw = build_docx({
        "date": DAY, "weekday": "الاثنين",
        "fixed_rows": [_fixed("خدمة رقم 1 للتجربة", officers=1, personnel=2, conscripts=3)],
        "emergency_enabled": True,
        "emergency_rows": [{"name": "خدمة طوارئ", "officers": 1,
                            "personnel": 0, "conscripts": 2, "notes": ""}],
        "ops_signer": {"rank": "رائد", "name": "أحمد"},
        "chief": {"rank": "رائد", "name": "محمد"},
    }).getvalue()
    doc = Document(BytesIO(raw))
    visible = "\n".join(
        [p.text for p in doc.paragraphs]
        + [cell.text for table in doc.tables for row in table.rows for cell in row.cells]
        + [cell.text for table in doc.sections[0].footer.tables for row in table.rows for cell in row.cells]
    )
    assert "٢١/١١/٢٠٢٦" in visible and "2026" not in visible
    assert "الأعـــــداد" in visible
    assert "ـــــ" in visible
    xml = ZipFile(BytesIO(raw)).read("word/document.xml")
    assert b'val="thickThinSmallGap"' in xml
    assert b'offsetFrom="page"' in xml
    assert b'ascii="Simplified Arabic"' in xml and b'eastAsia="Simplified Arabic"' in xml
    assert b"w:szCs" in xml and b"w:bCs" in xml
    assert b'color="7F7F7F"' in xml
    table = doc.tables[1]
    grid = [int(col.get(f"{{{W}}}w")) for col in table._tbl.tblGrid.findall(f"{{{W}}}gridCol")]
    expected_grid = [round(width * 56.6929) for width in dry_meals_export._table_widths()]
    expected_grid[-1] += round(dry_meals_export.CONTENT_WIDTH_MM * 56.6929) - sum(expected_grid)
    assert grid == expected_grid
    assert sum(grid) == round(dry_meals_export.CONTENT_WIDTH_MM * 56.6929)
    assert table._tbl.tblPr.tblLayout.type == "fixed"
    tbl_width = table._tbl.tblPr.find(f"{{{W}}}tblW")
    assert tbl_width.get(f"{{{W}}}type") == "dxa"
    widths = [int(cell._tc.tcPr.tcW.w) for cell in table.rows[0].cells]
    assert widths[1] > widths[6] > widths[0]
    assert b'gridSpan w:val="3"' in xml and b'gridSpan w:val="2"' in xml
    body_spacing = etree.fromstring(xml).xpath(
        './/w:p[w:r/w:t[contains(., "أمر صرف وجبات")]]/w:pPr/w:spacing',
        namespaces={"w": W},
    )
    expected_line = str(round(dry_meals_export.BODY_FONT_PT * 20 * 1.35))
    assert body_spacing and all(
        node.get(f"{{{W}}}line") == expected_line
        and node.get(f"{{{W}}}lineRule") == "exact"
        for node in body_spacing
    )
    total_row = table.rows[-1]._tr
    total_height = total_row.find(f"{{{W}}}trPr/{{{W}}}trHeight")
    assert total_height.get(f"{{{W}}}hRule") == "atLeast"
    m_margin = table.rows[2].cells[0]._tc.tcPr.find(f"{{{W}}}tcMar")
    assert m_margin.find(f"{{{W}}}start").get(f"{{{W}}}w") == "80"
    assert m_margin.find(f"{{{W}}}end").get(f"{{{W}}}w") == "80"


def test_large_layout_compresses_only_after_common_case_budget():
    common_off = {
        "fixed_rows": [_fixed(str(i)) for i in range(6)],
        "emergency_enabled": False,
        "emergency_rows": [],
    }
    common_layout = dry_meals_export._table_layout(common_off)
    assert common_layout["data_row"] == dry_meals_export.DATA_ROW_PT
    assert common_layout["data_font"] == 16
    assert common_layout["header_font"] == 15
    assert common_layout["paragraph_font"] == 17
    assert common_layout["signature_font"] == dry_meals_export.SIGNATURE_FONT_PT

    two_emergency = {
        "fixed_rows": [_fixed(str(i)) for i in range(5)],
        "emergency_enabled": True,
        "emergency_rows": [{**_fixed(str(i)), "source": "طوارئ"} for i in range(2)],
    }
    two_emergency_layout = dry_meals_export._table_layout(two_emergency)
    assert two_emergency_layout["data_row"] == 21.3
    assert two_emergency_layout["data_font"] == 16
    assert two_emergency_layout["header_gap"] == 26

    large = {
        "date": DAY, "weekday": "الاثنين",
        "fixed_rows": [_fixed(f"ثابت {i}") for i in range(12)],
        "emergency_enabled": True,
        "emergency_rows": [{**_fixed(f"طارئ {i}"), "source": "طوارئ"} for i in range(8)],
        "ops_signer": {"rank": "رائد", "name": "أحمد"},
        "chief": {"rank": "رائد", "name": "محمد"},
    }
    large_layout = dry_meals_export._table_layout(large)
    assert large_layout["data_row"] == 17.6
    assert large_layout["data_font"] == 13
    assert large_layout["header_font"] == 14
    assert large_layout["paragraph_font"] == 14
    assert large_layout["signature_font"] == dry_meals_export.SIGNATURE_FONT_PT
    assert large_layout["header_gap"] == 17
    assert large_layout["separator_space"] == 3
    assert build_docx(large).getvalue()


def test_page_js_uses_shared_work_day_and_escapes_dynamic_html():
    root = Path(__file__).resolve().parent.parent
    js = (root / "static/js/dry-meals.js").read_text(encoding="utf-8")
    assert "workDay()" in js and "setPageDay(day, remember)" in js
    assert "rememberWorkDay" not in js or "setPageDay" in js
    assert "esc(row.name" in js and "esc(item.name)" in js
    assert "innerHTML" in js and "dataAttr(item)" in js


def test_dry_meals_round_trips_in_extras_bundle(data_file):
    store.with_data(lambda data: dry_meals.store_config(data, DAY, {
        "fixed_rows": [_fixed("خدمة")], "emergency_enabled": False,
        "emergency_rows": [], "ops_signer_id": "",
    }), [DAY])
    assert store.load_data([DAY])["day_dry_meals"][DAY]["fixed_rows"][0]["name"] == "خدمة"
    assert (store.day_folder(DAY) / "extras.json").exists()


def test_signer_rank_is_abbreviated_for_individuals():
    from backend.labels import personnel_rank_abbr
    assert personnel_rank_abbr("معاون ثالث") == "م.ش"
    assert personnel_rank_abbr("أمين شرطة ثان") == "ا.ش"

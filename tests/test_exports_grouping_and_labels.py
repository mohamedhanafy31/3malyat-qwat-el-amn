"""ترتيب/فواصل اللواري في خط التشكيل ويومية الحملة، وتسمية مركبة الانتظامات،
وعمود الحالة الخاصة في إجمالي يومية الضباط."""
from io import BytesIO

import pytest
from docx import Document
from docx.oxml.ns import qn

from backend.fleet import order_by_category, vehicle_category
from backend.formation import build as build_formation
from backend.formation_export import build_docx as formation_docx
from backend.campaign_export import build_docx as campaign_docx
from backend.duty_export import _summary_layout, _summary_values, build_docx as duty_docx

DAY = "2026-10-20"


def _borders(tc):
    node = tc.find(qn("w:tcPr") + "/" + qn("w:tcBorders"))
    return {child.tag.split("}")[1]: int(child.get(qn("w:sz")) or 0)
            for child in (node if node is not None else [])
            if child.get(qn("w:val")) == "single"}


def _row_cells(row):
    return row._tr.tc_lst


def _row_text(row):
    seen, out = set(), []
    for tc in row._tr.tc_lst:
        out.append("".join(t.text or "" for t in tc.iter(qn("w:t"))))
    return out


# ---------- 1. خط التشكيل ----------

def _formation_data():
    names = ["أ", "ب", "ج", "د", "هـ"]
    catalog = [{"id": f"SVC-{i}", "name": name, "tags": [tag]}
               for i, (name, tag) in enumerate(zip(names, ["t1", "t2", "t1", "", "t2"]), 1)]
    return {
        "service_catalog": catalog,
        "service_tags": ["t1", "t2"],
        "service_lines": [
            {"id": "LN-1", "name": "خط 1", "tag": "t1", "lorry_id": "LOR-1", "order": []},
            {"id": "LN-2", "name": "خط 2", "tag": "t2", "lorry_id": "LOR-3", "order": []}],
        "counts_template": {"entries": [
            {"id": f"CNT-{i}", "name": name, "block": "صباحية", "count": 2, "weapon": "آلي"}
            for i, name in enumerate(names, 1)]},
        "day_assignments": {DAY: []}, "day_afraad": {}, "service_counts": {},
    }


def test_formation_groups_services_by_lorry_with_group_end_flags():
    result = build_formation(_formation_data(), DAY, "morning")
    # أ و ج على اللوري 1 (أول ظهور)، ب و هـ على اللوري 3، د من غير لوري.
    assert [b["name"] for b in result["blocks"]] == ["أ", "ج", "ب", "هـ", "د"]
    assert [bool(b["group_end"]) for b in result["blocks"]] == [False, True, False, True, False]


def _slot_rows(table):
    return [(i, _row_text(row)) for i, row in enumerate(table.rows)]


def test_formation_morning_docx_has_thick_border_after_lorry_group():
    document = Document(BytesIO(formation_docx(build_formation(_formation_data(), DAY, "morning")).getvalue()))
    table = document.tables[0]
    thick = []
    for row in table.rows:
        for tc in row._tr.tc_lst:
            if _borders(tc).get("bottom") == 18:
                thick.append(tc)
    assert thick, "لازم يبقى فيه حد سفلي 2.25pt"
    # صفين فقط (آخر مجموعة اللوري 1 وآخر مجموعة اللوري 3) × 3 أعمدة
    assert len(thick) == 6


def test_formation_night_docx_has_thick_border_after_lorry_group():
    data = _formation_data()
    for entry in data["counts_template"]["entries"]:
        entry["block"] = "ليلية"
    result = build_formation(data, DAY, "night")
    assert [b["name"] for b in result["blocks"]] == ["أ", "ج", "ب", "هـ", "د"]
    document = Document(BytesIO(formation_docx(result).getvalue()))
    table = document.tables[0]
    thick_rows = [i for i, row in enumerate(table.rows)
                  if any(_borders(tc).get("bottom") == 18 for tc in row._tr.tc_lst)]
    assert thick_rows
    # الليل نص يمين بس (كل الخدمات 5×3 صف)؛ مجموعتين لوري → صفين
    assert len(thick_rows) == 2


# ---------- 2. يومية الحملة ----------

@pytest.mark.parametrize("text,expected", [
    ("لوري", "lorry"), ("اوتوبيس", "bus"), ("أتوبيس", "bus"), ("أوتوبيس", "bus"),
    ("ميك", "micro"), ("ميكروباص", "micro"), ("ميكرو", "micro"),
    ("بيك اب", "pickup"), ("بيكب", "pickup"), ("بيك-اب", "pickup"),
    ("بيك اب دوبل كبينة", "pickup"), ("دوبل كابينة", "pickup"), ("دبل كبينة", "pickup"),
    ("مدرعة", "other"), ("اسعاف", "other"), ("", "other"), (None, "other"),
])
def test_vehicle_category_normalises_arabic_spellings(text, expected):
    assert vehicle_category(text) == expected


def test_order_by_category_groups_lorries_and_marks_breaks():
    items = [("p1", "بيك اب", "V1"), ("l1", "لوري", "V2"), ("m", "ميك", "V3"),
             ("l2", "لوري", "V4"), ("l1b", "لوري", "V2"), ("u", "مدرعة", "V5"),
             ("b", "اوتوبيس", "V6"), ("d", "دوبل كبينة", "V7")]
    out = order_by_category(items, lambda i: i[1], lambda i: i[2])
    assert [o[0][0] for o in out] == ["l1", "l1b", "l2", "b", "m", "p1", "d", "u"]
    assert [o[3] for o in out] == [False, True, True, True, True, False, True, False]


def _lorry(name, plate, vtype="لوري", vid=None):
    return {"id": vid or plate, "kind": "lorry", "name": name, "driver": None, "attached": [],
            "vehicle": {"id": vid or plate, "plate": plate, "type": vtype, "origin": "internal"}}


def _service(name, plate, vtype, vid=None):
    vehicle = {"id": vid or plate, "plate": plate, "type": vtype, "origin": "internal"}
    return {"id": f"S-{name}", "kind": "service", "name": name, "time": "", "driver": None,
            "vehicle": vehicle, "service_vehicles": [{"vehicle": vehicle, "driver": None}]}


def test_campaign_export_orders_by_vehicle_category_with_thick_borders():
    payload = {"date": "2026-09-29", "posts": [],
               "lorries": [_lorry("لوري أول", "ب1/1"), _lorry("لوري ثاني", "ب1/2")],
               "services": [_service("خدمة بيك", "ب2/1", "بيك اب"),
                            _service("خدمة ميك", "ب2/2", "ميك"),
                            _service("خدمة دوبل", "ب2/3", "بيك اب دوبل كبينة"),
                            _service("خدمة باص", "ب2/4", "اوتوبيس"),
                            _service("خدمة مدرعة", "ب2/5", "مدرعة"),
                            _service("خدمة على اللوري", "ب1/1", "لوري", vid="ب1/1")],
               "daily": [], "appointments": [], "plates": {"rows": []}}
    document = Document(BytesIO(campaign_docx(payload).getvalue()))
    table = document.tables[0]
    rows = [(i, _row_text(r)) for i, r in enumerate(table.rows)]
    start = next(i for i, texts in rows if texts and texts[0] == "1.")
    delivery = [(i, texts) for i, texts in rows if i >= start and texts[0].endswith(".")]
    names = [texts[1] for _i, texts in delivery]
    assert names == ["لوري أول", "خدمة على اللوري", "لوري ثاني", "خدمة باص", "خدمة ميك",
                     "خدمة بيك", "خدمة دوبل", "خدمة مدرعة"]
    bottoms = [i for i, _ in delivery
               if all(_borders(tc).get("bottom") == 18 for tc in table.rows[i]._tr.tc_lst)]
    # بعد: لوري أول+خدمته، لوري ثاني، الباص، الميكرو، الدوبل(آخر البيك اب)
    assert [names[[i for i, _ in delivery].index(b)] for b in bottoms] == [
        "خدمة على اللوري", "لوري ثاني", "خدمة باص", "خدمة ميك", "خدمة دوبل"]
    # الصف التالي لكل فاصل عليه حد علوي سميك كمان
    after = [table.rows[b + 1] for b in bottoms]
    assert all(all(_borders(tc).get("top") == 18 for tc in row._tr.tc_lst) for row in after)


def test_campaign_page_services_are_ordered_and_flagged():
    from backend.campaign import order_services
    mk = lambda ident, vtype, vid: {"id": ident, "service_vehicles": [{"vehicle": {"id": vid, "type": vtype}}]}
    rows = order_services([mk("a", "بيك اب", "V1"), mk("b", "لوري", "V2"), mk("c", "لوري", "V3"),
                           mk("d", "لوري", "V2"), {"id": "e", "service_vehicles": []}])
    assert [r["id"] for r in rows] == ["b", "d", "c", "a", "e"]
    assert [r["category_break"] for r in rows] == [False, True, True, True, False]
    assert rows[0]["vehicle_category"] == "lorry" and rows[-1]["vehicle_category"] == "other"


# ---------- 3. الانتظامات ----------

def test_regularity_vehicle_cell_is_plate_space_type_and_hides_external_party():
    from backend.regularity import _vehicle_label
    internal = {"vehicle": {"plate": "ب11/1111", "type": "لوري", "origin": "internal", "party": ""},
                "label": "ب11/1111 — لوري"}
    external = {"vehicle": {"plate": "ب12/2222", "type": "بيك اب", "origin": "external", "party": "جهة س"},
                "label": "ب12/2222 — بيك اب (خارجية: جهة س)"}
    assert _vehicle_label([internal]) == "ب11/1111 لوري"
    assert _vehicle_label([external]) == "ب12/2222 بيك اب"
    assert _vehicle_label([internal, external]) == "ب11/1111 لوري + ب12/2222 بيك اب"
    assert "—" not in _vehicle_label([external]) and "خارج" not in _vehicle_label([external])


# ---------- 4. إجمالي يومية الضباط ----------

def _summary(**outside):
    base = {key: 0 for key in ("تقصيرة", "راحة", "طارئة", "غياب", "مرضي", "فرقة", "انتداب")}
    base.update(outside)
    return {"أصل القوة": 5, "خارجية": {"صباحية": 0, "ليلية": 0, "بحث": 0},
            "داخلية": {"صباحية": 0, "ليلية": 0}, "طبية": {"موجود": 0, "راحة": 0},
            "خوارج": base, "حراسات": 0, "صافي": 0}


def _duty(summary):
    return {"date": "2026-09-29", "summary": summary, "rows": [{
        "section": "القوة", "role": "ملازم أول", "name": "ضابط", "post": "", "rest_system": "أسبوعية",
        "rest_day": None, "group": "صافي", "services": [], "status": "", "note": ""}]}


def _headers_and_values(summary):
    document = Document(BytesIO(duty_docx(_duty(summary)).getvalue()))
    table = document.tables[1]
    return ([c.text for c in table.rows[1].cells], [c.text for c in table.rows[2].cells],
            [int(g.get(qn("w:w"))) for g in table._tbl.tblGrid])


def test_custom_status_replaces_zero_daria_column():
    headers, values, _grid = _headers_and_values(_summary(**{"مؤتمر": 2, "تقصيرة": 1}))
    assert headers[9] == "مؤتمر" and values[9] == "2"
    assert headers[7] == "تقصيرة" and values[7] == "1"
    assert headers[10:15] == ["غياب", "مرضي", "فرقة", "مأمورية", "انتداب"]


def test_custom_status_keeps_nonzero_daria_and_takes_next_zero_column():
    headers, values, _grid = _headers_and_values(_summary(**{"مؤتمر": 2, "طارئة": 4}))
    assert headers[9] == "دورية" and values[9] == "4"
    assert headers[13] == "مؤتمر" and values[13] == "2"      # أول عمود صفر بعد دورية: مأمورية


def test_several_custom_statuses_take_zero_columns_in_order_and_total_is_kept():
    summary = _summary(**{"مؤتمر": 1, "ندوة": 2, "مهمة": 3})
    headers, values, _grid = _headers_and_values(summary)
    assert [headers[9], headers[13], headers[12]] == ["مؤتمر", "ندوة", "مهمة"]
    assert [values[9], values[13], values[12]] == ["1", "2", "3"]


def test_overflow_statuses_merge_into_last_replaced_column():
    # كل أعمدة الخوارج غير صفر إلا اثنين → حالتين تاخد العمودين والباقي بيتجمع
    summary = _summary(**{"تقصيرة": 1, "راحة": 1, "غياب": 1, "مرضي": 1, "انتداب": 1, "فرقة": 1,
                          "ح1": 1, "ح2": 2, "ح3": 3})
    headers, values, _grid = _headers_and_values(summary)
    assert headers[9] == "ح1" and values[9] == "1"
    assert headers[13] == "ح2 + ح3" and values[13] == "5"
    layout_values, _ = _summary_layout(summary)
    assert sum(int(v) for v in layout_values[7:15]) == 1 + 1 + 1 + 1 + 1 + 1 + 6


def test_custom_status_without_zero_column_folds_into_daria_like_before():
    summary = _summary(**{"تقصيرة": 1, "راحة": 1, "طارئة": 1, "غياب": 1, "مرضي": 1, "فرقة": 1,
                          "مأمورية": 1, "انتداب": 1, "مؤتمر": 2})
    headers, values, _grid = _headers_and_values(summary)
    assert headers[9] == "دورية" and values[9] == "3"


def test_no_custom_status_leaves_header_untouched_and_grid_unchanged():
    headers, values, grid = _headers_and_values(_summary())
    assert headers[7:15] == ["تقصيرة", "راحة", "دورية", "غياب", "مرضي", "فرقة", "مأمورية", "انتداب"]
    template = Document(__import__("backend.duty_export", fromlist=["TEMPLATE"]).TEMPLATE)
    assert grid == [int(g.get(qn("w:w"))) for g in template.tables[1]._tbl.tblGrid]
    assert _summary_values(_summary())[9] == 0

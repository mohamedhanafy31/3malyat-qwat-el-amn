from io import BytesIO

from docx import Document

from backend.campaign import order_campaign_rows, order_campaign_vehicle_rows
from backend.campaign_export import build_docx


def _delivery_rows(payload):
    document = Document(BytesIO(build_docx(payload).read()))
    rows = document.tables[0].rows
    start = next(index for index, row in enumerate(rows)
                 if row.cells[0].text == "م" and row.cells[1].text == "الخدمة") + 1
    return [[cell.text for cell in dict.fromkeys(row.cells)] for row in rows[start:]]


def _payload(**extra):
    payload = {"date": "2026-09-29", "posts": [], "lorries": [], "services": [],
               "daily": [], "appointments": [], "plates": {"rows": []}}
    payload.update(extra)
    return payload


def test_vehicle_grouping_uses_requested_type_without_plate_or_driver_and_is_stable():
    rows = order_campaign_vehicle_rows([
        {"id": "micro-1", "type_text": "ميكروباص"},
        {"id": "lorry", "vehicle": {"id": "v-l", "type": "لوري"}},
        {"id": "micro-2", "type_text": "ميكروباص", "driver": None},
        {"id": "pickup", "type_text": "بيك اب"},
        {"id": "unknown", "vehicle": None},
    ])

    assert [row["id"] for row in rows] == ["lorry", "micro-1", "micro-2", "pickup", "unknown"]
    assert [row["vehicle_group_label"] for row in rows] == [
        "لوري", "ميكروباص", "ميكروباص", "بيك اب", "غير محدد"]
    assert [row["vehicle_group_count"] for row in rows] == [1, 2, 2, 1, 1]
    assert rows[-1]["vehicle_group"] == "missing"


def test_word_delivery_order_groups_placeholder_type_and_keeps_unknown_last():
    payload = _payload(services=[
        {"id": "unknown", "name": "بلا نوع", "vehicle": None, "driver": None},
        {"id": "micro-1", "name": "ميكرو بلا لوحة", "vehicle": None, "driver": None,
         "service_vehicles": [{"vehicle": None, "type_text": "ميكروباص", "driver": None}]},
        {"id": "lorry", "name": "لوري بلا سائق", "vehicle": {"id": "v-l", "plate": "ب12/1",
                                                                        "type": "لوري"}, "driver": None},
        {"id": "micro-2", "name": "ميكرو بلوحة", "vehicle": {"id": "v-m", "plate": "ب12/2",
                                                                    "type": "ميكروباص"}, "driver": None},
    ])

    rows = _delivery_rows(payload)

    assert [row[1] for row in rows] == [
        "لوري بلا سائق", "ميكرو بلا لوحة", "ميكرو بلوحة", "بلا نوع"]
    assert len(rows) == 4


def test_campaign_delivery_rows_expose_type_group_headers_without_extra_rows():
    rows = order_campaign_rows([
        {"id": "a", "kind": "service", "name": "أ", "type_text": "ملاكي"},
        {"id": "b", "kind": "service", "name": "ب", "type_text": "لوري"},
        {"id": "c", "kind": "service", "name": "ج"},
    ], [])

    assert [row["id"] for row in rows] == ["b", "a", "c"]
    assert [row["band_label"] for row in rows] == ["لوري (1)", "ملاكي (1)", "غير محدد (1)"]
    assert sum(row["vehicle_group_count"] for row in rows) == 3

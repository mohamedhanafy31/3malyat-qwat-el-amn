from docx import Document

from backend import campaign
from backend.campaign_export import _post_plate, _post_type, build_docx

DAY = "2026-07-10"


def _vehicle(client, number, kind="بيك اب"):
    return client.post("/api/vehicles", json={
        "plate_series": "ب12", "plate_number": number, "type": kind,
    }).get_json()


def _assignment(client, name="خدمة متعددة"):
    return client.post(f"/api/assignments/{DAY}", json={
        "name": name, "kind": "خارجية", "section": "الخدمات الطارئة",
    }).get_json()


def _doc_text(campaign_data):
    doc = Document(build_docx(campaign_data))
    return " ".join(cell.text for table in doc.tables for row in table.rows for cell in row.cells)


def test_chosen_post_vehicle_wins_over_stale_free_text():
    merged = campaign._merge_inherited(
        {"vehicle_id": "old", "plate_text": "OLDPLATE", "type_text": "قديم"},
        {"vehicle_id": "new"},
    )
    assert merged == {"vehicle_id": "new"}
    assert campaign._inherited_from(
        {"vehicle_id": "2026-07-09", "plate_text": "2026-07-09", "type_text": "2026-07-09"},
        {"vehicle_id": "new"},
    ) == {}
    chosen = {"vehicle": {"plate": "ب12/4997", "type": "بيك اب", "model": "نيسان"},
              "plate_text": "OLDPLATE", "type_text": "قديم"}
    assert _post_plate(chosen) == "4997ب12"
    assert _post_type(chosen) == "بيك اب نيسان"


def test_export_prints_vehicle_plate_and_type_without_driver_for_all_row_kinds():
    vehicle = {"id": "v1", "plate": "ب12/4997", "type": "بيك اب", "model": "نيسان"}
    row = {"id": "1", "name": "اختبار", "vehicle": vehicle}
    doc = {
        "date": DAY,
        "posts": [{"number": 1, "name": "ارتكاز اختبار", "vehicle": vehicle}],
        "lorries": [dict(row, kind="lorry")],
        "appointments": [dict(row, kind="lorry", id="a1", name="مأمورية اختبار")],
        "services": [dict(row, kind="service", service_vehicles=[
            {"source": "direct", "vehicle": vehicle, "driver": None}])],
        "daily": [dict(row, kind="daily")],
        "plates": {"rows": []},
    }
    text = _doc_text(doc)
    assert text.count("4997ب12") >= 1
    assert text.count("بيك اب") >= 1
    assert "ـــــ" in text


def test_export_multi_vehicle_service_keeps_each_vehicle_category_and_line():
    pickup = {"id": "v1", "plate": "ب12/4997", "type": "بيك اب"}
    bus = {"id": "v2", "plate": "ب12/5997", "type": "اوتوبيس"}
    service = {"id": "s1", "kind": "service", "name": "خدمة متعددة", "service_vehicles": [
        {"source": "direct", "vehicle": pickup, "driver": None},
        {"source": "direct", "vehicle": bus, "driver": None},
    ]}
    doc = Document(build_docx({"date": DAY, "services": [service], "plates": {"rows": []}}))
    rows = [" ".join(cell.text for cell in row.cells) for row in doc.tables[0].rows]
    service_rows = [row for row in rows if "خدمة متعددة" in row]
    assert len(service_rows) == 2
    assert any("4997" in row and "بيك اب" in row for row in service_rows)
    assert any("5997" in row and "اوتوبيس" in row for row in service_rows)


def test_export_keeps_free_text_vehicle_fields_for_each_row_kind():
    free = {"plate_text": "نص لوحة", "type_text": "نص نوع"}
    service_rows = [
        {"id": "s", "kind": "service", "name": "خدمة نصية", **free,
         "service_vehicles": [{"source": "direct", "vehicle": None, "driver": None}]},
        {"id": "g", "kind": "group", "name": "مجموعة نصية", **free,
         "service_vehicles": [{"source": "group", "vehicle": None, "driver": None}]},
    ]
    data = {"date": DAY,
        "posts": [{"number": 1, "name": "ارتكاز نصي", **free}],
        "lorries": [{"id": "l", "kind": "lorry", "name": "لوري نصي", **free}],
        "appointments": [{"id": "a", "kind": "lorry", "name": "مأمورية نصية", **free}],
        "services": service_rows,
        "daily": [{"id": "d", "kind": "daily", "name": "قول نصي", **free}],
        "plates": {"rows": []}}
    text = _doc_text(data)
    assert text.count("نص لوحة") >= 6 and text.count("نص نوع") >= 6


def test_inline_vehicle_index_edit_keeps_other_vehicle_people(client):
    first, second = _vehicle(client, "4997"), _vehicle(client, "5997", "اوتوبيس")
    assignment = _assignment(client)
    person = client.post("/api/person", json={"type": "personnel", "name": "فرد الخدمة",
        "code": "971", "phone": "0101", "join_date": "2020-01-01", "role": "أمين شرطة"}).get_json()
    assert client.patch(f"/api/assignments/{DAY}/{assignment['id']}", json={
        "personnel_ids": [person["id"]]}).status_code == 200
    people = {"vehicle_id": first["id"], "personnel_ids": [person["id"]], "officer_ids": []}
    response = client.put(f"/api/campaign/{DAY}/service/{assignment['id']}", json={"vehicles": [
        people, {"vehicle_id": second["id"], "personnel_ids": [], "officer_ids": []},
    ]})
    assert response.status_code == 200
    row = next(row for row in response.get_json()["services"] if row["id"] == assignment["id"])
    assert row["status"] == "partial"
    assert row["status_text"] == "المركبة 1: ناقص سائق — المركبة 2: ناقص سائق"
    response = client.put(f"/api/campaign/{DAY}/service/{assignment['id']}", json={
        "vehicle_index": 1, "driver": {"kind": "text", "name": "سائق ثاني"},
    })
    assert response.status_code == 200, response.get_json()
    saved = response.get_json()["services"]
    # لا يسمح تحرير الفهرس بتقليص القائمة أو إسقاط توزيع الأفراد.
    from backend import store
    data = store.load_data()
    raw = data["day_campaign"][DAY]["services"][assignment["id"]]["vehicles"]
    assert [item["vehicle_id"] for item in raw] == [first["id"], second["id"]]
    assert raw[0]["personnel_ids"] == [person["id"]] and raw[1]["driver"]["name"] == "سائق ثاني"
    assert next(row for row in saved if row["id"] == assignment["id"])["status"] == "partial"
    removed = client.put(f"/api/campaign/{DAY}/service/{assignment['id']}", json={
        "vehicles": [raw[0]],
    })
    assert removed.status_code == 200
    remaining = next(row for row in removed.get_json()["services"] if row["id"] == assignment["id"])
    assert [item["vehicle_id"] for item in remaining["vehicles"]] == [first["id"]]
    assert remaining["vehicles"][0]["personnel_ids"] == [person["id"]]


def test_vehicle_field_group_explicit_empty_stops_inheritance():
    data = {"day_campaign": {
        "2026-07-08": {"posts": {"P": {"vehicle_id": "old", "plate_text": "old plate", "type_text": "old type"}}},
        "2026-07-09": {"posts": {"P": {"plate_text": ""}}},
    }}
    prior, sources = campaign._prior_with_sources(data, ["2026-07-08", "2026-07-09"], "posts", "P")
    assert prior == {"plate_text": ""}
    assert sources == {"plate_text": "2026-07-09"}


def test_blank_service_vehicle_line_counts_as_missing(client):
    assignment = _assignment(client, "خدمة بسطر فارغ")
    response = client.put(f"/api/campaign/{DAY}/service/{assignment['id']}", json={
        "vehicles": [{"vehicle_id": ""}],
    })
    assert response.status_code == 200, response.get_json()
    row = next(row for row in response.get_json()["services"] if row["id"] == assignment["id"])
    assert row["status"] == "empty"
    assert row["missing"] == ["driver:1", "vehicle:1"]
    assert row["status_text"] == "ناقص سائق ومركبة"


def test_multi_vehicle_status_groups_mixed_missing_fields(client):
    first, second = _vehicle(client, "4998"), _vehicle(client, "5998", "اوتوبيس")
    assignment = _assignment(client, "خدمة متعددة بنواقص مختلفة")
    response = client.put(f"/api/campaign/{DAY}/service/{assignment['id']}", json={
        "vehicles": [
            {"vehicle_id": first["id"]},
            {"vehicle_id": "", "driver": {"kind": "text", "name": "سائق السطر الثاني"}},
        ],
    })
    assert response.status_code == 200, response.get_json()
    row = next(row for row in response.get_json()["services"] if row["id"] == assignment["id"])
    assert row["missing"] == ["driver:1", "vehicle:2"]
    assert row["status_text"] == "المركبة 1: ناقص سائق — المركبة 2: ناقص مركبة"

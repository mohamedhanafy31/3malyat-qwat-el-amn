from backend import campaign
from backend.constants import CAMPAIGN_LORRIES
from backend.dated import campaign_lorries_on
from unittest.mock import patch


def test_lorry_changes_are_dated_and_seed_is_unchanged():
    data = {"reference_lists": {}, "day_campaign": {}}
    assert campaign_lorries_on(data, "2026-01-01") == CAMPAIGN_LORRIES
    ident, error, status = campaign.add_lorry(data, "2026-07-10", "لوري اختبار")
    assert (error, status) == (None, None)
    assert ident not in {item["id"] for item in CAMPAIGN_LORRIES}
    assert campaign_lorries_on(data, "2026-07-09") == CAMPAIGN_LORRIES
    assert campaign_lorries_on(data, "2026-07-10")[-1] == {"id": ident, "name": "لوري اختبار"}
    assert campaign_lorries_on(data, "2026-07-11")[-1]["id"] == ident
    assert campaign.remove_lorry(data, "2026-07-11", ident) == (None, None)
    assert any(item["id"] == ident for item in campaign_lorries_on(data, "2026-07-10"))
    assert all(item["id"] != ident for item in campaign_lorries_on(data, "2026-07-11"))


def test_removing_lorry_does_not_change_service_saved_data():
    ident = "AS-TEST-LO"
    lorry_id = "LOR-1"
    before = {"vehicles": [{"vehicle_id": "VEH-1", "driver": {"kind": "text", "name": "خاص"}}]}
    data = {
        "reference_lists": {},
        "day_campaign": {"2026-07-10": {"services": {ident: before.copy()},
            "lorries": {lorry_id: {"vehicle_id": "VEH-2", "driver": {"kind": "text", "name": "لوري"},
                                   "attached": [{"assignment_id": ident}]}}}},
    }
    original = __import__("copy").deepcopy(data["day_campaign"]["2026-07-10"]["services"][ident])
    with patch.object(campaign, "occasional_rows", return_value=[{"id": ident}]):
        assert campaign.remove_lorry(data, "2026-07-10", lorry_id) == (None, None)
    assert data["day_campaign"]["2026-07-10"]["services"][ident] == original


# ---- مسارات اللواري: الإضافة والحذف والتصدير والحماية ----

from io import BytesIO

from docx import Document

DAY = "2026-07-10"


def _rows(client, day=DAY):
    document = Document(BytesIO(client.get(f"/api/campaign/{day}/export.docx").data))
    return [" | ".join(dict.fromkeys(cell.text.strip() for cell in row.cells if cell.text.strip()))
            for row in document.tables[0].rows]


def _lorries(client, day=DAY):
    return client.get(f"/api/campaign/{day}").get_json()["lorries"]


def test_added_lorry_is_a_working_row_from_its_day_forward(client):
    assert client.post(f"/api/campaign/{DAY}/lorries", json={"name": "لوري جديد"}).status_code == 200
    added = next(item for item in _lorries(client) if item["name"] == "لوري جديد")
    assert added["id"] not in {"LOR-1", "LOR-2", "LOR-3", "LOR-4"}
    assert added["kind"] == "lorry" and added["status"] == "empty"
    assert any("لوري جديد" in row for row in _rows(client))
    assert "لوري جديد" in {item["name"] for item in _lorries(client, "2026-07-12")}      # لقدام
    assert "لوري جديد" not in {item["name"] for item in _lorries(client, "2026-07-09")}  # الماضي مايتأثرش


def test_added_lorry_takes_a_service_and_removal_returns_the_service(client):
    client.post(f"/api/campaign/{DAY}/lorries", json={"name": "لوري للإلحاق"})
    lorry_id = next(item["id"] for item in _lorries(client) if item["name"] == "لوري للإلحاق")
    service = client.post(f"/api/assignments/{DAY}", json={
        "name": "خدمة على لوري جديد", "kind": "خارجية", "section": "الخدمات الطارئة"}).get_json()["id"]
    assert client.post(f"/api/campaign/{DAY}/lorry/{lorry_id}/service",
                       json={"assignment_id": service}).status_code == 200
    row = next(item for item in _lorries(client) if item["id"] == lorry_id)
    assert "خدمة على لوري جديد" in row["name"]

    assert client.delete(f"/api/campaign/{DAY}/lorries/{lorry_id}").status_code == 200
    payload = client.get(f"/api/campaign/{DAY}").get_json()
    assert lorry_id not in {item["id"] for item in payload["lorries"]}
    assert service in {item["id"] for item in payload["service_rows"]}      # رجعت خدمة مستقلة
    assert not any("لوري للإلحاق" in row for row in _rows(client))


def test_lorry_validation_and_guards(client, anon_client):
    assert client.post(f"/api/campaign/{DAY}/lorries", json={"name": "   "}).status_code == 400
    assert client.post(f"/api/campaign/{DAY}/lorries", json={"name": CAMPAIGN_LORRIES[0]["name"]}
                       ).status_code == 400                                    # الاسم مكرر
    assert client.delete(f"/api/campaign/{DAY}/lorries/LOR-9999").status_code == 404
    assert anon_client.post(f"/api/campaign/{DAY}/lorries", json={"name": "ض"}).status_code == 401
    assert client.post(f"/api/day-status/{DAY}/close").status_code == 201
    assert client.post(f"/api/campaign/{DAY}/lorries", json={"name": "على يوم مقفول"}).status_code == 409
    assert client.delete(f"/api/campaign/{DAY}/lorries/LOR-1").status_code == 409


def test_untouched_days_keep_the_four_original_lorries(client):
    ids = [item["id"] for item in _lorries(client, "2026-06-01")]
    assert ids[:4] == ["LOR-1", "LOR-2", "LOR-3", "LOR-4"]
    assert not any(item["name"] == "لوري جديد" for item in _lorries(client, "2026-06-01"))

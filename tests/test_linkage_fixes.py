"""اختبارات عزل قسم السجن وربط الإسعاف المنظم."""
import importlib.util
import json

DAY = "2026-04-10"


def _assignment(client, name, section):
    response = client.post(f"/api/assignments/{DAY}", json={
        "name": name, "kind": "خارجية", "section": section, "shift": "صباحية",
    })
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def test_prison_aliases_are_excluded_from_afraad_counts_and_campaign(client):
    _assignment(client, "صف سجن", "فرد تأمين فترة ليلة")
    _assignment(client, "صف عادي", "الخدمات الطارئة")

    afraad = client.get(f"/api/afraad/{DAY}").get_json()
    assert [row["label"] for row in afraad["occasional"]] == ["صف عادي"]
    counts = client.get(f"/api/counts/{DAY}").get_json()
    assert [row["name"] for row in counts["emergency"]] == ["صف عادي"]
    campaign = client.get(f"/api/campaign/{DAY}").get_json()
    assert all(row["name"] != "صف سجن" for row in campaign["services"])


def test_basic_definition_validates_and_exposes_structured_fields(client):
    response = client.put(f"/api/afraad/{DAY}/basic-services/AFB-19", json={
        "location_text": "الحماية المدنية", "conscript_count": 3,
    })
    assert response.status_code == 200
    row = next(item for item in response.get_json()["basic"] if item["id"] == "AFB-19")
    assert row["location_text"] == "الحماية المدنية" and row["conscript_count"] == 3

    bad = client.put(f"/api/afraad/{DAY}/basic-services/AFB-19", json={"conscript_count": -1})
    assert bad.status_code == 400


def test_basic_count_is_derived_from_one_unambiguous_parenthesized_count(client):
    response = client.put(f"/api/afraad/{DAY}/basic/AFB-19", json={"count": "ميك فض (3 مجند)"})
    assert response.status_code == 200
    row = next(item for item in response.get_json()["basic"] if item["id"] == "AFB-19")
    assert row["conscript_count"] == 3


def test_campaign_daily_resolves_basic_service_by_id(client):
    response = client.post(f"/api/campaign/{DAY}/daily-rows", json={
        "name": "ارتكاز الاسعاف", "basic_entry_id": "AFB-19",
    })
    assert response.status_code == 200, response.get_json()
    row = next(item for item in response.get_json()["daily"] if item["name"] == "ارتكاز الاسعاف")
    assert row["basic_entry_id"] == "AFB-19"
    assert row["basic_service"]["name"] == "الإسعاف"


def test_migration_020_is_idempotent_on_temp_data(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("migration_020", "migrations/020_link_ambulance.py")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    data = {
        "schema": 6, "reference_lists": {
            "afraad_basic": [{"from": "2026-01-01", "items": [
                {"id": "AFB-19", "name": "الإسعاف", "count": "ميك (3 مجند)"},
            ]}],
            "campaign_daily": [{"from": "2026-01-01", "items": [
                {"id": "CD-005", "name": "ارتكاز الاسعاف"},
            ]}],
        }, "day_afraad": {}, "_migrations": [],
    }
    source = tmp_path / "data.json"
    source.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    common = importlib.import_module("common")
    monkeypatch.setattr(common, "DATA_FILE", source)
    monkeypatch.setattr(common, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(common, "split_mode", lambda: False)
    original = source.read_text(encoding="utf-8")
    monkeypatch.setattr(common.sys, "argv", ["020"])
    common.run(6, 6, migration.migrate, "اختبار")
    assert source.read_text(encoding="utf-8") == original
    monkeypatch.setattr(common.sys, "argv", ["020", "--write"])
    common.run(6, 6, migration.migrate, "اختبار")
    result = json.loads(source.read_text(encoding="utf-8"))
    assert result["reference_lists"]["afraad_basic"][0]["items"][0]["conscript_count"] == 3
    assert result["reference_lists"]["afraad_basic"][0]["items"][0]["location_text"] == "الحماية المدنية"
    assert result["reference_lists"]["campaign_daily"][0]["items"][0]["basic_entry_id"] == "AFB-19"
    common.run(6, 6, migration.migrate, "اختبار")

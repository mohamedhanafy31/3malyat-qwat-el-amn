import importlib.util
from pathlib import Path

import pytest

from backend import store


def _add_service(client, name, tags):
    response = client.post("/api/service-catalog/entries", json={"name": name, "tags": tags})
    assert response.status_code == 201
    return response.get_json()


def _line_body(tag, **extra):
    return {"name": f"خط {tag}", "tag": tag, "lorry_id": "", "order": [],
            "depart_am": "8 ص", "depart_pm": "8 م", **extra}


def test_service_line_crud_returns_expanded_members_and_delete_keeps_catalog(client):
    service = _add_service(client, "خدمة فيصل", ["فيصل"])
    created = client.post("/api/service-lines", json=_line_body("فيصل", order=[service["id"]]))
    assert created.status_code == 201
    line = created.get_json()
    assert line["id"].startswith("LN-") and line["members"][0]["id"] == service["id"]
    edited = client.patch(f"/api/service-lines/{line['id']}", json={"name": "خط فيصل المعدل", "depart_am": "09:30"})
    assert edited.status_code == 200 and edited.get_json()["depart_am"] == "09:30"
    assert client.delete(f"/api/service-lines/{line['id']}").get_json() == {"ok": True}
    assert client.get("/api/service-catalog").get_json()["entries"][0]["id"] == service["id"]


@pytest.mark.parametrize("body", [
    {"name": ""},
    {"name": "x" * 121},
    {"tag": "غير موجود"},
    {"lorry_id": "LOR-X"},
    {"depart_am": "مش وقت"},
    {"order": ["SVC-999"]},
])
def test_service_line_validation_failures(client, body):
    _add_service(client, "خدمة", ["وسم"])
    response = client.post("/api/service-lines", json={**_line_body("وسم"), **body})
    assert response.status_code == 400


def test_service_line_rejects_duplicate_tag_and_lorry(client):
    _add_service(client, "أ", ["أ"])
    _add_service(client, "ب", ["ب"])
    assert client.post("/api/service-lines", json=_line_body("أ", lorry_id="LOR-1")).status_code == 201
    assert client.post("/api/service-lines", json=_line_body("أ")).status_code == 400
    assert client.post("/api/service-lines", json=_line_body("ب", lorry_id="LOR-1")).status_code == 400


def test_service_line_rejects_overlapping_membership(client):
    _add_service(client, "خدمة مشتركة", ["أ", "ب"])
    assert client.post("/api/service-lines", json=_line_body("أ")).status_code == 201
    conflict = client.post("/api/service-lines", json=_line_body("ب"))
    assert conflict.status_code == 400 and "خدمة مشتركة" in conflict.get_json()["error"]


def test_migration_019_seeds_empty_registry_and_is_noop_with_existing_lines():
    path = Path(__file__).parents[1] / "migrations" / "019_seed_service_lines.py"
    spec = importlib.util.spec_from_file_location("migration_019_test", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    empty = {"service_lines": [], "_migrations": []}
    report = migration.migrate(empty)
    assert len(empty["service_lines"]) == 4 and report
    existing = {"service_lines": [{"id": "LN-9", "name": "موجود"}], "_migrations": []}
    with pytest.raises(migration.AlreadyDone):
        migration.migrate(existing)
    assert existing["service_lines"] == [{"id": "LN-9", "name": "موجود"}]


def test_bulk_ops_route_moves_only_selected_keys(client):
    def seed(data):
        data["service_catalog"] = [
            {"id": "SVC-1", "name": "أ", "period": "صباحية", "report_am": "08:00", "tags": []},
            {"id": "SVC-2", "name": "ب", "period": "صباحية", "report_am": "08:00", "tags": []},
        ]
        data["service_counts"] = {"2026-10-20": {"entries": [
            {"id": "CNT-1", "name": "أ", "service_id": "SVC-1", "block": "صباحية", "count": 1},
            {"id": "CNT-2", "name": "ب", "service_id": "SVC-2", "block": "صباحية", "count": 1},
        ]}}
    store.with_data(seed, ())
    response = client.post("/api/ops/2026-10-20/depart", json={
        "keys": ["SVC-1:am"], "now": "2026-10-20T08:01:00"})
    assert response.status_code == 200
    state = store.assemble().get("day_service_runs", {}).get("2026-10-20", {})
    assert state["SVC-1:am"]["out_at"] and "SVC-2:am" not in state

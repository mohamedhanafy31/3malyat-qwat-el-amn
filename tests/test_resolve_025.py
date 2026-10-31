from copy import deepcopy
from importlib import import_module
from types import SimpleNamespace

import pytest

from importer.campaign import Op


migration = import_module("migrations.025_resolve_unresolved")


def test_person_upgrade_fills_text_or_empty_but_never_overwrites_link():
    op = Op(("services", "AS-1", "driver"), {"kind": "personnel", "id": "IND-2"}, "خدمة", "أحمد محمد")
    data = {"day_campaign": {}}
    assert migration._allowed({}, op, data, "2026-08-01")[0]
    assert migration._allowed({"kind": "text", "id": "", "name": "أحمد محمد"}, op, data, "2026-08-01")[0]
    assert not migration._allowed({"kind": "personnel", "id": "IND-1"}, op, data, "2026-08-01")[0]


def test_dry_run_no_change_and_idempotent_when_no_candidates(monkeypatch, tmp_path):
    data = {"schema": 6, "change_log": []}
    original = deepcopy(data)
    empty = {"counts": migration.Counter(), "medium": [], "unresolved": [], "conflicts": [], "changes": []}
    monkeypatch.setattr(migration, "_campaign_pass", lambda *_: deepcopy(empty))
    monkeypatch.setattr(migration, "_gaps_pass", lambda *_: deepcopy(empty))
    options = SimpleNamespace(archive_root=tmp_path, start="2026-08-01", end=None, report=None, write=False)
    with pytest.raises(migration.AlreadyDone):
        migration.migrate(data, options)
    assert data == original
    with pytest.raises(migration.AlreadyDone):
        migration.migrate(data, options)
    assert data == original


def test_seeding_a_day_keeps_inherited_vehicles_for_following_days():
    data = {"day_campaign": {"2026-09-30": {
        "lorries": {"LOR-1": {"vehicle_id": "VEH-1", "attached": [{"assignment_id": "AS-9"}]}},
        "plates": {"rows": [["1/ب"]]}}}}
    assert migration._seed_day(data, "2026-10-01")
    seeded = data["day_campaign"]["2026-10-01"]
    assert seeded["lorries"]["LOR-1"] == {"vehicle_id": "VEH-1"}
    assert seeded["plates"] == {"rows": [["1/ب"]]}
    assert not migration._seed_day(data, "2026-10-01")

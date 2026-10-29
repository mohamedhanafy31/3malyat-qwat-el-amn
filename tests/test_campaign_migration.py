from copy import deepcopy
from importlib import import_module

migration = import_module("migrations.021_campaign_vehicles")


def test_campaign_vehicles_migration_is_idempotent_and_preserves_assignment_people():
    data = {
        "_migrations": [],
        "day_assignments": {"2026-07-10": [{"id": "AS-1", "personnel_ids": ["IND-1"],
                                               "officer_ids": ["OFF-1"]}]},
        "day_campaign": {"2026-07-10": {"services": {"AS-1": {"vehicle_id": "VEH-1"}}}},
    }
    before = deepcopy(data)
    report = migration.migrate(data)
    assert report and data["day_campaign"]["2026-07-10"]["services"]["AS-1"] == {
        "vehicles": [{"vehicle_id": "VEH-1", "personnel_ids": ["IND-1"], "officer_ids": ["OFF-1"]}]}
    assert before["day_campaign"]["2026-07-10"]["services"]["AS-1"] == {"vehicle_id": "VEH-1"}
    try:
        migration.migrate(data)
    except migration.AlreadyDone:
        pass
    else:
        raise AssertionError("الهجرة المفروض تعتبر نفسها اتعملت")

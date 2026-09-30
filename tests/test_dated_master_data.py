import importlib.util
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from backend.afraad import BASIC_SERVICES, basic_rows, set_basic_entry
from backend.board import build_board
from backend.constants import ROLE_MEDICAL
from backend.dated import afraad_basic_on, command_on, groups_on, targets_on
from backend.duty import summarise
from backend.people import effective, record_change
from backend.references import cascade_delete
from backend.repo import Repos
from tools.check_integrity import check as integrity_check


def test_officer_rest_and_individual_grade_are_effective_by_day():
    officer = {"id": "OFF-900", "join_date": "2023-01-01", "role": "نقيب",
               "post": "عمل قديم", "section": "القوة", "search_attached": False,
               "rest_system": "أسبوعية", "rest_day": "السبت"}
    record_change(officer, "2025-01-01", {"rest_system": "شهرية", "rest_day": ""})
    assert effective(officer, "2024-12-31")["rest_day"] == "السبت"
    assert effective(officer, "2025-01-01")["rest_system"] == "شهرية"

    individual = {"id": "IND-900", "join_date": "2023-01-01",
                  "role": "أمين شرطة ثان", "post": "عمل أول"}
    record_change(individual, "2025-02-01",
                  {"role": "أمين شرطة أول", "post": "عمل ثان"})
    assert effective(individual, "2024-01-01") == {
        "role": "أمين شرطة ثان", "post": "عمل أول"}
    assert effective(individual, "2026-01-01")["role"] == "أمين شرطة أول"


def _dated_data():
    return {
        "officers": [
            {"id": "OFF-901", "name": "ضابط طبي قديم", "role": "نقيب", "code": "901",
             "phone": "0101", "join_date": "2023-01-01", "post": "", "status": "active",
             "rest_system": "—", "rest_day": ""},
            {"id": "OFF-902", "name": "ضابط طبي جديد", "role": "ملازم", "code": "902",
             "phone": "0102", "join_date": "2023-01-01", "post": "", "status": "active",
             "rest_system": "—", "rest_day": ""},
        ],
        "personnel": [], "leaves": [], "courses": [], "course_terms": [],
        "day_assignments": {}, "day_officers": {}, "command": {}, "command_groups": {},
        "command_history": [
            {"from": "2023-01-01", "command": {}, "groups": {ROLE_MEDICAL: ["OFF-901"], "بحث": []}},
            {"from": "2025-01-01", "command": {}, "groups": {ROLE_MEDICAL: ["OFF-902"], "بحث": []}},
        ],
    }


def test_historical_medical_group_controls_summary_and_board():
    data = _dated_data()
    old = summarise(data, "2024-06-01")
    assert next(r for r in old["rows"] if r["id"] == "OFF-901")["group"] == "طبية"
    assert next(r for r in old["rows"] if r["id"] == "OFF-902")["group"] == "صافي"
    old_roster = build_board(data, "2024-06-01")["roster"]["officers"]
    assert {r["id"] for r in old_roster} == {"OFF-902"}
    new_roster = build_board(data, "2026-06-01")["roster"]["officers"]
    assert {r["id"] for r in new_roster} == {"OFF-901"}


def test_dated_reference_lists_and_stable_afraad_ids():
    data = {"reference_lists": {
        "targets": [{"from": "2023-01-01", "names": ["مشرف قديم", "هدف قديم"]},
                    {"from": "2026-01-01", "names": ["مشرف جديد"]}],
        "afraad_basic": [
            {"from": "2023-01-01", "items": [{"id": "AFB-01", "name": "خدمة مشتركة"}]},
            {"from": "2026-01-01", "items": [{"id": "AFB-99", "name": "خدمة مشتركة"},
                                                  {"id": "AFB-23", "name": "خدمة جديدة"}]},
        ]}}
    assert targets_on(data, "2024-01-01") == ["مشرف قديم", "هدف قديم"]
    assert targets_on(data, "2026-01-01") == ["مشرف جديد"]
    assert afraad_basic_on(data, "2024-01-01")[0]["id"] == "AFB-01"
    assert [r["id"] for r in basic_rows(data, "2026-01-01")] == ["AFB-01", "AFB-23"]
    assert targets_on({}, "2023-01-01")[0] == "مشرف الأهداف"
    assert afraad_basic_on({}, "2023-01-01") == BASIC_SERVICES


def test_afraad_person_link_validation_stale_clear_and_cleanup():
    data = {"personnel": [{"id": "IND-901", "name": "فرد تجريبي", "role": "أمين شرطة ثان",
                            "code": "901", "phone": "0101", "join_date": "2023-01-01",
                            "status": "active"}], "officers": [], "day_afraad": {}}
    row, error, _ = set_basic_entry(data, "2026-01-01", "AFB-01", {
        "morning_name": "اسم مرتبط", "morning_person_id": "IND-901"})
    assert error is None and row["morning_person_id"] == "IND-901"
    _row, error, status = set_basic_entry(data, "2026-01-01", "AFB-01",
                                          {"night_person_id": "IND-404"})
    assert status == 400 and "غير موجود" in error
    set_basic_entry(data, "2026-01-01", "AFB-01", {"morning_name": "اسم مصحح"})
    assert "morning_person_id" not in data["day_afraad"]["2026-01-01"]["AFB-01"]
    data["day_afraad"]["2026-01-01"]["AFB-01"]["night_person_id"] = "IND-901"
    assert integrity_check(data) == []
    report = cascade_delete(Repos(data), "IND-901", "personnel")
    assert report["day_afraad.*.morning_person_id / night_person_id"] == 1
    data["personnel"] = []
    assert integrity_check(data) == []


def _migration(number, name):
    path = Path(__file__).parents[1] / "migrations" / f"{number}_{name}.py"
    spec = importlib.util.spec_from_file_location(f"migration_{number}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migrations_015_016_seed_and_are_idempotent():
    data = {"schema": 6, "officers": [], "personnel": [],
            "day_assignments": {"2023-10-01": []},
            "command": {"مدير الإدارة": "OFF-001", "وكيل الإدارة": None},
            "command_groups": {"طبي": ["OFF-002"], "بحث": []}}
    m15 = _migration("015", "seed_command_history")
    m16 = _migration("016", "seed_reference_lists")
    m15.migrate(data)
    assert data["command_history"][0]["from"] == "2023-10-01"
    assert command_on(data, "2024-01-01")["مدير الإدارة"] == "OFF-001"
    assert groups_on(data, "2024-01-01")["طبي"] == ["OFF-002"]
    with pytest.raises(m15.AlreadyDone):
        m15.migrate(data)
    m16.migrate(data)
    assert data["reference_lists"]["targets"][0]["from"] == "2023-10-01"
    assert data["reference_lists"]["afraad_basic"][0]["items"] == BASIC_SERVICES
    with pytest.raises(m16.AlreadyDone):
        m16.migrate(data)


@pytest.mark.parametrize("script,key", [
    ("015_seed_command_history.py", "command_history"),
    ("016_seed_reference_lists.py", "reference_lists"),
])
def test_migration_cli_dry_run_write_and_already_done(tmp_path, script, key):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    core = {
        "schema": 6, "officers": [], "personnel": [], "leaves": [],
        "command": {"مدير الإدارة": None, "وكيل الإدارة": None},
        "command_groups": {"طبي": [], "بحث": []},
    }
    core_path = data_dir / "core.json"
    core_path.write_text(json.dumps(core, ensure_ascii=False), encoding="utf-8")
    env = {**os.environ, "PERSONNEL_DATA_DIR": str(data_dir)}
    command = [sys.executable, str(Path(__file__).parents[1] / "migrations" / script)]

    before = core_path.read_bytes()
    dry = subprocess.run(command, cwd=Path(__file__).parents[1], env=env,
                         text=True, capture_output=True, check=True)
    assert "عرض بس" in dry.stdout and core_path.read_bytes() == before

    subprocess.run([*command, "--write"], cwd=Path(__file__).parents[1], env=env,
                   text=True, capture_output=True, check=True)
    assert key in json.loads(core_path.read_text(encoding="utf-8"))
    again = subprocess.run([*command, "--write"], cwd=Path(__file__).parents[1], env=env,
                           text=True, capture_output=True, check=True)
    assert "موجود" in again.stdout

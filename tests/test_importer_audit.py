import csv
import json
from datetime import date

from importer.audit import run_audit
from importer.ledger import Ledger


def _day(name, imported=False):
    day = {"assignments": [{"id": "AS-1", "section": "خدمات", "name": name,
                            "kind": "خارجية", "shift": "صباحية", "officer_ids": ["OFF-1"],
                            "personnel_ids": [], "conscripts": [], "conscript_count": 0,
                            "weapon": "", "time": "", "party": "", "counts_in_summary": True,
                            "note": ""}], "officer_states": {"OFF-1": {"note": name}}}
    if imported:
        day["import"] = {"batch": "B1", "at": "B1", "derived": False, "sources": []}
    return day


def _fixture(tmp_path):
    data = tmp_path / "data"
    (data / "days" / "2025" / "01").mkdir(parents=True)
    (data / "core.json").write_text(json.dumps({"schema": 6, "officers": [], "personnel": []}), encoding="utf-8")
    ledger = Ledger(data, "B1")
    state = ledger.initialise({}, {})
    report = ledger.root / "reports"
    report.mkdir(parents=True, exist_ok=True)
    (report / "B1-manifest.csv").write_text(
        "date,roster,afraad,notes\n"
        "2025-01-01,1.docx,1.docx,\n"
        "2025-01-02,,2.docx,\n",
        encoding="utf-8")
    days = ledger.root / "staging" / "B1" / "transform" / "days"
    days.mkdir(parents=True)
    for date, name in (("2025-01-01", "مرجع"), ("2025-01-02", "جزئي")):
        (days / f"{date}.json").write_text(json.dumps(_day(name)), encoding="utf-8")
    return ledger, state


def test_audit_classifies_add_review_skip_and_mismatch(tmp_path):
    ledger, state = _fixture(tmp_path)
    (ledger.data_dir / "days" / "2025" / "01" / "2025-01-01.json").write_text(
        json.dumps(_day("حالي")), encoding="utf-8")
    result = run_audit(ledger, date(2025, 1, 1), date(2025, 1, 3), state)
    by_date = {row["date"]: row for row in result["rows"]}
    assert by_date["2025-01-01"]["action"] == "skip"
    assert by_date["2025-01-01"]["target_status"] == "unverified"
    assert by_date["2025-01-01"]["missing_rows"] == 1
    assert by_date["2025-01-02"]["action"] == "review"
    assert by_date["2025-01-03"]["source_status"] == "source_gap"
    assert by_date["2025-01-03"]["action"] == "skip"
    with (ledger.root / "reports" / "B1-audit.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 3

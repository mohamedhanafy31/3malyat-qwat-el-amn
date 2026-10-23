import json

from importer.ledger import Ledger, atomic_write_jsonl
from importer.preview import inspect_day, run_preview


def _board_row(label="ترحيلة العاشر", manning="فرد + مج"):
    return {
        "date": "2026-10-04", "role": "board", "record_type": "board_row", "path": "2026/10/4/4.docx",
        "table_index": 0, "row_index": 1, "half": 1, "label": label, "manning": manning,
        "extra_cells": [], "raw_cells": [label, manning], "column_indexes": [[2, 3], [4, 5]], "stale": False,
    }


def _header():
    return {
        "date": "2026-10-04", "role": "board", "record_type": "header", "path": "2026/10/4/4.docx",
        "table_index": 0, "row_index": 0, "half_starts": [0, 2],
        "half_labels": ["الخدمات الأساسية", "الخدمات الطارئة"], "known_section": True,
        "raw_cells": ["الخدمات الأساسية", "الخدمات الطارئة"], "column_indexes": [[0, 1], [2, 3, 4]], "stale": False,
    }


def _day():
    return {"assignments": [{"section": "الخدمات الطارئة", "name": "ترحيلة العاشر", "shift": "صباحية",
                              "officer_ids": [], "personnel_ids": [], "conscript_count": 1, "time": "7ص"}]}


def test_preview_accepts_accounted_independent_lanes():
    result = inspect_day("2026-10-04", [_header(), _board_row()], _day(), [], {})
    assert result["errors"] == 0 and result["source_rows"] == 1


def test_preview_rejects_shifted_strength_and_dropped_cells():
    row = _board_row("فرد + 2 مج", "ترحيلة العاشر")
    row["raw_cells"].append("تفصيل ساقط")
    result = inspect_day("2026-10-04", [_header(), row], _day(), [], {})
    codes = {item["code"] for item in result["issues"]}
    assert {"unaccounted_cells", "strength_used_as_service", "shifted_service_columns"} <= codes


def test_run_preview_writes_summary_day_report_and_quarantine(tmp_path):
    ledger = Ledger(tmp_path / "data", "OCT")
    state = ledger.initialise({}, {"preview": "1"})
    atomic_write_jsonl(ledger.staging_path("extract"), [_header(), _board_row()])
    days = ledger.root / "staging" / "OCT" / "transform" / "days"
    days.mkdir(parents=True)
    (days / "2026-10-04.json").write_text(json.dumps(_day(), ensure_ascii=False), encoding="utf-8")
    atomic_write_jsonl(ledger.staging_path("transform-review"), [])

    summary = run_preview(ledger, state)

    assert summary["passed"] == 1 and summary["quarantined"] == 0
    assert ledger.report_path("preview.md").exists()
    assert (ledger.root / "reports" / "OCT-preview" / "2026-10-04.md").exists()
    quarantine = json.loads((ledger.root / "quarantine" / "OCT-preview.json").read_text(encoding="utf-8"))
    assert quarantine == {"days": {}}

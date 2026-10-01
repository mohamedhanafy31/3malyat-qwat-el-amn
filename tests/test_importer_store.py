import csv
import hashlib
import json

import pytest

from backend import store
from importer import store as importer_store
from importer.ledger import Ledger
from importer.store import StoreRefused, run_diff, run_rollback, run_store

BATCH = "T1"


def _row(name, officer="OFF-001"):
    return {"id": "AS-0001", "section": "الخدمات الطارئة", "name": name, "kind": "خارجية", "shift": "صباحية",
            "officer_ids": [officer], "personnel_ids": [], "conscripts": [], "conscript_count": 0, "weapon": "",
            "time": "", "party": "", "counts_in_summary": True, "note": ""}


def _imported(name):
    return {"assignments": [_row(name)], "assignment_seq": 1, "officer_states": {"OFF-001": {"note": name}},
            "import": {"batch": BATCH, "at": BATCH, "derived": False, "sources": []}}


@pytest.fixture
def batch(data_file, monkeypatch):
    importer_store._LOCKED.add(str(store.DATA_DIR.resolve()))  # الاختبار مش سيرفر
    data = store.load_data()
    data["day_assignments"]["2025-02-01"] = [_row("خدمة من النظام")]
    store.save_data(data)
    ledger = Ledger(store.DATA_DIR, BATCH)
    state = ledger.initialise({}, {})
    state["stages"]["verify"] = {"status": "complete"}
    days = ledger.root / "staging" / BATCH / "transform" / "days"
    days.mkdir(parents=True)
    for date, name in (("2025-01-05", "ترحيلة"), ("2025-02-01", "ترحيلة الأرشيف"), ("2026-09-01", "يوم مرجعي")):
        (days / f"{date}.json").write_text(json.dumps(_imported(name), ensure_ascii=False), encoding="utf-8")
    (days.parent / "core_delta.json").write_text(json.dumps(
        {"officers": [], "personnel": [], "leaves": [], "command_history": [], "reference_lists": {}}), encoding="utf-8")
    return ledger, state


def _hashes():
    return {str(p.relative_to(store.DATA_DIR)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(store.DATA_DIR.rglob("*.json")) if "import" not in p.parts}


def test_dry_run_writes_nothing_and_store_is_idempotent(batch):
    ledger, state = batch
    before = _hashes()
    report = run_store(ledger, state)
    assert report["plan"] == {"write": 1, "skip": 2} and _hashes() == before
    run_store(ledger, state, write=True)
    after = _hashes()
    assert "days/2025/01/2025-01-05.json" in after and "days/2026/09/2026-09-01.json" not in after
    again = run_store(ledger, state, write=True)
    assert again["files_to_write"] == 0 and _hashes() == after


def test_store_requires_verify(batch):
    ledger, state = batch
    state["stages"]["verify"] = {"status": "running"}
    with pytest.raises(StoreRefused):
        run_store(ledger, state, write=True)


def test_in_app_day_needs_flag_and_written_approval(batch):
    ledger, state = batch
    assert run_store(ledger, state, replace_existing=True)["skipped"]["2025-02-01"].endswith("replace.csv")
    run_diff(ledger, state)
    approvals = ledger.root / "decisions" / "replace.csv"
    rows = list(csv.DictReader(approvals.open(encoding="utf-8-sig")))
    assert [row["date"] for row in rows] == ["2025-02-01"]
    assert (ledger.root / "reports" / f"{BATCH}-replace-diff" / "2025-02-01.md").exists()
    approvals.write_text("﻿date,approve,note\n2025-02-01,نعم,راجعت الفرق\n", encoding="utf-8")
    assert "2025-02-01" in run_store(ledger, state)["skipped"]
    run_store(ledger, state, write=True, replace_existing=True)
    day = json.loads(store.day_path("2025-02-01").read_text(encoding="utf-8"))
    assert day["assignments"][0]["name"] == "ترحيلة الأرشيف" and day["import"]["batch"] == BATCH


def test_rollback_restores_every_file_byte_for_byte(batch):
    ledger, state = batch
    before = _hashes()
    run_store(ledger, state, write=True)
    assert _hashes() != before
    result = run_rollback(ledger, state, write=True)
    assert result["mismatches"] == [] and _hashes() == before
    assert not store.day_path("2025-01-05").exists()


def test_resume_after_a_crash_mid_write(batch, monkeypatch):
    ledger, state = batch
    before = _hashes()
    real = store._write_atomic
    calls = {"n": 0}

    def crash(path, text):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("انقطاع كهربا")
        real(path, text)

    monkeypatch.setattr(store, "_write_atomic", crash)
    with pytest.raises(OSError):
        run_store(ledger, state, write=True)
    monkeypatch.setattr(store, "_write_atomic", real)
    store._cache.clear()
    run_store(ledger, state, write=True, resume=True)
    assert store.day_path("2025-01-05").exists()
    manifest = json.loads((ledger.root / "preimage" / BATCH / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["core.json"]["sha256"] == before["core.json"]  # الأصل الأول ما اتكتبش فوقه
    run_rollback(ledger, state, write=True)
    assert _hashes() == before

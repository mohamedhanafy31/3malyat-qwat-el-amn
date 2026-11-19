"""أدوات ترقية التخزين: دمج سجل قديم، وحماية البيانات المحلية قبل السحب."""
import json

from backend import store
from tools import migrate_storage, protect_before_pull


def _entry(n, ts):
    return {"id": f"CHG-{n:03d}", "ts": ts, "entity": "x", "entity_id": str(n), "action": "create",
            "day": None, "text": f"t{n}", "before": None, "after": None, "reason": "", "edited_by": None}


def test_legacy_core_log_is_merged_without_duplicates_and_in_time_order(client, tmp_path):
    path = store.change_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(_entry(n, f"2026-02-0{n}T00:00:00")) + "\n" for n in (3, 4)),
                    encoding="utf-8")
    legacy = tmp_path / "old-core.json"
    legacy.write_text(json.dumps({"change_log": [_entry(1, "2026-02-01T00:00:00"),
                                                  _entry(2, "2026-02-02T00:00:00"),
                                                  _entry(3, "2026-02-03T00:00:00")]}), encoding="utf-8")

    migrate_storage._merge_legacy_log(legacy)

    ids = [json.loads(line)["id"] for line in path.read_text(encoding="utf-8").splitlines()]
    assert ids == ["CHG-001", "CHG-002", "CHG-003", "CHG-004"]


def test_protect_backup_and_restore_round_trip(tmp_path, monkeypatch):
    root = tmp_path / "project"
    (root / "data" / "days" / "2026" / "11").mkdir(parents=True)
    (root / "data" / "days" / "2026" / "11" / "2026-11-16.json").write_text('{"assignments": []}', encoding="utf-8")
    (root / "data" / "core").mkdir(parents=True)
    (root / "data" / "core" / "force.json").write_text('{}', encoding="utf-8")
    (root / "data" / "core.json").write_text("{}", encoding="utf-8")
    (root / "logs").mkdir()
    (root / "logs" / "audit.log").write_text("x", encoding="utf-8")
    monkeypatch.setattr(protect_before_pull, "ROOT", root)
    monkeypatch.setattr(protect_before_pull, "DATA", root / "data")

    kept = protect_before_pull.backup()
    assert (kept / "core" / "force.json").exists() and (kept / "core.json").exists()
    import shutil
    shutil.rmtree(root / "data" / "days")                  # اللي بيعمله السحب
    shutil.rmtree(root / "logs")
    protect_before_pull.restore(kept)

    assert (root / "data" / "days" / "2026" / "11" / "2026-11-16.json").read_text(encoding="utf-8") == '{"assignments": []}'
    assert (root / "logs" / "audit.log").exists()

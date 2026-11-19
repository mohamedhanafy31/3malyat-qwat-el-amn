"""Core storage: topic files, legacy migration, backups, and journal recovery."""
import json
import shutil
import zipfile

from backend import store


def _core_files():
    return {path.name: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in store.core_dir().glob("*.json")}


def _normalised_snapshot():
    data = store.load_data(store.ALL_DAYS)
    store.save_data(data)
    return store.assemble()


def test_core_is_saved_as_topic_files(data_file):
    core = store.read_core_at(store.DATA_DIR)

    assert store.core_exists()
    assert store.core_dir().is_dir()
    assert not store.core_file().exists()
    assert {path.name for path in store.core_dir().glob("*.json")} == set(store._split_core(core))
    assert {"force.json", "leaves.json"} <= set(store._split_core(core))


def test_editing_leaves_rewrites_only_leaves_topic(data_file):
    store.save_data(store.load_data(store.ALL_DAYS))
    before = _core_files()
    data = store.load_data(store.ALL_DAYS)
    data["leaves"].append({"id": "LV-NEW", "person_id": "OFF-001", "type": "أسبوعية"})
    store.save_data(data)
    after = _core_files()

    assert after["leaves.json"][0] != before["leaves.json"][0]
    assert {name: value for name, value in after.items() if name != "leaves.json"} == {
        name: value for name, value in before.items() if name != "leaves.json"
    }


def test_legacy_core_is_read_and_migrated_on_first_write(data_file):
    data = store.load_data(store.ALL_DAYS)
    store.save_data(data)
    expected = store.read_core_at(store.DATA_DIR)
    shutil.rmtree(store.core_dir())
    store.core_file().write_text(json.dumps(expected, ensure_ascii=False, indent=2), encoding="utf-8")
    store._cache.clear()

    assert store.core_exists()
    assert store.read_core_at(store.DATA_DIR) == expected
    store.save_data(store.load_data(store.ALL_DAYS))

    assert store.core_dir().is_dir()
    assert not store.core_file().exists()
    assert store.read_core_at(store.DATA_DIR) == expected


def test_backup_contains_core_topic_files_and_restores_round_trip(data_file, monkeypatch):
    monkeypatch.setattr(store, "BACKUP_MIN_GAP", 0)
    expected = _normalised_snapshot()
    backup = store.snapshot_now()

    with zipfile.ZipFile(backup) as archive:
        names = set(archive.namelist())
    assert any(name.startswith("core/") and name.endswith(".json") for name in names)
    assert "core.json" not in names

    data = store.load_data(store.ALL_DAYS)
    data["leaves"].append({"id": "LV-OTHER", "person_id": "OFF-002", "type": "طارئة"})
    store.save_data(data)
    store.restore_backup(backup.name)

    assert store.assemble() == expected


def test_core_files_are_replayed_from_an_incomplete_journal(data_file):
    data = store.load_data(store.ALL_DAYS)
    data["leaves"].append({"id": "LV-RECOVERED", "person_id": "OFF-001", "type": "أسبوعية"})
    core, _ = store.split(data)
    entry = store._load_entry(store.core_dir(), core=True, cache=False)[0]
    plan = store._plan_core_write(core, entry.parts)
    operations = [{"action": "replace", "target": path, "text": text}
                  for path, text in plan["files"].items()]
    operations += [{"action": "delete", "target": path} for path in plan["delete"]]
    store._write_journal(operations)

    assert store.recover_journal() is True
    assert not store._journal_path().exists()
    assert store.read_core_at(store.DATA_DIR) == core
    assert store.recover_journal() is False


def test_assemble_is_identical_before_and_after_core_migration(data_file):
    expected = _normalised_snapshot()
    core, _ = store.split(expected)
    shutil.rmtree(store.core_dir())
    store.core_file().write_text(json.dumps(core, ensure_ascii=False, indent=2), encoding="utf-8")
    store._cache.clear()

    assert store.assemble() == expected
    store.save_data(store.load_data(store.ALL_DAYS))
    assert not store.core_file().exists()
    assert store.assemble() == expected


def test_resync_all_picks_up_files_changed_outside_the_app(client, data_file):
    from backend import store
    store.with_data(lambda data: data["leaves"].append({"id": "x1", "person_id": "p", "start": "2026-01-01", "end": "2026-01-02"}) or None, [])
    report = store.resync_all()
    assert report["status"] == "ok" and report["error"] is None
    leaves = store.core_dir() / "leaves.json"
    text = leaves.read_text(encoding="utf-8").replace("x1", "x2")
    leaves.write_text(text, encoding="utf-8")
    store.resync_all()
    assert any(row["id"] == "x2" for row in store.with_data(lambda d: list(d["leaves"]), []))


def test_resync_all_reports_corrupt_data_instead_of_raising(client, data_file):
    from backend import store
    store.with_data(lambda data: None, [])
    (store.core_dir() / "leaves.json").write_text("{not json", encoding="utf-8")
    report = store.resync_all()
    assert report["status"] == "error" and report["error"]

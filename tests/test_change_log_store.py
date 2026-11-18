"""سجل التغييرات في ملفه (changes/log.jsonl): ترقية من core.json، إضافة فقط، نافذة الذاكرة،
تعافي بعد انقطاع، والنسخ الاحتياطي."""
import json

import pytest

from backend import changes, store


def _entry(n, **extra):
    return {"id": f"CHG-{n:03d}", "ts": "2026-01-01T00:00:00", "entity": "x", "entity_id": f"E-{n}",
            "action": "create", "day": None, "text": f"t{n}", "before": None, "after": {"n": n},
            "reason": "", "edited_by": None, **extra}


def _lines():
    path = store.change_log_path()
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def _core():
    return json.loads(store.core_file().read_text(encoding="utf-8"))


def _legacy(count, archive=0):
    """core.json بالشكل القديم (السجل جواه) + أرشيف تقليم قديم اختياري، من غير ملف السجل الجديد."""
    core = _core()
    core["change_log"] = [_entry(archive + i + 1) for i in range(count)]
    store.core_file().write_text(json.dumps(core, ensure_ascii=False, indent=2), encoding="utf-8")
    store.change_log_path().unlink(missing_ok=True)
    if archive:
        (store._LOG_DIR / "change_log_archive.jsonl").write_text(
            "".join(json.dumps(_entry(i + 1)) + "\n" for i in range(archive)), encoding="utf-8")
    store._cache.clear()


def test_first_write_after_upgrade_moves_the_log_out_of_core_with_the_old_archive(client):
    _legacy(5, archive=3)
    window = store.load_data(store.ALL_DAYS)["change_log"]
    assert [e["id"] for e in window] == [f"CHG-{n:03d}" for n in range(4, 9)]       # قبل الكتابة: من core

    store.with_data(lambda d: changes.record(d, "a", "A-1", "create", text="جديد"))

    assert "change_log" not in _core()
    ids = [e["id"] for e in _lines()]
    assert ids[:8] == [f"CHG-{n:03d}" for n in range(1, 9)] and len(ids) == 9       # الأرشيف + النافذة + الجديد
    assert len(set(ids)) == len(ids)                                                    # من غير تكرار
    assert store.load_data(store.ALL_DAYS)["change_log"][-1]["text"] == "جديد"


def test_later_writes_only_append_and_never_touch_core(client):
    store.with_data(lambda d: changes.record(d, "a", "A-1", "create"))
    core_before = store.core_file().read_bytes()
    log_before = store.change_log_path().read_bytes()

    for i in range(3):
        store.with_data(lambda d, i=i: changes.record(d, "a", f"A-{i + 2}", "update"))

    log_after = store.change_log_path().read_bytes()
    assert log_after.startswith(log_before)                       # اللي قبل كده ما اتلمسش
    assert len(_lines()) == len(log_before.splitlines()) + 3
    assert store.core_file().read_bytes() == core_before         # id_seq ما اتحرّكش → core ما اتكتبش


def test_change_ids_keep_increasing_without_the_core_counter(client):
    ids = []
    for _ in range(3):
        store.with_data(lambda d: ids.append(changes.record(d, "a", "A", "create")["id"]))
    numbers = [int(i.split("-")[1]) for i in ids]
    assert numbers == sorted(set(numbers)) and numbers[1] == numbers[0] + 1


def test_memory_window_is_the_tail_of_the_file(client, monkeypatch):
    monkeypatch.setattr(store, "CHANGE_WINDOW", 4)
    store.change_log_path().parent.mkdir(parents=True, exist_ok=True)
    store.change_log_path().write_text("".join(json.dumps(_entry(n)) + "\n" for n in range(1, 11)),
                                       encoding="utf-8")
    store._cache.clear()

    window = store.load_data(store.ALL_DAYS)["change_log"]

    assert [e["id"] for e in window] == ["CHG-007", "CHG-008", "CHG-009", "CHG-010"]


def test_interrupted_append_is_completed_exactly_once_from_the_journal(client, monkeypatch):
    store.with_data(lambda d: changes.record(d, "a", "A-1", "create"))
    before = len(_lines())
    real = store._append_log
    monkeypatch.setattr(store, "_append_log",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("انقطاع")))

    with pytest.raises(OSError):
        store.with_data(lambda d: changes.record(d, "a", "A-2", "create", text="هيتكمل"))

    monkeypatch.setattr(store, "_append_log", real)
    store._cache.clear()
    store.recover_journal()
    store.recover_journal()                                       # تكرار آمن (idempotent)

    assert len(_lines()) == before + 1 and _lines()[-1]["text"] == "هيتكمل"
    assert not store._journal_path().exists()


def test_partial_append_after_a_crash_is_repaired(client):
    store.with_data(lambda d: changes.record(d, "a", "A-1", "create"))
    path = store.change_log_path()
    offset = path.stat().st_size
    text = store._log_text([_entry(900, text="كامل")])
    with open(path, "ab") as fh:
        fh.write(text.encode("utf-8")[:20])                       # كتابة ناقصة

    store._append_log(path, text, offset)

    assert _lines()[-1]["id"] == "CHG-900" and _lines()[-1]["text"] == "كامل"


def test_diverged_log_refuses_a_blind_append(client):
    store.with_data(lambda d: changes.record(d, "a", "A-1", "create"))
    path = store.change_log_path()
    offset = path.stat().st_size
    with open(path, "ab") as fh:
        fh.write(b'{"id":"CHG-777"}\n')                           # حد تاني كتب بعد الإزاحة المتوقعة

    with pytest.raises(store.DataUnreadable):
        store._append_log(path, store._log_text([_entry(900)]), offset)


def test_backup_carries_the_full_history_and_restore_brings_it_back(client, monkeypatch):
    monkeypatch.setattr(store, "BACKUP_MIN_GAP", 0)
    for i in range(3):
        store.with_data(lambda d, i=i: changes.record(d, "a", f"A-{i}", "create"))
    full = store.change_log_path().read_bytes()
    backup = store.snapshot_now()
    assert "changes/log.jsonl" in __import__("zipfile").ZipFile(backup).namelist()

    store.with_data(lambda d: changes.record(d, "a", "بعد النسخة", "create"))
    assert store.change_log_path().read_bytes() != full

    store.restore_backup(backup.name)

    assert store.change_log_path().read_bytes() == full


def test_assemble_includes_the_window_so_tools_and_backups_stay_complete(client):
    store.with_data(lambda d: changes.record(d, "a", "A-1", "create", text="في التجميع"))
    assert store.assemble()["change_log"][-1]["text"] == "في التجميع"


def test_reads_do_not_unpack_the_log_and_writes_that_do_not_touch_it_skip_it(client):
    store.with_data(lambda d: changes.record(d, "a", "A-1", "create"))
    seen = {}

    def read_only(data):
        seen["view"] = data["change_log"]
        seen["len"] = len(data["change_log"])
        seen["untouched"] = data["change_log"].untouched
        return None

    store.with_data(read_only)

    assert seen["untouched"] and seen["len"] >= 1                     # العدّ من غير فك pickle
    assert seen["view"].untouched                                       # وبعد الحفظ برضه
    assert len(_lines()) == seen["len"]                                 # ومفيش سطر اتكتب


def test_change_log_view_behaves_like_a_list():
    import copy
    view = store.ChangeLogView.of([_entry(1), _entry(2)])

    view.append(_entry(3))
    del view[:1]
    clone = copy.deepcopy(view)
    clone.append(_entry(4))

    assert [e["id"] for e in view] == ["CHG-002", "CHG-003"] and len(clone) == 3
    assert list(reversed(view))[0]["id"] == "CHG-003" and bool(view)
    assert view == [_entry(2), _entry(3)] and json.dumps(view.to_list())


def test_new_backups_are_raw_files_and_old_single_json_backups_still_restore(client, tmp_path):
    import zipfile
    client.post("/api/assignments/2026-04-10", json={"name": "خدمة نسخة", "kind": "خارجية"})
    store.with_data(lambda d: changes.record(d, "a", "A-1", "create", text="قبل"))
    backup = store.snapshot_now()
    with zipfile.ZipFile(backup) as zf:
        names = zf.namelist()
    assert "manifest.json" in names and "core.json" in names and "data.json" not in names
    assert any(n.startswith("days/") for n in names) and "changes/log.jsonl" in names
    assert store.read_backup(backup) == store.assemble()                  # نفس الـdict القديم بالظبط

    # نسخة بالصيغة القديمة (data.json واحد) لازم تفضل تتقري وتتستعاد
    old = store.backup_dir() / "data-19990101-000000-000000.zip"
    with zipfile.ZipFile(old, "w") as zf:
        zf.writestr("data.json", store._dumps(store.assemble()))
    store.with_data(lambda d: changes.record(d, "a", "A-2", "create", text="بعد"))
    store.restore_backup(old.name)

    assert store.load_data(store.ALL_DAYS)["change_log"][-1]["text"] == "قبل"

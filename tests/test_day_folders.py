"""مجلد لكل يوم: ملف لكل جانب، ترقية من الملف الواحد في معاملة واحدة، وكتابة اللي اتغيّر بس."""
import json

import pytest

from backend import store

DAY = "2026-04-10"
OTHER = "2026-04-11"


def _add(client, day=DAY, name="خدمة"):
    return client.post(f"/api/assignments/{day}", json={"name": name, "kind": "خارجية"})


def _legacy(day, blob):
    """يحوّل يوم لملف واحد قديم من «برّه»."""
    store._remove_day(day)
    path = store.legacy_day_file(day)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")
    store._cache.clear()


def _mtimes(day):
    return {p.name: p.stat().st_mtime_ns for p in store.day_files(day)}


def test_a_legacy_day_file_migrates_to_a_folder_on_its_first_write(client):
    _legacy(DAY, {"assignments": [{"id": "AS-0001", "name": "قديم", "section": "الخدمات الطارئة"}],
                  "assignment_seq": 1, "confirm": {"at": "2026-04-10T10:00:00"}})
    assert store.legacy_day_file(DAY).exists() and not store.day_folder(DAY).exists()
    before = store.read_day_blob(DAY)

    client.put(f"/api/duty/{DAY}/OFF-001", json={"note": "تعديل"})      # أي كتابة على اليوم

    assert not store.legacy_day_file(DAY).exists() and store.day_folder(DAY).is_dir()
    after = store.read_day_blob(DAY)
    assert after["assignments"] == before["assignments"] and after["confirm"] == before["confirm"]
    assert set(p.name for p in store.day_files(DAY)) == {"assignments.json", "confirm.json", "officers.json"}


def test_only_the_changed_aspect_file_is_rewritten(client):
    _add(client)
    client.put(f"/api/duty/{DAY}/OFF-001", json={"taqseera": True})
    before = _mtimes(DAY)

    _add(client, name="خدمة تانية")
    after = _mtimes(DAY)

    assert after["assignments.json"] != before["assignments.json"]
    assert after["officers.json"] == before["officers.json"]            # حالات الضباط ما اتلمستش


def test_an_aspect_that_becomes_empty_loses_its_file_and_an_empty_day_loses_its_folder(client):
    r = _add(client)
    client.put(f"/api/duty/{DAY}/OFF-001", json={"taqseera": True})
    assert "officers.json" in _mtimes(DAY)

    client.put(f"/api/duty/{DAY}/OFF-001", json={"taqseera": False})
    assert "officers.json" not in _mtimes(DAY)

    client.delete(f"/api/assignments/{DAY}/{r.get_json()['id']}")
    assert not store.day_folder(DAY).exists() and not store.legacy_day_file(DAY).exists()


def test_crash_after_the_journal_but_before_the_files_is_finished_on_recovery(client, monkeypatch):
    _legacy(DAY, {"assignments": [{"id": "AS-0001", "name": "قديم", "section": "الخدمات الطارئة"}],
                  "assignment_seq": 1})
    original = store.read_day_blob(DAY)
    real = store._apply_day_plan
    monkeypatch.setattr(store, "_apply_day_plan",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("انقطاع كهربا")))

    with pytest.raises(OSError):
        client.put(f"/api/duty/{DAY}/OFF-001", json={"note": "هيتكمل"})

    monkeypatch.setattr(store, "_apply_day_plan", real)
    store._cache.clear()
    store.recover_journal()

    assert store.day_folder(DAY).is_dir() and not store.legacy_day_file(DAY).exists()
    blob = store.read_day_blob(DAY)
    assert blob["assignments"] == original["assignments"]
    assert blob["officer_states"]["OFF-001"]["note"] == "هيتكمل"


def test_mixed_layouts_read_the_same_and_assemble_is_identical_after_migrating_everything(client):
    _add(client, DAY)
    _add(client, OTHER, name="تانية")
    folder_view = store.assemble()
    for day in (DAY, OTHER):                       # رجّعهم للشكل القديم
        _legacy(day, store.read_day_blob(day))
    assert store.assemble() == folder_view          # القراءة بتفهم الشكلين بنفس النتيجة

    for day in (DAY, OTHER):                        # ترقية كلها
        blob = store.read_day_blob(day)
        plan = store._plan_day_write(day, blob, None)
        store._apply_day_plan(day, plan)
    store._cache.clear()

    assert store.assemble() == folder_view
    assert all(store.day_folder(d).is_dir() and not store.legacy_day_file(d).exists() for d in (DAY, OTHER))


def test_readers_for_other_data_dirs_understand_both_layouts(client):
    _add(client, DAY)
    _legacy(OTHER, {"assignments": [{"id": "AS-0001", "name": "قديم", "section": "الخدمات الطارئة"}]})

    assert store.read_day_dir(store.DATA_DIR, DAY)["assignments"]
    assert store.read_day_dir(store.DATA_DIR, OTHER)["assignments"][0]["name"] == "قديم"
    assert store.read_day_dir(store.DATA_DIR, "2030-01-01") is None
    assert {DAY, OTHER} <= set(store.day_blobs_at(store.DATA_DIR))


def test_backup_of_a_folder_day_restores_it(client, monkeypatch):
    import zipfile
    monkeypatch.setattr(store, "BACKUP_MIN_GAP", 0)
    _add(client, DAY, name="قبل")
    backup = store.snapshot_now()
    assert any(n.startswith(f"days/2026/04/{DAY}/") for n in zipfile.ZipFile(backup).namelist())
    assert store.read_backup(backup) == store.assemble()

    _add(client, DAY, name="بعد")
    store.restore_backup(backup.name)

    assert [a["name"] for a in store.read_day_blob(DAY)["assignments"]] == ["قبل"]


def test_writing_outside_the_scope_still_touches_nothing(client):
    _add(client, DAY)
    _add(client, OTHER)
    before = store.day_bytes(OTHER)

    def mutate(data):
        data["day_assignments"][OTHER] = []          # خارج النطاق
        return None

    with pytest.raises(store.OutOfScope):
        store.with_data(mutate, [DAY])

    assert store.day_bytes(OTHER) == before

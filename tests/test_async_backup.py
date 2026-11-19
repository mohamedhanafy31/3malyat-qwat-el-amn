"""النسخ التلقائية برّه قفل الطلبات (`store.BackupWorker`).

`_write` بياخد لقطة بايتات الحالة **قبل** التعديل تحت `LOCK` (قراءة بس)، والعامل
بيضغطها وينضّف برّه القفل. كل الاختبارات هنا بتتحكم في البناء بـ`threading.Event`
(مفيش sleep)، وكلها على مجلد مؤقت من `data_file`.
"""
import json
import os
import threading
import zipfile

import pytest

from backend import store


class _Gate:
    """بيلف `_write_archive` لخيط العامل بس: بيوقفه لحد `release`، وبيعدّ التداخل."""

    def __init__(self, real):
        self.real = real
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self.active = 0
        self.max_active = 0
        self.fail_next = 0
        self._lock = threading.Lock()

    def __call__(self, *args):
        if threading.current_thread().name != "store-backup":
            return self.real(*args)                 # snapshot_now المتزامنة بتعدّي زي ما هي
        with self._lock:
            self.calls += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            fail = self.fail_next > 0
            self.fail_next -= fail
        try:
            self.entered.set()
            if not self.release.wait(10):
                raise RuntimeError("gate was never released")
            if fail:
                raise OSError("disk full (test)")
            return self.real(*args)
        finally:
            with self._lock:
                self.active -= 1


@pytest.fixture
def worker(data_file, monkeypatch):
    monkeypatch.setattr(store, "BACKUP_MIN_GAP", 0)
    started = store.start_backup_worker()
    yield started
    assert store.stop_backup_worker(timeout=10)
    assert not started.is_alive()


@pytest.fixture
def gate(worker, monkeypatch):
    wrapped = _Gate(store._write_archive)
    monkeypatch.setattr(store, "_write_archive", wrapped)
    yield wrapped
    wrapped.release.set()                           # اختبار وقع في النص ما يعلّقش إيقاف العامل


def _add_leave(n):
    store.with_data(lambda data: data["leaves"].append(
        {"id": f"LV-9{n:02d}", "person_id": "OFF-002", "type": "أسبوعية",
         "start": "2026-03-01", "end": "2026-03-01", "return_date": "2026-03-02",
         "note": "", "source": "test"}))


def _leave_ids():
    return {leave["id"] for leave in store.load_data(())["leaves"]}


def test_mutation_returns_while_the_archive_build_is_blocked(gate, worker):
    _add_leave(1)
    assert gate.entered.wait(10), "العامل لازم يبدأ البناء"
    # الطلب رجع والبناء لسه واقف: التعديل على القرص، ومفيش أرشيف لسه
    assert "LV-901" in _leave_ids()
    assert store._backup_files() == []
    # وLOCK فاضي: كتابة تانية بتخلص والبناء لسه واقف
    _add_leave(2)
    assert "LV-902" in _leave_ids()
    assert worker.flush(timeout=0) is False

    gate.release.set()
    assert worker.flush(timeout=10)
    assert len(store._backup_files()) == 1
    assert worker.built == 1 and worker.failed == 0


def test_burst_triggers_coalesce_and_builds_never_overlap(gate, worker):
    _add_leave(1)
    assert gate.entered.wait(10)
    errors = []

    def write(n):
        try:
            _add_leave(n)
        except Exception as exc:          # pragma: no cover - بيظهر في assert تحت
            errors.append(exc)

    burst = [threading.Thread(target=write, args=(n,)) for n in range(2, 12)]
    for thread in burst:
        thread.start()
    for thread in burst:
        thread.join(10)
    assert errors == [] and not any(t.is_alive() for t in burst)
    assert _leave_ids() >= {f"LV-9{n:02d}" for n in range(1, 12)}
    assert gate.calls == 1, "الطلبات وقت البناء بتتدمج، مش بتتطابر"

    gate.release.set()
    assert worker.flush(timeout=10)
    assert gate.calls == 1 and len(store._backup_files()) == 1

    _add_leave(12)                            # العامل فاضي تاني -> يقبل طلب جديد
    assert worker.flush(timeout=10)
    assert gate.calls == 2 and gate.max_active == 1
    assert len(store._backup_files()) == 2


def test_failed_build_is_counted_and_a_later_trigger_still_backs_up(gate, worker):
    gate.fail_next = 1
    gate.release.set()
    _add_leave(1)
    assert worker.flush(timeout=10)
    assert worker.failed == 1 and worker.built == 0
    assert worker.is_alive()
    assert store._backup_files() == []
    assert not list(store.backup_dir().glob("*.part"))

    _add_leave(2)
    assert worker.flush(timeout=10)
    assert worker.built == 1
    assert len(store._backup_files()) == 1


def test_snapshot_now_stays_synchronous_while_the_worker_runs(gate, worker, data_file,
                                                               tmp_path, monkeypatch):
    expected = json.loads(data_file.read_text(encoding="utf-8"))
    path = store.snapshot_now()
    assert path is not None and path.exists()
    assert path in store._backup_files()
    assert gate.calls == 0, "snapshot_now ما بتعدّيش على العامل"
    assert store.read_backup(path) == expected

    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "empty")
    assert store.snapshot_now() is None


def test_async_archive_is_the_consistent_pre_mutation_state(client, gate, worker, data_file):
    before = json.loads(data_file.read_text(encoding="utf-8"))
    log_path = store.change_log_path()
    log_before = log_path.read_bytes() if log_path.exists() else None

    client.post("/api/assignments/2026-04-10", json={"name": "أولى", "kind": "خارجية"})
    assert gate.entered.wait(10)
    # معاملات بعد اللقطة ووقت البناء — ما ينفعش يظهر منها حاجة في الأرشيف
    client.post("/api/assignments/2026-04-10", json={"name": "تانية", "kind": "خارجية"})
    assert client.post("/api/leaves", json={"person_id": "OFF-002", "type": "إجازة طارئة",
                                            "start": "2026-02-01", "end": "2026-02-01"}).status_code == 201
    _add_leave(1)
    assert log_path.exists() and log_path.read_bytes() != log_before, "سجل التغييرات اتضاف له بعد اللقطة"

    gate.release.set()
    assert worker.flush(timeout=10)
    [archive] = store._backup_files()
    assert store.read_backup(archive) == before, "النسخة = الحالة قبل أول تعديل بالظبط"
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        assert not any(name.startswith("days/2026/04/2026-04-10") for name in names)
        if log_before is None:
            assert store.CHANGE_LOG_FILE not in names
        else:
            assert zf.read(store.CHANGE_LOG_FILE) == log_before

    store.restore_backup(archive.name)
    restored = store.assemble()
    assert restored.get("day_assignments", {}).get("2026-04-10", []) == \
        before.get("day_assignments", {}).get("2026-04-10", [])
    assert {leave["id"] for leave in restored["leaves"]} == \
        {leave["id"] for leave in before["leaves"]}
    assert [e.get("id") for e in restored["change_log"]] == \
        [e.get("id") for e in before["change_log"]]


def test_async_archive_freezes_upload_bytes_at_capture_time(gate, worker):
    uploads = store.DATA_DIR / "uploads" / "service_catalog"
    uploads.mkdir(parents=True)
    (uploads / "kept.bin").write_bytes(b"original")
    (uploads / "gone.bin").write_bytes(b"to-delete")

    _add_leave(1)
    assert gate.entered.wait(10)
    # بعد اللقطة ووقت البناء: صورة اتبدّلت وصورة اتمسحت وصورة جديدة اترفعت
    (uploads / "kept.bin").write_bytes(b"changed")
    (uploads / "gone.bin").unlink()
    (uploads / "new.bin").write_bytes(b"later")

    gate.release.set()
    assert worker.flush(timeout=10)
    [archive] = store._backup_files()
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        assert zf.read("uploads/service_catalog/kept.bin") == b"original"
        assert zf.read("uploads/service_catalog/gone.bin") == b"to-delete"
        assert "uploads/service_catalog/new.bin" not in names


def test_failed_build_removes_its_own_part_file_and_the_worker_recovers(gate, worker,
                                                                         monkeypatch):
    real_replace = store._replace
    seen_parts = []

    def failing_replace(src, dst):
        if str(src).endswith(".part") and not seen_parts:
            seen_parts.append(os.path.exists(src))
            raise OSError("replace failed (test)")
        return real_replace(src, dst)

    monkeypatch.setattr(store, "_replace", failing_replace)
    foreign = store.backup_dir() / "data-20000101-000000-000000.part"
    foreign.parent.mkdir(parents=True, exist_ok=True)
    foreign.write_bytes(b"another process")         # مش بتاعنا — لازم يفضل

    gate.release.set()
    _add_leave(1)
    assert worker.flush(timeout=10)
    assert seen_parts == [True], "الفشل حصل بعد ما ملف .part اتعمل"
    assert worker.failed == 1 and worker.is_alive()
    assert sorted(store.backup_dir().glob("*.part")) == [foreign]
    assert store._backup_files() == []

    _add_leave(2)
    assert worker.flush(timeout=10)
    assert worker.built == 1
    assert len(store._backup_files()) == 1
    assert sorted(store.backup_dir().glob("*.part")) == [foreign]


def test_timed_out_stop_never_lets_a_second_worker_start(data_file, monkeypatch):
    monkeypatch.setattr(store, "BACKUP_MIN_GAP", 0)
    gate = _Gate(store._write_archive)
    monkeypatch.setattr(store, "_write_archive", gate)
    first = store.start_backup_worker()
    try:
        _add_leave(1)
        assert gate.entered.wait(10)

        assert store.stop_backup_worker(timeout=0) is False, "الضغط لسه واقف"
        assert first.is_alive() and first.stopping()
        assert store.backup_worker() is first, "المرجع ما يضيعش قبل ما الخيط يخلص"
        assert store.start_backup_worker() is first, "مفيش بديل والقديم لسه شغّال"
        _add_leave(2)                         # وقت الإيقاف: مابيتقبلش ومابيتبنيش متزامن
        assert gate.calls == 1 and store._backup_files() == []

        gate.release.set()
        assert store.stop_backup_worker(timeout=10) is True
        assert not first.is_alive()
        assert store.backup_worker() is None
        assert first.built == 1 and len(store._backup_files()) == 1

        second = store.start_backup_worker()
        assert second is not first and second.is_alive() and not second.stopping()
        _add_leave(3)
        assert second.flush(timeout=10)
        assert second.built == 1 and gate.calls == 2 and gate.max_active == 1
        assert len(store._backup_files()) == 2
    finally:
        gate.release.set()
        assert store.stop_backup_worker(timeout=10)
    assert store.backup_worker() is None


def test_worker_start_and_stop_are_idempotent_and_stop_drains_pending(data_file, monkeypatch):
    monkeypatch.setattr(store, "BACKUP_MIN_GAP", 0)
    first = store.start_backup_worker()
    try:
        assert store.start_backup_worker() is first
        assert store.backup_worker() is first
        _add_leave(1)                          # لقطة منتظرة أو جارية
    finally:
        assert store.stop_backup_worker(timeout=10)
    assert not first.is_alive()
    assert first.built == 1, "الإيقاف بيخلّص اللقطة اللي اتقبلت"
    assert len(store._backup_files()) == 1
    assert store.stop_backup_worker() is True
    assert store.backup_worker() is None
    assert first.offer({"members": []}) is False

    # من غير عامل: النسخة التلقائية متزامنة زي الأول
    _add_leave(2)
    assert len(store._backup_files()) == 2

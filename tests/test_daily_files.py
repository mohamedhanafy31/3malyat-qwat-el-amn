import json
import time
from pathlib import Path

from backend import daily_files


def test_daily_names_and_archive_patterns():
    names = daily_files.file_names("2026-09-28")
    assert names["board"] == "28.docx"
    assert names["afraad"] == "28-9-2026 افراد.docx"
    for value in ("28.docx", "28.pdf", "28-9-2026.docx",
                  "28-9-2026 افراد.pdf", "يومية الحملة عن يوم 28-9-2026.pdf",
                  "اعداد الخدمات يوم 27-9-2026.xlsx"):
        assert daily_files.is_daily_file(value)
    for value in ("28..docx", "~$-2026.docx", "خط تشكيل صبح.docx", "ارقام الافراد.docx",
                  "داتا افراد.docx", "أمر خدمة يوم 28-9-2026.docx"):
        assert not daily_files.is_daily_file(value)


def test_clone_gap_and_write(monkeypatch, tmp_path):
    root = tmp_path / "archive"; monkeypatch.setenv("DAILY_FILES_ROOT", str(root))
    source = root / "2026" / "9" / "28"; (source / "اضافات").mkdir(parents=True)
    (source / "اضافات" / "keep.txt").write_text("ok")
    (source / "28.docx").write_text("old"); (source / "~$x.docx").write_text("tmp")
    from backend import day_exports
    for kind in daily_files.KINDS:
        monkeypatch.setattr(day_exports, f"build_{kind}_bytes", lambda day, kind=kind: kind.encode())
    folder, cloned, warnings = daily_files.ensure_day_folder("2026-09-30")
    assert cloned == source and not warnings and (folder / "اضافات" / "keep.txt").exists()
    result = daily_files.write_day_files("2026-09-30")
    assert all(result.files[k]["ok"] for k in daily_files.KINDS)
    assert set(daily_files.file_names("2026-09-30").values()) <= {
        p.name for p in folder.iterdir()
    }


def test_clone_excludes_real_archive_names_at_all_levels(monkeypatch, tmp_path):
    root = tmp_path / "archive"
    monkeypatch.setenv("DAILY_FILES_ROOT", str(root))
    source = root / "2026" / "9" / "28"
    (source / "اضافات").mkdir(parents=True)
    names = [
        "28.docx", "28.pdf", "28-9-2026.docx", "28-9-2026 افراد.pdf",
        "يومية الحملة عن يوم 28-9-2026.pdf",
        "اعداد الخدمات يوم 27-9-2026.xlsx", "~$-2026.docx",
        "خط تشكيل صبح.docx", "ارقام الافراد.docx", "داتا افراد.docx",
        "أمر خدمة يوم 28-9-2026.docx", "28..docx",
    ]
    for name in names:
        (source / name).write_text(name)
    (source / "اضافات" / "28.docx").write_text("nested daily-looking file")
    (source / "اضافات" / "~$locked.docx").write_text("temp")
    (source / "اضافات" / "keep.tmp").write_text("temp")

    target, cloned, warnings = daily_files.ensure_day_folder("2026-09-30")

    assert cloned == source
    assert not warnings
    assert (target / "28..docx").exists()
    assert (target / "خط تشكيل صبح.docx").exists()
    assert (target / "اضافات" / "28.docx").exists()
    for name in names:
        if daily_files.is_daily_file(name) or name.startswith("~$"):
            assert not (target / name).exists()
    assert not (target / "اضافات" / "~$locked.docx").exists()
    assert not (target / "اضافات" / "keep.tmp").exists()


def test_clone_without_earlier_folder_is_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("DAILY_FILES_ROOT", str(tmp_path / "archive"))
    target, cloned, warnings = daily_files.ensure_day_folder("2020-01-01")
    assert target.is_dir() and cloned is None and warnings == []
    assert list(target.iterdir()) == []


def test_write_manifest_stale_names_pdf_and_retry(monkeypatch, tmp_path):
    root = tmp_path / "archive"
    monkeypatch.setenv("DAILY_FILES_ROOT", str(root))
    from backend import day_exports, store

    day = "2026-09-30"
    source = root / "2026" / "9" / "29"
    source.mkdir(parents=True)
    (source / "اعداد الخدمات يوم 29-9-2026.xlsx").write_bytes(b"stale")
    for kind in daily_files.KINDS:
        monkeypatch.setattr(day_exports, f"build_{kind}_bytes", lambda _day, k=kind: k.encode())

    target, _, _ = daily_files.ensure_day_folder(day)
    (target / "اعداد الخدمات يوم 28-9-2026.pdf").write_bytes(b"pdf")

    original_replace = daily_files.os.replace
    calls = {"count": 0}

    def flaky_replace(source_path, target_path):
        if Path(target_path).name == daily_files.file_names(day)["board"]:
            calls["count"] += 1
            if calls["count"] < 3:
                raise PermissionError("locked")
        return original_replace(source_path, target_path)

    monkeypatch.setattr(daily_files.os, "replace", flaky_replace)
    monkeypatch.setattr(daily_files.time, "sleep", lambda _seconds: None)
    result = daily_files.write_day_files(day)
    folder = daily_files.day_folder(day)
    manifest = json.loads((root / ".manifest.json").read_text(encoding="utf-8"))

    assert result.files["board"]["ok"] is True
    assert calls["count"] == 3
    assert not list(folder.glob(".*.tmp"))
    assert not (folder / "اعداد الخدمات يوم 29-9-2026.xlsx").exists()
    assert (folder / "اعداد الخدمات يوم 28-9-2026.pdf").exists()
    assert manifest[day]["sig"] is not None
    assert manifest[day]["at"]


def test_permission_failure_is_reported_and_temp_removed(monkeypatch, tmp_path):
    monkeypatch.setenv("DAILY_FILES_ROOT", str(tmp_path / "archive"))
    from backend import day_exports

    monkeypatch.setattr(day_exports, "build_board_bytes", lambda _day: b"board")
    monkeypatch.setattr(daily_files.os, "replace", lambda *_args: (_ for _ in ()).throw(PermissionError("locked")))
    monkeypatch.setattr(daily_files.time, "sleep", lambda _seconds: None)
    result = daily_files.write_day_files("2026-09-30", kinds=["board"])
    assert result.files["board"]["ok"] is False
    assert not list(Path(result.folder).glob(".*.tmp"))


def test_worker_debounce_and_flush_waits_for_inflight(monkeypatch):
    calls = []

    def write(day, kinds=None, **kwargs):
        calls.append(day)
        assert kwargs == {"require_data": True}
        time.sleep(0.03)

    monkeypatch.setattr(daily_files, "write_day_files", write)
    worker = daily_files.DailyFilesWorker(debounce=0.03)
    worker.enqueue(["2026-09-30"])
    time.sleep(0.02)
    worker.enqueue(["2026-10-01"])
    assert worker.flush(timeout=2)
    worker.stop()
    assert calls == ["2026-09-30", "2026-10-01"]


def test_start_worker_catchup_uses_manifest_signatures(monkeypatch, tmp_path):
    root = tmp_path / "archive"
    monkeypatch.setenv("DAILY_FILES_ROOT", str(root))
    monkeypatch.setattr(daily_files, "managed_from", lambda: "2026-09-30")
    monkeypatch.setattr(daily_files, "enabled", lambda: True)

    class Index:
        def days(self):
            return ["2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02"]

        def signature(self, day):
            return {"2026-09-29": (1, 1), "2026-09-30": (2, 2),
                    "2026-10-01": (3, 3), "2026-10-02": (4, 4)}[day]

    monkeypatch.setattr(daily_files.store, "day_index", lambda: Index())
    root.mkdir(parents=True)
    (root / ".manifest.json").write_text(json.dumps({
        "2026-09-29": {"sig": [0, 0]},
        "2026-09-30": {"sig": [2, 2]},
        "2026-10-01": {"sig": [0, 0]},
        "2026-10-02": {"sig": [4, 4]},
        "2026-10-03": {"sig": [9, 9]},
    }), encoding="utf-8")
    monkeypatch.setattr(daily_files, "_worker", None)
    worker = daily_files.start_worker()
    pending = worker.pending()
    today = {daily_files.date.today().isoformat(),
             (daily_files.date.today() + daily_files.timedelta(days=1)).isoformat()}
    assert "2026-10-01" in pending
    assert "2026-09-29" not in pending
    assert "2026-10-02" not in pending
    assert "2026-10-03" in pending
    assert today <= pending
    worker.stop()
    daily_files._worker = None
    daily_files.store.clear_after_commit_hooks()


def _stub_builders(monkeypatch):
    from backend import day_exports
    for kind in daily_files.KINDS:
        monkeypatch.setattr(day_exports, f"build_{kind}_bytes",
                            lambda day, kind=kind: kind.encode())


def test_day_without_data_gets_folder_clone_but_no_dailies(monkeypatch, tmp_path):
    root = tmp_path / "archive"
    monkeypatch.setenv("DAILY_FILES_ROOT", str(root))
    source = root / "2026" / "10" / "1"
    (source / "اضافات").mkdir(parents=True)
    (source / "اضافات" / "keep.txt").write_text("ok")
    (source / "1.docx").write_text("old daily")
    _stub_builders(monkeypatch)
    monkeypatch.setattr(daily_files, "has_data", lambda day: False)

    result = daily_files.write_day_files("2026-10-02", require_data=True)

    folder = daily_files.day_folder("2026-10-02")
    assert result.skipped == "no_data" and result.files == {}
    assert (folder / "اضافات" / "keep.txt").exists()
    assert not any(daily_files.is_daily_file(path.name) for path in folder.iterdir())
    assert "2026-10-02" not in daily_files._manifest()


def test_explicit_refresh_generates_even_without_data(monkeypatch, tmp_path):
    monkeypatch.setenv("DAILY_FILES_ROOT", str(tmp_path / "archive"))
    _stub_builders(monkeypatch)
    monkeypatch.setattr(daily_files, "has_data", lambda day: False)

    result = daily_files.write_day_files("2026-10-02")

    assert result.skipped == "" and all(row["ok"] for row in result.files.values())


def test_day_with_data_is_generated_when_data_required(monkeypatch, tmp_path):
    monkeypatch.setenv("DAILY_FILES_ROOT", str(tmp_path / "archive"))
    _stub_builders(monkeypatch)
    monkeypatch.setattr(daily_files, "has_data", lambda day: True)

    result = daily_files.write_day_files("2026-10-02", require_data=True)

    assert all(row["ok"] for row in result.files.values())


def test_has_data_ignores_auto_seeded_only_days(monkeypatch):
    class Index:
        def __init__(self, sections):
            self.sections = sections

        def has(self, day, key):
            return key in self.sections

    monkeypatch.setattr(daily_files.store, "day_index",
                        lambda: Index({"weekly_rest_seeded_days", "target_defaults"}))
    assert daily_files.has_data("2026-10-02") is False
    monkeypatch.setattr(daily_files.store, "day_index",
                        lambda: Index({"day_officers"}))
    assert daily_files.has_data("2026-10-02") is True


def test_sync_day_folder_fills_missing_without_overwriting(monkeypatch, tmp_path):
    root = tmp_path / "archive"
    monkeypatch.setenv("DAILY_FILES_ROOT", str(root))
    previous = root / "2026" / "9" / "29"
    (previous / "اضافات").mkdir(parents=True)
    (previous / "اضافات" / "a.txt").write_text("from previous")
    (previous / "امر.docx").write_text("from previous")
    (previous / "29.docx").write_text("daily")
    target = root / "2026" / "9" / "30"
    target.mkdir(parents=True)
    (target / "امر.docx").write_text("kept as is")

    folder, source, copied, warnings = daily_files.sync_day_folder("2026-09-30")

    assert source == previous and copied == 1 and not warnings
    assert (folder / "اضافات" / "a.txt").read_text() == "from previous"
    assert (folder / "امر.docx").read_text() == "kept as is"
    assert not (folder / "29.docx").exists()


def test_request_refresh_enqueues_only_when_running(monkeypatch):
    monkeypatch.setattr(daily_files, "_worker", None)
    assert daily_files.request_refresh(["2026-10-02"]) is False

    queued = []

    class Fake:
        def enqueue(self, days):
            queued.extend(days)

    monkeypatch.setattr(daily_files, "_worker", Fake())
    monkeypatch.setattr(daily_files, "enabled", lambda: True)
    assert daily_files.request_refresh(["2026-10-02"]) is True and queued == ["2026-10-02"]

from backend import daily_files


def _fake_builders(monkeypatch):
    from backend import day_exports
    for kind in daily_files.KINDS:
        monkeypatch.setattr(day_exports, f"build_{kind}_bytes",
                            lambda day, _k=kind: f"{_k}:{day}".encode(), raising=False)
    monkeypatch.setattr(day_exports, "special_groups", lambda day: [], raising=False)


def test_single_kind_refresh_writes_only_that_file(client, monkeypatch, tmp_path):
    monkeypatch.setenv("DAILY_FILES_ROOT", str(tmp_path / "archive"))
    _fake_builders(monkeypatch)
    response = client.post("/api/day-files/2026-09-30/duty", json={})
    assert response.status_code == 200
    body = response.get_json()
    assert body["kind"] == "duty" and body["result"]["ok"] is True
    folder = daily_files.day_folder("2026-09-30")
    name = daily_files.file_names("2026-09-30")["duty"]
    assert {p.name for p in folder.iterdir()} == {name}
    assert (folder / name).read_bytes() == b"duty:2026-09-30"


def test_single_kind_refresh_keeps_day_signature_stale(client, monkeypatch, tmp_path):
    monkeypatch.setenv("DAILY_FILES_ROOT", str(tmp_path / "archive"))
    _fake_builders(monkeypatch)
    client.post("/api/day-files/2026-09-30/board", json={})
    assert daily_files._manifest()["2026-09-30"]["sig"] is None


def test_single_kind_unknown_bad_day_and_disabled(client, monkeypatch, tmp_path):
    monkeypatch.setenv("DAILY_FILES_ROOT", str(tmp_path / "archive"))
    _fake_builders(monkeypatch)
    assert client.post("/api/day-files/2026-09-30/nope", json={}).status_code == 404
    assert client.post("/api/day-files/bad/duty", json={}).status_code == 400
    monkeypatch.setenv("DAILY_FILES_ENABLED", "false")
    assert client.post("/api/day-files/2026-09-30/duty", json={}).status_code == 409
    assert not (tmp_path / "archive" / "2026").exists()


def test_single_kind_refresh_leaves_operator_files_alone(client, monkeypatch, tmp_path):
    monkeypatch.setenv("DAILY_FILES_ROOT", str(tmp_path / "archive"))
    _fake_builders(monkeypatch)
    folder = daily_files.day_folder("2026-09-30")
    folder.mkdir(parents=True)
    mine = {"خط تشكيل صبح محدث.docx": b"op", "ملاحظات.docx": b"op2",
            "خط تشكيل ليل.docx": b"night-old"}
    for name, data in mine.items():
        (folder / name).write_bytes(data)
    assert client.post("/api/day-files/2026-09-30/formation_morning", json={}).status_code == 200
    for name, data in mine.items():
        assert (folder / name).read_bytes() == data
    assert (folder / "خط تشكيل صبح.docx").exists()


def test_pages_carry_per_daily_refresh_hooks(client):
    for path, kind in {"/duty": "duty", "/board": "board,service_order", "/afraad": "afraad",
                       "/counts": "counts", "/campaign": "campaign"}.items():
        assert f'data-daily-files="{kind}"'.encode() in client.get(path).data
    assert b"regularity,formation_morning,formation_night" in client.get("/").data
    assert b"btnRefreshFiles" in client.get("/board").data

"""طباعة اليوميات: المجموعات، حالة الملفات، الطابور، ومنع الطباعة من بره."""
from pathlib import Path

import pytest

from backend import daily_files, daily_print, store
from backend import print_collections as lib

DAY = "2026-11-04"


class FakeSession:
    printed = []
    fail_on = ()

    def __enter__(self):
        return self

    def print_file(self, path):
        if path.name in FakeSession.fail_on:
            raise RuntimeError("printer offline")
        FakeSession.printed.append(path.name)

    def __exit__(self, *_exc):
        return None


@pytest.fixture
def printer(data_file, tmp_path, monkeypatch):
    monkeypatch.setenv("DAILY_FILES_ROOT", str(tmp_path / "archive"))
    monkeypatch.setenv("DAILY_PRINT_ENGINE", "fake")
    monkeypatch.setattr(daily_print, "open_session", FakeSession)
    FakeSession.printed, FakeSession.fail_on = [], ()
    daily_print.QUEUE.clear()
    folder = daily_files.day_folder(DAY)
    folder.mkdir(parents=True)
    for kind in lib.PRINT_KINDS:
        (folder / daily_files.document_name(DAY, kind)).write_bytes(kind.encode())
    yield folder
    assert daily_print.QUEUE.wait_idle()
    daily_print.QUEUE.clear()


def _status(client, cid=None):
    body = client.get(f"/api/daily-print/{DAY}").get_json()
    if cid is None:
        return body
    return next(c for c in body["collections"] if c["id"] == cid)["status"]


def _print(client, ids, **extra):
    return client.post("/api/daily-print/jobs", json={"day": DAY, "collection_ids": ids, **extra})


def test_defaults_match_the_requested_sets(client):
    rows = {c["label"]: c["kinds"] for c in _status_for_defaults(client)}
    assert rows == {
        "احمد بيه سمير": ["board"],
        "محمد بيه فؤاد": ["board", "regularity", "duty", "afraad"],
        "محمد بيه نعامة": ["regularity", "duty", "afraad", "campaign"],
        "حمدي بيه النجار": ["regularity", "duty", "afraad"],
        "ضابط عظيم": ["board", "regularity", "duty", "afraad"],
        "امر الخدمة": ["service_order", "regularity", "duty", "afraad"],
        "الحكمدار": ["board", "regularity", "duty", "afraad"],
    }


def _status_for_defaults(client):
    return client.get(f"/api/daily-print/{DAY}").get_json()["collections"]


def test_deleted_collections_never_come_back(client):
    for row in _status_for_defaults(client):
        assert client.delete(f"/api/print-collections/{row['id']}").status_code == 200
    assert _status_for_defaults(client) == []
    assert store.load_data(())["print_collections"] == []


def test_custom_collection_keeps_print_order_and_validates(client):
    made = client.post("/api/print-collections",
                       json={"label": " مكتب   المدير ", "kinds": ["duty", "service_order"]})
    assert made.status_code == 201
    assert made.get_json()["label"] == "مكتب المدير"
    assert made.get_json()["kinds"] == ["service_order", "duty"]
    assert client.post("/api/print-collections",
                       json={"label": "مكتب المدير", "kinds": ["duty"]}).status_code == 400
    assert client.post("/api/print-collections", json={"label": "س", "kinds": []}).status_code == 400
    assert client.post("/api/print-collections",
                       json={"label": "س", "kinds": ["../../x"]}).status_code == 400
    cid = made.get_json()["id"]
    edited = client.patch(f"/api/print-collections/{cid}", json={"label": "س", "kinds": ["board"]})
    assert edited.get_json()["kinds"] == ["board"]
    assert client.patch("/api/print-collections/nope",
                        json={"label": "ص", "kinds": ["board"]}).status_code == 404


def test_every_role_can_edit_collections_and_print(printer, individual_client):
    assert individual_client.post("/api/print-collections",
                                  json={"label": "جهة", "kinds": ["duty"]}).status_code == 201
    assert _print(individual_client, ["pc-ahmed-samir"]).status_code == 202


def test_printing_is_blocked_from_the_phone_but_editing_is_not(printer, client):
    headers = {"X-Forwarded-For": "100.64.0.5"}
    refused = client.post("/api/daily-print/jobs", headers=headers,
                          json={"day": DAY, "collection_ids": ["pc-ahmed-samir"]})
    assert refused.status_code == 403
    assert FakeSession.printed == []
    body = client.get(f"/api/daily-print/{DAY}", headers=headers).get_json()
    assert body["can_print"] is False and "جهاز المكتب" in body["block_reason"]
    assert client.post("/api/print-collections", headers=headers,
                       json={"label": "جهة", "kinds": ["duty"]}).status_code == 201


def test_copies_repeat_the_whole_set_in_order(printer, client):
    assert _print(client, ["pc-hamdy-elnaggar"], copies=2).status_code == 202
    assert daily_print.QUEUE.wait_idle()
    names = daily_files.file_names(DAY)
    one_set = [names["regularity"], names["duty"], names["afraad"]]
    assert FakeSession.printed == one_set * 2


def test_status_goes_from_idle_to_done_then_the_mark_disappears(printer, client, monkeypatch):
    cid = "pc-ahmed-samir"
    assert _status(client, cid)["state"] == "idle"
    monkeypatch.setattr(daily_print, "DONE_VISIBLE_SECONDS", 60)
    _print(client, [cid])
    assert daily_print.QUEUE.wait_idle()
    done = _status(client, cid)
    assert done["state"] == "done" and done["docs"] == {"board": "done"}
    monkeypatch.setattr(daily_print, "DONE_VISIBLE_SECONDS", -1)
    faded = _status(client, cid)
    assert faded["state"] == "printed" and faded["docs"] == {"board": "printed"}


def test_queued_and_printing_states_and_double_click(printer, client, monkeypatch):
    import threading
    release, entered = threading.Event(), threading.Event()

    class Slow(FakeSession):
        def print_file(self, path):
            entered.set()
            assert release.wait(5)

    monkeypatch.setattr(daily_print, "open_session", Slow)
    _print(client, ["pc-ahmed-samir"])
    assert entered.wait(5)
    _print(client, ["pc-mohamed-fouad"])
    assert _status(client, "pc-ahmed-samir")["state"] == "printing"
    assert _status(client, "pc-mohamed-fouad")["state"] == "queued"
    again = _print(client, ["pc-mohamed-fouad"])
    assert again.status_code == 409 and again.get_json()["code"] == "nothing_to_print"
    release.set()
    assert daily_print.QUEUE.wait_idle()


def test_one_failure_does_not_stop_the_rest_and_stays_visible(printer, client, monkeypatch):
    names = daily_files.file_names(DAY)
    FakeSession.fail_on = (names["regularity"],)
    monkeypatch.setattr(daily_print, "DONE_VISIBLE_SECONDS", -1)
    _print(client, ["pc-hamdy-elnaggar"])
    assert daily_print.QUEUE.wait_idle()
    assert FakeSession.printed == [names["duty"], names["afraad"]]
    status = _status(client, "pc-hamdy-elnaggar")
    assert status["state"] == "failed" and status["docs"]["regularity"] == "failed"
    assert "printer offline" in status["errors"][0]


def test_missing_file_on_an_empty_day_fails_with_a_clear_message(printer, client):
    (printer / daily_files.document_name(DAY, "board")).unlink()
    _print(client, ["pc-ahmed-samir"])
    assert daily_print.QUEUE.wait_idle()
    status = _status(client, "pc-ahmed-samir")
    assert status["state"] == "failed" and "غير موجود" in status["errors"][0]


def _write_manifest(entry):
    daily_files._write_manifest({DAY: entry})


def test_manual_edit_is_detected_from_the_written_hash(printer, client):
    board = printer / daily_files.document_name(DAY, "board")
    _write_manifest({"shas": {"board": daily_files._sha(board.read_bytes())}})
    assert daily_files.document_state(DAY, "board")["state"] == "ready"
    board.write_bytes(b"edited")
    assert daily_files.document_state(DAY, "board")["state"] == "edited"
    assert daily_files.document_state(DAY, "duty")["state"] == "ready"      # من غير بصمة


def test_unedited_service_order_needs_explicit_approval(printer, client):
    path = printer / daily_files.service_order_name(DAY)
    _write_manifest({"service_order": daily_files._sha(path.read_bytes())})
    assert daily_files.document_state(DAY, "service_order")["state"] == "draft"
    cid = "pc-service-order"
    out = _print(client, [cid])
    assert out.get_json()["skipped_draft"] is True
    assert daily_print.QUEUE.wait_idle()
    assert path.name not in FakeSession.printed
    assert _print(client, [cid], include_draft=True).get_json()["skipped_draft"] is False
    assert daily_print.QUEUE.wait_idle()
    assert FakeSession.printed.count(path.name) == 1
    path.write_bytes(b"operator edit")
    assert daily_files.document_state(DAY, "service_order")["state"] == "ready"


def test_write_day_files_records_a_hash_per_kind(printer, client, monkeypatch):
    from backend import day_exports
    monkeypatch.setattr(day_exports, "build_duty_bytes", lambda day: b"generated")
    daily_files.write_day_files(DAY, ["duty"])
    shas = daily_files._manifest()[DAY]["shas"]
    assert shas["duty"] == daily_files._sha(b"generated")


def test_paths_come_from_the_server_only(printer):
    with pytest.raises(ValueError):
        daily_print.document_path(DAY, "../../secrets")
    path = daily_print.document_path(DAY, "afraad")
    assert path.parent == Path(printer).resolve()


def test_bad_requests(printer, client):
    assert client.post("/api/daily-print/jobs", json={"day": "x", "collection_ids": ["a"]}).status_code == 400
    assert _print(client, []).status_code == 400
    assert _print(client, ["nope"]).status_code == 404
    assert _print(client, ["pc-ahmed-samir"], copies=0).status_code == 400
    assert _print(client, ["pc-ahmed-samir"], copies=True).status_code == 400


def test_page_is_in_the_today_section(client):
    html = client.get("/daily-print").get_data(as_text=True)
    assert 'data-page="daily_print"' in html
    assert client.get("/api/bootstrap/daily_print").get_json()["meta"]["today"]


def test_saving_collections_does_not_regenerate_files(client, monkeypatch):
    queued = []

    class Worker:
        def enqueue(self, days):
            queued.extend(days)

    monkeypatch.setattr(daily_files, "_worker", Worker())
    monkeypatch.setattr(daily_files, "enabled", lambda: True)
    store.register_after_commit(daily_files._hook)
    try:
        client.post("/api/print-collections", json={"label": "جهة", "kinds": ["duty"]})
    finally:
        store.clear_after_commit_hooks()
    assert queued == []


def test_word_session_prints_read_only_and_always_quits(monkeypatch, tmp_path):
    import sys
    import types
    calls = []

    class Doc:
        def PrintOut(self, **kw):
            calls.append(("print", kw))
            raise RuntimeError("offline")

        def Close(self, save):
            calls.append(("close", save))

    class Docs:
        def Open(self, path, **kw):
            calls.append(("open", path, kw))
            return Doc()

    class App:
        Documents = Docs()

        def Quit(self):
            calls.append(("quit",))

    pythoncom = types.SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: calls.append(("uninit",)))
    client_mod = types.SimpleNamespace(DispatchEx=lambda name: App())
    monkeypatch.setitem(sys.modules, "pythoncom", pythoncom)
    monkeypatch.setitem(sys.modules, "win32com", types.SimpleNamespace(client=client_mod))
    monkeypatch.setitem(sys.modules, "win32com.client", client_mod)
    path = tmp_path / "يومية 4-11-2026 افراد.docx"
    with pytest.raises(RuntimeError):
        with daily_print._WordSession() as session:
            assert session.app.Visible is False and session.app.DisplayAlerts == 0
            session.print_file(path)
    assert calls[0][1] == str(path) and calls[0][2]["ReadOnly"] is True
    assert calls[1] == ("print", {"Background": False, "Copies": 1})
    assert calls[2:] == [("close", 0), ("quit",), ("uninit",)]

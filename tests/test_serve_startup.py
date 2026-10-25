import importlib.util
import logging
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_serve(monkeypatch):
    waitress = types.ModuleType("waitress")
    waitress.serve = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "waitress", waitress)
    spec = importlib.util.spec_from_file_location("serve_under_test", ROOT / "serve.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_configure_logging",
                        lambda: logging.getLogger("serve-startup-test"))
    return module


def test_server_startup_locks_data_before_worker_and_bind(monkeypatch):
    module = load_serve(monkeypatch)
    events = []
    monkeypatch.setattr(module.store, "acquire_process_lock", lambda: events.append("lock"))
    monkeypatch.setattr(module, "start_worker", lambda: events.append("worker"))
    monkeypatch.setattr(module, "serve", lambda *args, **kwargs: events.append("bind"))

    assert module.main() == 0
    assert events == ["lock", "worker", "bind"]


def test_server_startup_records_lock_refusal_before_binding(monkeypatch):
    module = load_serve(monkeypatch)
    events = []

    def refuse_lock():
        raise SystemExit("already running")

    monkeypatch.setattr(module.store, "acquire_process_lock", refuse_lock)
    monkeypatch.setattr(module, "start_worker", lambda: events.append("worker"))
    monkeypatch.setattr(module, "serve", lambda *args, **kwargs: events.append("bind"))

    assert module.main() == 1
    assert events == []

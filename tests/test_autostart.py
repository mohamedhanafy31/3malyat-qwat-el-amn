import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def supervisor(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("autostart_under_test", ROOT / "tools" / "autostart.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(mod, "STOP_FILE", tmp_path / "logs" / "autostart.stop")
    monkeypatch.setattr(mod, "LOCK_FILE", tmp_path / "logs" / "autostart.lock")
    monkeypatch.setattr(mod, "MIN_DELAY", 0)
    return mod


def _fake_server(tmp_path, stop_on_run):
    """serve.py وهمي بيقع فورًا، وفي التشغيلة رقم stop_on_run بيطلب الإيقاف."""
    (tmp_path / "serve.py").write_text(
        "from pathlib import Path\n"
        "runs = Path('runs.txt')\n"
        "n = int(runs.read_text() or 0) + 1 if runs.exists() else 1\n"
        "runs.write_text(str(n))\n"
        f"if n >= {stop_on_run}:\n"
        "    Path('logs/autostart.stop').write_text('stop')\n"
        "raise SystemExit(1)\n", encoding="utf-8")


def test_restarts_crashed_server_until_stop_requested(supervisor, tmp_path):
    _fake_server(tmp_path, stop_on_run=3)
    assert supervisor.main() == 0
    assert (tmp_path / "runs.txt").read_text() == "3"
    assert not supervisor.STOP_FILE.exists()
    log = (tmp_path / "logs" / "autostart.log").read_text(encoding="utf-8")
    assert log.count("restarting") == 2 and "Stop requested" in log


def test_stale_stop_file_from_last_session_is_ignored(supervisor, tmp_path):
    (tmp_path / "logs").mkdir()
    supervisor.STOP_FILE.write_text("stop")
    _fake_server(tmp_path, stop_on_run=1)
    assert supervisor.main() == 0
    assert (tmp_path / "runs.txt").read_text() == "1"


def test_second_supervisor_exits_without_starting_server(supervisor, tmp_path):
    (tmp_path / "logs").mkdir()
    held = supervisor._single_instance()
    try:
        _fake_server(tmp_path, stop_on_run=1)
        assert supervisor.main() == 0
        assert not (tmp_path / "runs.txt").exists()
    finally:
        held.close()

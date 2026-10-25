from argparse import Namespace
import json
import socket
import urllib.error

from tools import deploy_check


def test_classify_readiness_requires_exact_service_marker():
    ready = json.dumps({"service": "personnel-system", "status": "ready", "schema": 6}).encode()
    assert deploy_check.classify_response(200, ready) == deploy_check.READY
    assert deploy_check.classify_response(200, b"<html>login</html>") == deploy_check.FOREIGN
    assert deploy_check.classify_response(200, b'{"service":"other","status":"ready","schema":6}') == deploy_check.FOREIGN
    assert deploy_check.classify_response(503, b'{"service":"personnel-system","status":"unavailable"}') == deploy_check.UNAVAILABLE


def test_host_python_contract_rejects_store_alias_and_wrong_wheel_abi():
    assert deploy_check.host_python_problem((3, 11, 9), False)
    assert deploy_check.host_python_problem((3, 10, 9), True, 64, "cp311")
    assert deploy_check.host_python_problem((3, 11, 9), True, 32, "cp311")
    assert deploy_check.host_python_problem((3, 11, 9), True, 64, "cp311") is None


def test_platform_and_port_contract():
    assert deploy_check.platform_problem("Windows", "AMD64", "10.0") is None
    assert deploy_check.platform_problem("Windows", "x86", "10.0")
    assert deploy_check.platform_problem("Linux", "x86_64")
    assert deploy_check.parse_port("5050") == 5050
    for invalid in ("0", "65536", "abc"):
        try:
            deploy_check.parse_port(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted invalid port {invalid}")


def test_windows_connection_refused_is_not_misclassified_as_foreign():
    refused = OSError(10061, "Windows connection refused")
    assert deploy_check.classify_transport_error(refused) == deploy_check.NOT_LISTENING
    wrapped = urllib.error.URLError(refused)
    assert deploy_check.classify_transport_error(wrapped.reason) == deploy_check.NOT_LISTENING


def test_windows_reset_during_startup_is_retryable():
    assert deploy_check.classify_transport_error(
        OSError(10054, "Windows connection reset")) == deploy_check.NO_ANSWER


def test_choose_available_port_falls_back_when_preferred_is_busy(monkeypatch):
    monkeypatch.setattr(deploy_check, "probe_ready", lambda port, timeout: deploy_check.FOREIGN)
    monkeypatch.setattr(deploy_check, "port_is_available", lambda port: port == 5002)

    assert deploy_check.choose_available_port(5000, 5000, 5005) == (5002, "fallback")


def test_choose_available_port_reuses_running_personnel_system(monkeypatch):
    monkeypatch.setattr(deploy_check, "probe_ready", lambda port, timeout: deploy_check.READY)
    monkeypatch.setattr(deploy_check, "port_is_available", lambda port: False)

    assert deploy_check.choose_available_port(5050, 5000, 5099) == (5050, "existing_ready")


def test_choose_available_port_reports_unavailable_existing_system(monkeypatch):
    monkeypatch.setattr(deploy_check, "probe_ready", lambda port, timeout: deploy_check.UNAVAILABLE)
    monkeypatch.setattr(deploy_check, "port_is_available", lambda port: False)

    assert deploy_check.choose_available_port(5000) == (5000, "existing_unavailable")


def test_choose_available_port_does_not_http_probe_a_free_port(monkeypatch):
    monkeypatch.setattr(deploy_check, "port_is_available", lambda port: True)
    monkeypatch.setattr(deploy_check, "probe_ready",
                        lambda port, timeout: (_ for _ in ()).throw(AssertionError("must not probe")))

    assert deploy_check.choose_available_port(5000) == (5000, "preferred")


def test_port_is_available_detects_a_real_listener():
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    try:
        assert deploy_check.port_is_available(listener.getsockname()[1]) is False
    finally:
        listener.close()


def test_ready_bind_first_reports_an_empty_port_without_http(monkeypatch):
    monkeypatch.setattr(deploy_check, "port_is_available", lambda port: True)
    monkeypatch.setattr(deploy_check, "probe_ready_detail",
                        lambda port, timeout: (_ for _ in ()).throw(AssertionError("must not probe")))
    args = Namespace(port="5000", timeout=3, quiet=True, trace=False, bind_first=True)

    assert deploy_check.cmd_ready(args) == deploy_check.NOT_LISTENING


def test_choose_port_saves_only_valid_numeric_port(tmp_path, monkeypatch):
    target = tmp_path / "logs" / "server.port"
    monkeypatch.setattr(deploy_check, "choose_available_port",
                        lambda preferred, start, end: (5007, "fallback"))
    args = type("Args", (), {"preferred": "5000", "range_start": "5000",
                              "range_end": "5099", "output": str(target)})()

    assert deploy_check.cmd_choose_port(args) == 0
    assert target.read_text(encoding="ascii") == "5007\n"


def test_choose_port_returns_distinct_existing_server_status(tmp_path, monkeypatch):
    target = tmp_path / "logs" / "server.port"
    args = type("Args", (), {"preferred": "5000", "range_start": "5000",
                              "range_end": "5099", "output": str(target)})()
    monkeypatch.setattr(deploy_check, "choose_available_port",
                        lambda preferred, start, end: (5000, "existing_ready"))
    assert deploy_check.cmd_choose_port(args) == deploy_check.CHOOSE_EXISTING_READY
    monkeypatch.setattr(deploy_check, "choose_available_port",
                        lambda preferred, start, end: (5000, "existing_unavailable"))
    assert deploy_check.cmd_choose_port(args) == deploy_check.CHOOSE_EXISTING_UNAVAILABLE


def test_retire_legacy_autostart_removes_shortcut_and_waits_for_lock(tmp_path, monkeypatch):
    appdata = tmp_path / "AppData" / "Roaming"
    shortcut = (appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" /
                "Startup" / "Personnel System.lnk")
    shortcut.parent.mkdir(parents=True)
    shortcut.write_bytes(b"legacy")
    calls = {"count": 0}

    def locked(_path):
        calls["count"] += 1
        return calls["count"] < 3

    monkeypatch.setattr(deploy_check, "is_file_locked", locked)
    problem = deploy_check.retire_legacy_autostart(
        tmp_path, {"APPDATA": str(appdata)}, timeout=1, sleep=lambda _seconds: None)

    assert problem is None
    assert not shortcut.exists()
    assert not (tmp_path / "logs" / "autostart.stop").exists()

import io
import logging
import zipfile

import pytest

from app import app as flask_app
from backend import tech_log
from backend.tech_log import ERRORS_LOG, SYSTEM_LOG


def _flush():
    for handler in logging.getLogger().handlers:
        handler.flush()


def _read(tmp_path, name=SYSTEM_LOG):
    _flush()
    path = tmp_path / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_request_line_has_status_duration_and_request_id(client, tmp_path):
    r = client.get("/api/auth/me")
    rid = r.headers["X-Request-Id"]
    assert rid and rid != "-"
    line = next(l for l in _read(tmp_path).splitlines() if "GET /api/auth/me 200" in l)
    assert "| INFO |" in line and f"| {rid} |" in line
    assert "| test_admin |" in line
    assert "status=200" in line and "duration_ms=" in line and "size=" in line
    assert line.split(" | ")[0][:4].isdigit()          # ISO timestamp


def test_incoming_request_id_is_kept_and_garbage_replaced(client):
    assert client.get("/api/auth/me", headers={"X-Request-Id": "abc-12345"}
                      ).headers["X-Request-Id"] == "abc-12345"
    bad = client.get("/api/auth/me", headers={"X-Request-Id": "x y"}).headers["X-Request-Id"]
    assert bad != "x y" and len(bad) == 12


def test_static_requests_are_not_logged_at_info(client, tmp_path):
    client.get("/static/css/tokens.css")
    assert "/static/css/tokens.css" not in _read(tmp_path)


@pytest.fixture
def boom_route(monkeypatch):
    def boom():
        raise RuntimeError("kaboom-marker")

    monkeypatch.setitem(flask_app.config, "TESTING", False)
    monkeypatch.setitem(flask_app.view_functions, "auth.me", boom)


def test_unhandled_exception_goes_to_errors_log_with_traceback(client, tmp_path, boom_route):
    r = client.get("/api/auth/me")
    assert r.status_code == 500
    rid = r.headers["X-Request-Id"]
    assert r.get_json()["request_id"] == rid
    errors = _read(tmp_path, ERRORS_LOG)
    assert "Traceback (most recent call last)" in errors
    assert "RuntimeError: kaboom-marker" in errors
    assert f"| {rid} |" in errors
    assert "| ERROR |" in errors and "GET /api/auth/me 500" in errors


def test_password_is_never_logged(anon_client, tmp_path):
    secret = "S3cr3t-Pa55w0rd-XYZ"
    anon_client.post("/api/auth/login", json={"username": "ghost", "role": "admin",
                                              "password": secret})
    text = _read(tmp_path) + _read(tmp_path, ERRORS_LOG)
    assert "login_failed" in text and "ghost" in text
    assert secret not in text


def test_secret_fields_are_masked():
    assert tech_log.format_fields({"password": "p", "api_key": "k", "ok": 1}) == \
        "password=*** api_key=*** ok=1"


def test_slow_request_logged_as_warning(client, tmp_path, monkeypatch):
    monkeypatch.setattr(tech_log, "SLOW_REQUEST_MS", -1)
    client.get("/api/auth/me")
    errors = _read(tmp_path, ERRORS_LOG)
    assert "| WARNING |" in errors and "slow=True" in errors


def _ours():
    return [h for h in logging.getLogger().handlers if getattr(h, "_personnel_tech_log", False)]


def test_setup_is_idempotent_and_does_not_leak_handlers(tmp_path):
    for _ in range(3):
        tech_log.setup_logging(tmp_path)
    assert len(_ours()) == 2


def test_log_level_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOG_LEVEL", "warning")
    assert tech_log.setup_logging(tmp_path)["level"] == "WARNING"
    monkeypatch.setenv("LOG_LEVEL", "nonsense")
    assert tech_log.setup_logging(tmp_path)["level"] == "INFO"


def test_logging_survives_unwritable_directory(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    tech_log.setup_logging(blocker / "sub")          # مسار مستحيل
    logging.getLogger("x").error("must not raise")


def test_store_save_is_logged_with_fields(client, tmp_path):
    r = client.post("/api/assignments/2026-04-10", json={"name": "خدمة", "kind": "خارجية"})
    assert r.status_code == 201
    line = next(l for l in _read(tmp_path).splitlines() if "store.save" in l)
    assert "files_written=" in line and "duration_ms=" in line


# ---------- صفحة السجلات ----------

def test_logs_page_and_api_are_admin_only(anon_client, individual_client, officer_client):
    assert anon_client.get("/api/tech-logs").status_code == 401
    # الضابط عنده سجل النشاط بس، مش السجلات الفنية.
    for low in (individual_client, officer_client):
        assert low.get("/api/tech-logs").status_code == 403
        assert low.get("/api/tech-logs/download?file=all").status_code == 403
        assert low.get("/tech-logs").status_code == 403
    assert "/tech-logs" not in officer_client.get("/audit").get_data(as_text=True)


def test_logs_api_filters_and_downloads(client, tmp_path):
    client.get("/api/auth/me")
    logging.getLogger("t").warning("needle-warning")
    r = client.get("/api/tech-logs?file=system&level=WARNING&q=needle")
    assert r.status_code == 200
    records = r.get_json()["records"]
    assert len(records) == 1 and "needle-warning" in records[0]
    assert client.get("/api/tech-logs?file=nope").status_code == 400
    assert client.get("/tech-logs").status_code == 200
    _flush()
    dl = client.get("/api/tech-logs/download?file=errors")
    assert dl.status_code == 200 and b"needle-warning" in dl.data
    zipped = client.get("/api/tech-logs/download?file=all")
    assert "system.log" in zipfile.ZipFile(io.BytesIO(zipped.data)).namelist()

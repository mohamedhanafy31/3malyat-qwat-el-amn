import io
import logging

import cv2
import numpy as np

from backend import tech_log
from backend.routes import afraad as route
from app import app as flask_app

DAY = "2026-04-10"


def _table(rows=4, cols=5):
    image = np.full((rows * 60 + 20, cols * 110 + 20, 3), 255, dtype=np.uint8)
    for row in range(rows + 1):
        cv2.line(image, (10, 10 + row * 60), (10 + cols * 110, 10 + row * 60), (0, 0, 0), 2)
    for col in range(cols + 1):
        cv2.line(image, (10 + col * 110, 10), (10 + col * 110, 10 + rows * 60), (0, 0, 0), 2)
    return image

SESSION = "abc123def4567890"


def _ocr_log(tmp_path):
    for handler in logging.getLogger(tech_log.OCR_LOGGER).handlers:
        handler.flush()
    path = tmp_path / tech_log.OCR_LOG
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _system_log(tmp_path):
    for handler in logging.getLogger().handlers:
        handler.flush()
    return (tmp_path / tech_log.SYSTEM_LOG).read_text(encoding="utf-8")


def _png():
    return io.BytesIO(cv2.imencode(".png", _table())[1].tobytes())


def _fake_result(*args, **kwargs):
    tech_log.ocr_event("ocr.match", matched=1)
    return {"ok": True, "grid": {"cell_count": 5, "confidence": 0.9}, "rows": [{"service_id": "AFB-01"}],
            "warnings": [], "summary": {"matched_services": 1, "matched_people": 1}}


def _preview(client, session=SESSION, **extra):
    data = {"image": (_png(), "اسم-سري-لفرد.png"), **extra}
    if session:
        data["ocr_session"] = session
    return client.post(f"/api/afraad/{DAY}/ocr/preview", data=data, content_type="multipart/form-data")


def test_preview_writes_ocr_log_with_session_and_no_filename(client, tmp_path, monkeypatch):
    monkeypatch.setattr(route, "analyze_image", lambda raw, filename, data, day: _fake_result())
    response = _preview(client, source="pdf", page="3")
    assert response.status_code == 200
    log = _ocr_log(tmp_path)
    lines = [l for l in log.splitlines() if "ocr.preview_received" in l]
    assert lines and f"ocr_session={SESSION}" in lines[0] and f"day={DAY}" in lines[0]
    assert "source=pdf" in lines[0] and "page=3" in lines[0] and "| test_admin |" in lines[0]
    assert f"ocr_session={SESSION}" in next(l for l in log.splitlines() if "ocr.preview_done" in l)
    assert "اسم-سري" not in log and "اسم-سري" not in _system_log(tmp_path)
    assert "ocr.preview_done" in _system_log(tmp_path)          # الأحداث بتوصل system.log كمان


def test_preview_without_session_gets_server_generated_one(client, tmp_path, monkeypatch):
    monkeypatch.setattr(route, "analyze_image", lambda raw, filename, data, day: _fake_result())
    assert _preview(client, session=None).status_code == 200
    line = next(l for l in _ocr_log(tmp_path).splitlines() if "ocr.preview_received" in l)
    assert "ocr_session=" in line and f"ocr_session={SESSION}" not in line


def test_real_pipeline_logs_stages_without_personal_data(client, tmp_path):
    response = _preview(client)
    assert response.status_code in (200, 503), response.get_data(as_text=True)
    log = _ocr_log(tmp_path)
    for name in ("ocr.preview_received", "ocr.decode", "ocr.grid"):
        assert name in log
    if response.status_code == 200:
        assert "ocr.analyze" in log and "ocr.match" in log and "ocr.preview_done" in log
    assert all(f"ocr_session={SESSION}" in l for l in log.splitlines() if "| ocr." in l or " ocr." in l)


def test_preview_exception_is_logged_with_stage_and_traceback(client, tmp_path, monkeypatch):
    def boom(raw, filename, data, day):
        tech_log.ocr_stage("cell_ocr")
        raise KeyError("kaboom")

    monkeypatch.setattr(route, "analyze_image", boom)
    monkeypatch.setitem(flask_app.config, "TESTING", False)
    assert _preview(client).status_code == 500
    log = _ocr_log(tmp_path)
    assert "ocr.preview_failed" in log and "stage=cell_ocr" in log and "KeyError" in log
    assert "ocr.preview_failed" in (tmp_path / tech_log.ERRORS_LOG).read_text(encoding="utf-8")


def test_apply_logs_session_and_stale_conflict(client, tmp_path):
    person = client.post("/api/person", json={
        "type": "personnel", "name": "فرد سجل", "code": "9911", "phone": "01012345600",
        "join_date": "2020-01-01", "role": "معاون شرطة"}).get_json()
    revision = client.get(f"/api/afraad/{DAY}").get_json()["revision"]
    ok = client.post(f"/api/afraad/{DAY}/ocr/apply", json={
        "revision": revision, "ocr_session": SESSION,
        "rows": [{"service_id": "AFB-01", "morning_person_id": person["id"]}]})
    assert ok.status_code == 200
    stale = client.post(f"/api/afraad/{DAY}/ocr/apply", json={
        "revision": revision, "ocr_session": SESSION,
        "rows": [{"service_id": "AFB-01", "morning_person_id": person["id"]}]})
    assert stale.status_code == 409
    log = _ocr_log(tmp_path)
    done = next(l for l in log.splitlines() if "ocr.apply_done" in l)
    assert f"ocr_session={SESSION}" in done and "applied=1" in done and "morning_set=1" in done
    assert "reason=stale_revision" in log
    assert "فرد سجل" not in log


# ---- نقطة أحداث المتصفح ----

URL = f"/api/afraad/{DAY}/ocr/client-log"


def test_client_log_accepts_whitelisted_events_and_drops_unknown(client, tmp_path):
    response = client.post(URL, json={"ocr_session": SESSION, "events": [
        {"event": "file_selected", "kind": "pdf", "bytes": 1234, "mime": "application/pdf",
         "ext": "pdf", "name_len": 11, "name": "secret-name.pdf", "extra": "x"},
        {"event": "page_rendered", "page": 2, "scale": 2.5, "width": 2200, "height": 3000, "ms": 80},
        {"event": "not_an_event", "bytes": 1},
        {"event": "preview_failed", "status": 500, "code": "<script>alert(1)</script>"},
    ]})
    assert response.status_code == 200 and response.get_json()["logged"] == 3
    log = _ocr_log(tmp_path)
    line = next(l for l in log.splitlines() if "ocr.client.file_selected" in l)
    assert f"ocr_session={SESSION}" in line and "kind=pdf" in line and "bytes=1234" in line
    assert "source=client" in line and "| test_admin |" in line
    assert "secret-name" not in log and "not_an_event" not in log and "extra" not in log
    assert "<script>" not in log and "ocr.client.page_rendered" in log


def test_client_log_rejects_too_many_oversize_and_invalid(client, tmp_path):
    many = [{"event": "upload_started", "bytes": 1}] * 21
    assert client.post(URL, json={"events": many}).status_code == 400
    assert client.post(URL, json={"events": [{"event": "cancelled", "stage": "x" * 9000}]}
                       ).status_code == 413
    assert client.post(URL, json={"events": "nope"}).status_code == 400
    assert client.post(URL, data="not json", content_type="application/json").status_code == 400
    assert "ocr.client" not in _ocr_log(tmp_path)


def test_client_log_bad_session_is_replaced_and_values_are_clamped(client, tmp_path):
    client.post(URL, json={"ocr_session": "bad session!\n", "events": [
        {"event": "cancelled", "stage": "scan\nFAKE | LINE " + "y" * 100},
        {"event": "upload_started", "bytes": "NaN", "source": "other"}]})
    log = _ocr_log(tmp_path)
    assert "bad session" not in log and "FAKE | LINE" not in log.replace("scan?FAKE", "")
    assert len([l for l in log.splitlines() if "ocr.client.cancelled" in l]) == 1


def test_client_log_needs_login_csrf_and_write_permission(anon_client, individual_client, client):
    body = {"events": [{"event": "cancelled", "stage": "scan"}]}
    assert anon_client.post(URL, json=body).status_code == 401
    assert client.post(URL, json=body, headers={"X-Requested-With": ""}).status_code in (400, 403)
    assert anon_client.post(URL, json=body, headers={"X-Requested-With": ""}).status_code == 403
    # نفس بوابة معاينة الصور بالظبط: أي حساب مسجّل دخوله بكل الأدوار (مفيش صلاحية أضيق)
    preview_gate = individual_client.post(f"/api/afraad/{DAY}/ocr/preview", data={}).status_code
    assert preview_gate != 403
    assert individual_client.post(URL, json=body).status_code == 200


# ---- صفحة السجلات الفنية ----

def test_tech_logs_can_read_and_download_ocr_file_admin_only(client, individual_client, tmp_path, monkeypatch):
    monkeypatch.setattr(route, "analyze_image", lambda raw, filename, data, day: _fake_result())
    _preview(client)
    _ocr_log(tmp_path)
    tail = client.get("/api/tech-logs?file=ocr&q=" + SESSION)
    assert tail.status_code == 200
    assert "ocr.preview_received" in str(tail.get_json())
    assert client.get("/api/tech-logs/download?file=ocr").status_code == 200
    assert individual_client.get("/api/tech-logs?file=ocr").status_code == 403
    assert "ocr.log" in client.get("/tech-logs").get_data(as_text=True)

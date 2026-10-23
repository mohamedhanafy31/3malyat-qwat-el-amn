"""كل قراءة OCR بتتسجّل (صورة + ناتج + الصح بعد المراجعة) لبناء موديل بعدين."""
import io
import json

from backend import ocr_samples

DAY = "2026-04-10"


def _preview(client, monkeypatch, rows=None):
    from backend.routes import afraad as route

    monkeypatch.setattr(route, "analyze_image", lambda raw, filename, data, day: {
        "ok": True, "grid": {"cell_count": 5, "confidence": .9}, "cells": [{"text": "x"}],
        "raw_ocr": {"text": "x"}, "overlay_png": "data:image/png;base64,AAAA",
        "rows": rows or [], "warnings": [], "summary": {}})
    response = client.post(f"/api/afraad/{DAY}/ocr/preview",
                           data={"image": (io.BytesIO(b"IMAGE-BYTES"), "roster.jpg")},
                           content_type="multipart/form-data")
    assert response.status_code == 200
    return response.get_json()["sample_id"]


def _person(client, code):
    return client.post("/api/person", json={
        "type": "personnel", "name": f"فرد {code}", "code": code, "phone": "01012345678",
        "join_date": "2020-01-01", "role": "معاون شرطة"}).get_json()["id"]


def test_preview_saves_image_and_prediction(client, monkeypatch):
    sample_id = _preview(client, monkeypatch)
    folder = ocr_samples.root() / DAY / sample_id
    assert (folder / "image.jpg").read_bytes() == b"IMAGE-BYTES"
    saved = json.loads((folder / "prediction.json").read_text(encoding="utf-8"))
    assert saved["prediction"]["cells"] == [{"text": "x"}]
    assert "overlay_png" not in saved["prediction"]            # صورة الخلايا مش مادة تدريب
    assert saved["services"][0]["id"] == "AFB-01"
    assert not (folder / "final.json").exists()                # لسه ما اتأكدتش


def test_apply_saves_the_reviewed_truth_with_edit_flags(client, monkeypatch):
    first, second = _person(client, "7701"), _person(client, "7702")
    rows = [{"service": "مدرعة", "service_id": "AFB-01", "morning": "فرد", "evening": "",
             "morning_match": {"matched": True, "id": first}, "night_match": {"matched": False}},
            {"service": "خط", "service_id": "AFB-02", "morning": "؟", "evening": "",
             "morning_match": {"matched": False}, "night_match": {"matched": False}}]
    sample_id = _preview(client, monkeypatch, rows)
    revision = client.get(f"/api/afraad/{DAY}").get_json()["revision"]
    response = client.post(f"/api/afraad/{DAY}/ocr/apply", json={
        "revision": revision, "sample_id": sample_id,
        "rows": [{"service_id": "AFB-01", "morning_person_id": second}],
        "review": [
            {"index": 0, "selected": True, "service_id": "AFB-01", "morning_person_id": second},
            {"index": 1, "selected": False, "service_id": "AFB-02"}]})
    assert response.status_code == 200, response.get_json()
    final = json.loads((ocr_samples.root() / DAY / sample_id / "final.json").read_text(encoding="utf-8"))
    kept, skipped = final["rows"]
    assert kept["selected"] and kept["edited"]                 # غيّر الفرد المقترح
    assert kept["morning"]["id"] == second and kept["service"]["name"]
    assert kept["read"]["service"] == "مدرعة"
    assert not skipped["selected"] and not skipped["edited"]   # نفس اقتراح النظام (مفيش حاجة)


def test_apply_without_sample_or_with_bad_id_still_works_and_writes_nothing(client, monkeypatch, tmp_path):
    person = _person(client, "7703")
    revision = client.get(f"/api/afraad/{DAY}").get_json()["revision"]
    for sample_id in ("", "../../etc", "20260101-000000-abcdef"):
        response = client.post(f"/api/afraad/{DAY}/ocr/apply", json={
            "revision": revision, "sample_id": sample_id,
            "rows": [{"service_id": "AFB-01", "morning_person_id": person}], "review": []})
        assert response.status_code in (200, 409)
        revision = response.get_json().get("revision") or client.get(
            f"/api/afraad/{DAY}").get_json()["revision"]
    assert not list(ocr_samples.root().glob("**/final.json"))


def test_recording_can_be_switched_off(client, monkeypatch):
    monkeypatch.setenv("OCR_SAMPLES_ENABLED", "0")
    assert _preview(client, monkeypatch) is None
    assert not ocr_samples.root().exists()

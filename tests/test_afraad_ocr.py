import io

import cv2
import numpy as np

from backend import afraad_ocr
from backend.afraad import BASIC_SERVICES
from backend.afraad_ocr_pipeline.grid import detect_grid


DAY = "2026-04-10"


def _table(rows=4, cols=5):
    image = np.full((rows * 60 + 20, cols * 110 + 20, 3), 255, dtype=np.uint8)
    for row in range(rows + 1):
        cv2.line(image, (10, 10 + row * 60), (10 + cols * 110, 10 + row * 60), (0, 0, 0), 2)
    for col in range(cols + 1):
        cv2.line(image, (10 + col * 110, 10), (10 + col * 110, 10 + rows * 60), (0, 0, 0), 2)
    return image


def test_cloned_grid_pipeline_keeps_five_columns():
    result = detect_grid(_table())
    assert result.ok
    assert len(result.vertical) - 1 == 5
    assert len(result.cells) == 20


def test_service_order_recovers_a_badly_read_cell_between_anchors():
    rows = []
    for index, service in enumerate(BASIC_SERVICES[:7], 1):
        text = service["name"]
        if index == 4:
            text = "نص غير مقروء"
        rows.append({"grid_row": index, "service": text, "morning": "", "evening": ""})
    aligned, offset = afraad_ocr._align_services(rows, BASIC_SERVICES)
    assert offset == 1
    fourth = next(row for row in aligned if row["grid_row"] == 4)
    assert fourth["service_id"] == BASIC_SERVICES[3]["id"]
    assert fourth["service_inferred_by_order"] is True


def test_person_match_accepts_unique_short_name_but_not_ambiguous_name():
    people = [
        {"id": "IND-1", "name": "عبد الحفيظ محمد عبد الحفيظ", "role": "معاون", "phone": "01000000001"},
        {"id": "IND-2", "name": "محمد احمد علي", "role": "معاون", "phone": "01000000002"},
        {"id": "IND-3", "name": "محمد احمد حسن", "role": "معاون", "phone": "01000000003"},
    ]
    certain = afraad_ocr._person_match("ا.ش/ عبد الحفيظ محمد عبد الحفيظ", people)
    assert certain["matched"] and certain["id"] == "IND-1"
    ambiguous = afraad_ocr._person_match("معاون/ محمد احمد", people)
    assert not ambiguous["matched"]


def test_ocr_preview_endpoint_returns_review_payload(client, monkeypatch):
    from backend.routes import afraad as route

    monkeypatch.setattr(route, "analyze_image", lambda raw, filename, data, day: {
        "ok": True, "grid": {"cell_count": 5, "confidence": 0.9}, "rows": [],
        "warnings": [], "summary": {"matched_services": 0, "matched_people": 0},
    })
    response = client.post(
        f"/api/afraad/{DAY}/ocr/preview",
        data={"image": (io.BytesIO(b"not-read-by-mock"), "roster.jpg")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert response.get_json()["revision"]


def test_ocr_apply_links_selected_person_without_clearing_other_shift(client):
    person = client.post("/api/person", json={
        "type": "personnel", "name": "فرد قراءة ضوئية", "code": "9901",
        "phone": "01012345678", "join_date": "2020-01-01", "role": "معاون شرطة",
    }).get_json()
    client.put(f"/api/afraad/{DAY}/basic/AFB-01", json={"night_name": "اسم ليلي موجود"})
    revision = client.get(f"/api/afraad/{DAY}").get_json()["revision"]
    response = client.post(f"/api/afraad/{DAY}/ocr/apply", json={
        "revision": revision,
        "rows": [{"service_id": "AFB-01", "morning_person_id": person["id"]}],
    })
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["applied"] == 1
    row = response.get_json()["data"]["basic"][0]
    assert row["morning"]["person_id"] == person["id"]
    assert row["night"]["name"] == "اسم ليلي موجود"


def test_ocr_apply_rejects_stale_preview(client):
    person = client.post("/api/person", json={
        "type": "personnel", "name": "فرد تعارض", "code": "9902",
        "phone": "01012345679", "join_date": "2020-01-01", "role": "معاون شرطة",
    }).get_json()
    revision = client.get(f"/api/afraad/{DAY}").get_json()["revision"]
    client.put(f"/api/afraad/{DAY}/basic/AFB-02", json={"count": "تعديل لاحق"})
    response = client.post(f"/api/afraad/{DAY}/ocr/apply", json={
        "revision": revision,
        "rows": [{"service_id": "AFB-01", "morning_person_id": person["id"]}],
    })
    assert response.status_code == 409
    assert response.get_json()["code"] == "stale_revision"

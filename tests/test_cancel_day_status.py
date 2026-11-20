"""إلغاء الحالة الحرة المحفوظة في يوم واحد فقط."""
import json
from pathlib import Path

from backend.store import assemble


DAY = "2026-05-01"
OTHER_DAY = "2026-05-02"
OFFICER = "OFF-002"


def _duty_row(client, day=DAY):
    body = client.get(f"/api/duty/{day}").get_json()
    return next(row for row in body["rows"] if row["id"] == OFFICER)


def test_cancel_day_status_clears_only_status_and_note(client):
    saved = client.put(f"/api/duty/{DAY}/{OFFICER}", json={
        "status": "حالة يومية", "note": "نص الحالة الخاص", "extra": "تشغيل إضافي",
        "taqseera": True, "admin_work": True, "announced": "phone",
    })
    assert saved.status_code == 200, saved.get_json()
    other = client.put(f"/api/duty/{OTHER_DAY}/{OFFICER}", json={
        "status": "حالة يوم آخر", "note": "ملاحظة أخرى",
    })
    assert other.status_code == 200, other.get_json()

    revision = client.get(f"/api/duty/{DAY}").get_json()["revision"]
    cancelled = client.post(f"/api/duty/{DAY}/{OFFICER}/cancel-day-status",
                            json={"revision": revision})
    assert cancelled.status_code == 200, cancelled.get_json()
    body = cancelled.get_json()
    assert {"summary", "daily", "revision", "officer_statuses"} <= body.keys()
    row = _duty_row(client)
    assert row["status"] == "" and row["note"] == ""
    assert row["extra"] == "تشغيل إضافي"
    assert row["taqseera"] is True and row["admin_work"] is True
    assert row["announced"] == "phone"
    assert _duty_row(client, OTHER_DAY)["status"] == "حالة يوم آخر"
    assert _duty_row(client, OTHER_DAY)["note"] == "ملاحظة أخرى"

    events = [event for event in assemble().get("change_log") or []
              if event.get("entity") == "officer_state"]
    assert any(event.get("text") == f"إلغاء حالة حالة يومية ليوم {DAY}" for event in events)


def test_cancel_day_status_accepts_legacy_archive_value_without_500(client, data_file):
    data = json.loads(data_file.read_text(encoding="utf-8"))
    data.setdefault("day_officers", {}).setdefault(DAY, {})[OFFICER] = {
        "status": "فرقة", "note": "ملاحظة فرقة قديمة", "extra": "إضافة محفوظة",
    }
    data_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    revision = client.get(f"/api/duty/{DAY}").get_json()["revision"]
    response = client.post(f"/api/duty/{DAY}/{OFFICER}/cancel-day-status",
                           json={"revision": revision})
    assert response.status_code == 200, response.get_json()
    row = _duty_row(client)
    assert row["status"] == "" and row["note"] == "" and row["extra"] == "إضافة محفوظة"


def test_cancel_day_status_rejects_stale_revision_and_keeps_state(client):
    client.put(f"/api/duty/{DAY}/{OFFICER}", json={
        "status": "حالة يومية", "note": "قبل التعديل",
    })
    old_revision = client.get(f"/api/duty/{DAY}").get_json()["revision"]
    client.put(f"/api/duty/{DAY}/{OFFICER}", json={
        "status": "حالة يومية", "note": "بعد التعديل",
    })
    response = client.post(f"/api/duty/{DAY}/{OFFICER}/cancel-day-status",
                           json={"revision": old_revision})
    assert response.status_code == 409
    assert response.get_json()["code"] == "stale_revision"
    assert _duty_row(client)["status"] == "حالة يومية"
    assert _duty_row(client)["note"] == "بعد التعديل"


def test_cancel_day_status_rejects_locked_day(client):
    client.put(f"/api/duty/{DAY}/{OFFICER}", json={"status": "حالة يومية", "note": "نص"})
    assert client.post(f"/api/day-status/{DAY}/close", json={}).status_code == 201
    revision = client.get(f"/api/duty/{DAY}").get_json()["revision"]
    response = client.post(f"/api/duty/{DAY}/{OFFICER}/cancel-day-status",
                           json={"revision": revision})
    assert response.status_code == 409
    assert "مغلق" in response.get_json()["error"]
    assert _duty_row(client)["status"] == "حالة يومية"


def test_cancel_day_status_without_a_status_returns_arabic_404(client):
    response = client.post(f"/api/duty/{DAY}/{OFFICER}/cancel-day-status", json={})
    assert response.status_code == 404
    assert "لا توجد حالة" in response.get_json()["error"]


def test_assign_modal_has_day_cancel_and_preserves_period_cancel_controls():
    root = Path(__file__).resolve().parent.parent
    modal = (root / "templates/partials/assign_modal.html").read_text(encoding="utf-8")
    source = (root / "static/js/duty.js").read_text(encoding="utf-8")
    assert 'id="assignCancelDayStatus"' in modal
    assert 'row.status_source === "day" && !!row.status' in source
    assert "/cancel-day-status" in source
    assert "سيُلغى تسجيل حالة «${row.status}» من هذا اليوم فقط" in source
    assert 'id="assignCancelPersistent"' in modal
    assert "/cancel-status" in source

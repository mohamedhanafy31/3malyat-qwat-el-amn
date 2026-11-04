"""السجل الدائم للراحات المحذوفة/الملغية واسترجاعها."""
import importlib
import json


def _saved(data_file):
    return json.loads(data_file.read_text(encoding="utf-8"))


def _leave(data, leave_id):
    return next((row for row in data.get("leaves", []) if row.get("id") == leave_id), None)


def _create(client, **overrides):
    body = {
        "person_id": "OFF-001", "type": "مرضي",
        "start": "2026-03-01", "end": "2026-03-09", "note": "اختبار",
    }
    body.update(overrides)
    response = client.post("/api/leaves", json=body)
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def _history(client):
    return client.get("/api/bootstrap/leaves").get_json()["leave_history"]


def _restore(client, event_id, headers=None):
    return client.post(f"/api/leaves/history/{event_id}/restore", headers=headers or {})


def test_delete_appears_then_restore_recreates_identical_leave_and_logs_change(client, data_file):
    created = _create(client)
    before = _leave(_saved(data_file), created["id"])

    deleted = client.delete(f"/api/leaves/{created['id']}")
    assert deleted.status_code == 200
    event = _history(client)[0]
    assert event["action"] == "delete" and event["before"] == before
    assert event["performed_by"] == "مدير الاختبارات"
    assert not event["restored_at"]

    restored = _restore(client, event["id"])
    assert restored.status_code == 200, restored.get_json()
    assert _leave(_saved(data_file), created["id"]) == before
    data = _saved(data_file)
    change = next(row for row in reversed(data["change_log"])
                  if row["entity"] == "leave" and row["action"] == "restore")
    marked = data["leave_history"][0]
    assert marked["restored_by"] == "مدير الاختبارات"
    assert marked["restore_change_id"] == change["id"]
    assert marked["restored_leave_id"] == created["id"]


def test_double_restore_is_rejected(client):
    leave = _create(client)
    client.delete(f"/api/leaves/{leave['id']}")
    event_id = _history(client)[0]["id"]
    assert _restore(client, event_id).status_code == 200
    second = _restore(client, event_id)
    assert second.status_code == 409
    assert "بالفعل" in second.get_json()["error"]


def test_restore_rejects_an_overlapping_leave(client):
    leave = _create(client)
    client.delete(f"/api/leaves/{leave['id']}")
    event_id = _history(client)[0]["id"]
    _create(client, type="إجازة طارئة", start="2026-03-04", end="2026-03-05")

    response = _restore(client, event_id)
    assert response.status_code == 409
    assert "راحة أخرى" in response.get_json()["error"]


def test_restore_a_shortened_leave_returns_its_previous_end(client, data_file, frozen_today):
    frozen_today("2026-02-28")
    leave = _create(client)
    frozen_today("2026-03-05")
    stopped = client.post(f"/api/leaves/{leave['id']}/stop",
                          json={"reason": "استدعاء عاجل", "on": "2026-03-05"})
    assert stopped.status_code == 200, stopped.get_json()
    event = _history(client)[0]
    assert event["action"] == "stop" and event["after"]["end"] == "2026-03-04"

    restored = _restore(client, event["id"], headers={"X-Retro-Reason": "تصحيح الإنهاء"})
    assert restored.status_code == 200, restored.get_json()
    saved = _leave(_saved(data_file), leave["id"])
    assert saved["end"] == "2026-03-09" and saved["return_date"] == "2026-03-10"
    assert not any(key in saved for key in
                   ("original_end", "stopped_on", "stop_reason", "suspension_id"))


def test_restore_has_the_same_authenticated_role_access_as_delete(
        client, officer_client, anon_client):
    leave = _create(client)
    assert officer_client.delete(f"/api/leaves/{leave['id']}").status_code == 200
    event_id = _history(officer_client)[0]["id"]
    assert officer_client.post(f"/api/leaves/history/{event_id}/restore").status_code == 200
    assert anon_client.post(f"/api/leaves/history/{event_id}/restore").status_code == 401


def test_migration_backfills_pre_existing_change_log_deletions():
    migration = importlib.import_module("migrations.027_leave_history")
    snapshot = {
        "id": "LV-314", "person_id": "OFF-001", "type": "أسبوعية",
        "start": "2026-04-11", "end": "2026-04-11", "return_date": "2026-04-12",
        "note": "", "source": "", "origin": "auto_weekly",
    }
    data = {
        "schema": 6, "officers": [{"id": "OFF-001", "name": "أحمد", "status": "active"}],
        "personnel": [], "id_seq": {},
        "change_log": [{
            "id": "CHG-314", "ts": "2026-04-11T10:00:00", "entity": "leave",
            "entity_id": "LV-314", "action": "delete", "before": snapshot,
            "after": None, "reason": "", "edited_by": "غرفة العمليات",
        }],
    }
    report = migration.migrate(data)
    assert report
    assert len(data["leave_history"]) == 1
    assert data["leave_history"][0]["change_id"] == "CHG-314"
    assert data["leave_history"][0]["before"] == snapshot
    assert migration.backfill_history(data) == 0


def test_weekly_seeding_does_not_duplicate_a_restored_auto_weekly_leave(
        client, data_file, frozen_today):
    friday, saturday = "2026-04-10", "2026-04-11"
    frozen_today(friday)
    seeded = client.post(f"/api/assignments/{saturday}",
                         json={"name": "فتح اليوم", "kind": "خارجية"})
    assert seeded.status_code == 201, seeded.get_json()
    data = _saved(data_file)
    weekly = next(row for row in data["leaves"]
                  if row.get("origin") == "auto_weekly" and row["start"] == saturday)
    client.delete(f"/api/leaves/{weekly['id']}")
    event_id = _history(client)[0]["id"]
    assert _restore(client, event_id).status_code == 200

    # فتح/تعديل اليوم مرة أخرى لا يعيد البذر لأن علامة اليوم محفوظة.
    client.post(f"/api/assignments/{saturday}",
                json={"name": "تعديل آخر", "kind": "داخلية"})
    rows = [row for row in _saved(data_file)["leaves"]
            if row.get("person_id") == "OFF-001" and row.get("origin") == "auto_weekly"
            and row["start"] == saturday]
    assert len(rows) == 1 and rows[0]["id"] == weekly["id"]


def test_old_data_without_leave_history_is_backfilled_on_load_and_restorable(
        client, data_file):
    leave = _create(client)
    before = _leave(_saved(data_file), leave["id"])
    client.delete(f"/api/leaves/{leave['id']}")
    # نحاكي ملف قديم: حذف حصل في change_log والمفتاح الجديد غير موجود.
    old = _saved(data_file)
    old.pop("leave_history")
    data_file.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")

    rows = _history(client)
    assert len(rows) == 1 and rows[0]["action"] == "delete"
    assert rows[0]["before"] == before and rows[0]["action_label"] == "حذف"
    assert _restore(client, rows[0]["id"]).status_code == 200
    assert _leave(_saved(data_file), leave["id"]) == before


def test_restore_unknown_event_is_404(client):
    assert _restore(client, "LVH-999").status_code == 404

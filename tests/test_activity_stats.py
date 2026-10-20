import json

from backend import store
from backend.auth import users
from backend.auth import audit_log


def _row(ts, event, user, method="GET", path="/"):
    return {"ts": ts, "event": event, "method": method, "path": path,
            "user_id": user["id"], "username": user["username"],
            "display_name": user["display_name"], "role": user["role"],
            "ip": "127.0.0.1", "status": 200, "edited_by": user["display_name"]}


def test_activity_stats_aggregate_members_and_estimate_active_time(
        client, officer_client, individual_client):
    admin = users.by_username("test_admin")
    officer = users.by_username("test_officer")
    rows = [
        _row("2026-10-01T09:00:00", "login_ok", admin, "POST", "/api/auth/login"),
        _row("2026-10-01T09:05:00", "write", admin, "POST", "/api/assignments/2026-10-01"),
        _row("2026-10-01T09:30:00", "logout", admin, "POST", "/api/auth/logout"),
        _row("2026-10-01T10:00:00", "login_ok", officer, "POST", "/api/auth/login"),
        _row("2026-10-01T10:10:00", "write", officer, "POST", "/api/assignments/2026-10-01"),
        _row("2026-10-01T10:20:00", "write", officer, "PATCH", "/api/assignments/2026-10-01/A-1"),
        {"ts": "2026-10-01T10:25:00", "event": "login_failed", "method": "POST",
         "path": "/api/auth/login", "user_id": None, "username": officer["username"],
         "display_name": officer["username"], "role": "officer", "ip": "127.0.0.1",
         "status": 401, "detail": "كلمة مرور خاطئة"},
    ]
    (store._LOG_DIR / "audit.log").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
    audit_log._FILE_CACHE.clear()

    response = officer_client.get("/api/activity-stats?from=2026-10-01&to=2026-10-01")
    assert response.status_code == 200
    data = response.get_json()
    assert data["summary"]["logins"] == 2
    assert data["summary"]["changes"] == 3
    assert data["summary"]["failed_logins"] == 1
    assert data["daily"] == [{"day": "2026-10-01", "changes": 3,
                               "logins": 2, "active_members": 2}]

    admin_stats = next(row for row in data["members"] if row["id"] == admin["id"])
    officer_stats = next(row for row in data["members"] if row["id"] == officer["id"])
    assert admin_stats["estimated_active_minutes"] == 20  # 5 + سقف 15 دقيقة
    assert officer_stats["estimated_active_minutes"] == 20
    assert officer_stats["changes"] == 2
    assert officer_stats["failed_logins"] == 1
    assert officer_stats["top_action"] in {"إضافة تكليف", "تعديل تكليف"}

    assert individual_client.get("/api/activity-stats?from=2026-10-01&to=2026-10-01").status_code == 403


def test_activity_stats_page_permissions_and_range_validation(
        client, officer_client, individual_client, conscript_client):
    for allowed in (client, officer_client):
        assert allowed.get("/activity-stats").status_code == 200
        assert allowed.get("/api/activity-stats?from=2026-01-01&to=2026-01-31").status_code == 200
    for denied in (individual_client, conscript_client):
        assert denied.get("/activity-stats").status_code == 403
        assert denied.get("/api/activity-stats").status_code == 403

    assert client.get("/api/activity-stats?from=nope&to=2026-01-01").get_json()["code"] == "invalid_date"
    assert client.get("/api/activity-stats?from=2026-02-01&to=2026-01-01").get_json()["code"] == "invalid_range"
    assert client.get("/api/activity-stats?from=2025-01-01&to=2026-12-31").get_json()["code"] == "range_too_large"

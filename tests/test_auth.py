"""عقد المصادقة والصلاحيات وسجل النشاط."""
import json

from flask import template_rendered

from backend.auth import current_actor, users
from backend.auth.audit_log import emit
from app import app


def _create(client, username, role="individual", **extra):
    body = {"username": username, "display_name": username, "role": role,
            "password": "password-123", **extra}
    return client.post("/api/users", json=body)


def test_setup_is_loopback_only_and_bootstraps_session(anon_client):
    assert anon_client.get("/login").headers["Location"].endswith("/setup")
    assert anon_client.get("/setup", environ_base={"REMOTE_ADDR": "10.0.0.2"}).status_code == 403
    response = anon_client.post("/api/auth/setup", json={
        "username": "First.Admin", "display_name": "المدير الأول", "password": "password-123"})
    assert response.status_code == 201
    assert anon_client.get("/api/auth/me").get_json()["user"]["role"] == "admin"
    assert anon_client.post("/api/auth/setup", json={}).status_code == 403


def test_login_logout_and_no_attempt_limit(anon_client):
    """مفيش حد لعدد المحاولات الفاشلة — الدخول الصح لازم ينجح بعد أي عدد منها."""
    users.create("login_user", "مستخدم الدخول", "officer", "password-123", "اختبار")
    for _ in range(12):
        response = anon_client.post("/api/auth/login", json={
            "role": "admin", "username": "LOGIN_USER", "password": "wrong"})
        assert response.status_code == 401
    assert anon_client.post("/api/auth/login", json={
        "role": "officer", "username": "login_user", "password": "password-123"}).status_code == 200
    assert anon_client.post("/api/auth/logout").get_json() == {"ok": True}
    assert anon_client.get("/api/auth/me").status_code == 401


def test_csrf_header_is_required_even_for_login(anon_client):
    response = anon_client.post("/api/auth/login", json={}, headers={"X-Requested-With": ""})
    assert response.status_code == 403
    assert response.get_json()["code"] == "csrf"


def test_login_page_gets_roles_in_contract_order(client):
    rendered = []

    def capture(sender, template, context, **extra):
        rendered.append(context)

    template_rendered.connect(capture, app)
    try:
        assert client.get("/login?next=/audit").status_code == 200
    finally:
        template_rendered.disconnect(capture, app)
    assert rendered[-1]["next"] == "/audit"
    assert rendered[-1]["roles"] == [
        {"key": "admin", "label": "ادمن"},
        {"key": "officer", "label": "ضابط"},
        {"key": "individual", "label": "فرد"},
        {"key": "conscript", "label": "مجند"},
    ]


def test_login_requires_role_and_hides_all_credential_mismatches(
        client, officer_client, anon_client):
    _create(client, "role_check", role="officer")
    disabled = _create(client, "stopped_user", role="officer").get_json()["user"]
    assert client.patch(f"/api/users/{disabled['id']}", json={"active": False}).status_code == 200

    missing = anon_client.post("/api/auth/login", json={
        "username": "role_check", "password": "password-123"})
    assert missing.status_code == 400
    assert missing.get_json() == {"error": "اختر نوع المستخدم.", "code": "role_required"}

    attempts = [
        ({"role": "admin", "username": "role_check", "password": "password-123"},
         "الدور المختار لا يطابق الحساب"),
        ({"role": "officer", "username": "role_check", "password": "wrong-password"},
         "كلمة مرور خاطئة"),
        ({"role": "officer", "username": "missing_user", "password": "password-123"},
         "حساب غير موجود"),
        ({"role": "officer", "username": "stopped_user", "password": "password-123"},
         "حساب موقوف"),
    ]
    expected = {"error": "بيانات الدخول غير صحيحة.", "code": "invalid_credentials"}
    for body, detail in attempts:
        response = anon_client.post("/api/auth/login", json=body)
        assert response.status_code == 401
        assert response.get_json() == expected
        entries = client.get(f"/api/audit?user={body['username']}").get_json()["entries"]
        entry = next(row for row in entries if row["detail"] == detail)
        assert entry["username"] == body["username"]
        assert entry["role"] == body["role"]
        assert entry["detail"] == detail

    officer_entry = officer_client.get("/api/audit?user=role_check").get_json()["entries"][0]
    assert officer_entry["detail"] in {"الدور المختار لا يطابق الحساب", "كلمة مرور خاطئة"}


def _sample_path(rule):
    values = {}
    for name in rule.arguments:
        values[name] = {"year": 2026, "month": 1, "day": "2026-01-01",
                        "page": "dashboard", "filename": "x.png",
                        "weekday": "السبت", "section": "s", "shift": "s",
                        "name": "s"}.get(name, "missing-id")
    return app.url_map.bind("").build(rule.endpoint, values)


def test_every_route_is_default_deny_for_anonymous(anon_client):
    public = {("GET", "/login"), ("GET", "/setup"),
              ("POST", "/api/auth/login"), ("POST", "/api/auth/setup")}
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        path = _sample_path(rule)
        for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            if (method, path) in public:
                continue
            response = anon_client.open(path, method=method)
            assert response.status_code in (302, 401), (method, path, response.status_code)


def test_view_logs_role_matrix(client, officer_client, individual_client, conscript_client):
    for allowed in (client, officer_client):
        assert allowed.get("/changes").status_code == 200
        assert allowed.get("/audit").status_code == 200
        assert allowed.get("/api/changes").status_code == 200
        assert allowed.get("/api/audit").status_code == 200
        assert allowed.get("/api/bootstrap/changes").status_code == 200
    for denied in (individual_client, conscript_client):
        assert denied.get("/changes").status_code == 403
        assert denied.get("/audit").status_code == 403
        assert denied.get("/api/changes").get_json()["code"] == "forbidden"
        assert denied.get("/api/audit").get_json()["code"] == "forbidden"
        assert "recent_changes" not in denied.get("/api/bootstrap/dashboard").get_json()


def test_dashboard_recent_changes_visibility(client, officer_client,
                                             individual_client, conscript_client):
    assert "recent_changes" in client.get("/api/bootstrap/dashboard").get_json()
    assert "recent_changes" in officer_client.get("/api/bootstrap/dashboard").get_json()
    assert "recent_changes" not in individual_client.get("/api/bootstrap/dashboard").get_json()
    assert "recent_changes" not in conscript_client.get("/api/bootstrap/dashboard").get_json()
    assert individual_client.get("/api/bootstrap/changes").status_code == 403


def test_full_data_hides_change_log_without_view_logs(
        client, officer_client, individual_client, conscript_client):
    day = "2026-06-01"
    client.post(f"/api/assignments/{day}", json={"name": "خدمة", "kind": "خارجية"})
    client.post(f"/api/board/{day}/confirm", json={})
    assert "change_log" in client.get("/api/data").get_json()
    assert "change_log" in officer_client.get("/api/data").get_json()
    assert "change_log" not in individual_client.get("/api/data").get_json()
    assert "change_log" not in conscript_client.get("/api/data").get_json()


def test_manage_users_role_matrix(client, officer_client, individual_client, conscript_client):
    assert client.get("/users").status_code == 200
    assert client.get("/api/users").status_code == 200
    for denied in (officer_client, individual_client, conscript_client):
        assert denied.get("/users").status_code == 403
        assert denied.get("/api/users").get_json()["code"] == "forbidden"


def test_created_user_can_login_without_password_change_gate(client):
    made = _create(client, "temporary_user", role="officer").get_json()["user"]
    assert "must_change_password" not in made
    login_client = app.test_client()
    response = login_client.post("/api/auth/login", json={
        "role": "officer", "username": "TEMPORARY_USER", "password": "password-123"})
    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "next": "/"}
    assert "must_change_password" not in login_client.get("/api/auth/me").get_json()["user"]


def test_legacy_must_change_password_value_is_ignored(client):
    made = _create(client, "legacy_password_flag").get_json()["user"]
    with users.LOCK:
        rows = users._read_unlocked()
        stored = next(row for row in rows if row["id"] == made["id"])
        stored["must_change_password"] = True
        stored.pop("session_version", None)
        users._write_unlocked(rows)
    legacy_client = app.test_client()
    login = legacy_client.post("/api/auth/login", json={
        "role": "individual", "username": "legacy_password_flag",
        "password": "password-123"})
    assert login.status_code == 200
    assert legacy_client.get("/").status_code == 200
    assert "must_change_password" not in legacy_client.get("/api/auth/me").get_json()["user"]


def test_removed_password_change_endpoints_return_not_found(client):
    assert client.get("/change-password").status_code == 404
    assert client.post("/api/auth/password", json={}).status_code == 404


def test_last_admin_and_cannot_disable_self(client):
    me = client.get("/api/auth/me").get_json()["user"]
    response = client.patch(f"/api/users/{me['id']}", json={"active": False})
    assert response.status_code == 409
    assert response.get_json()["code"] == "cannot_disable_self"
    response = client.patch(f"/api/users/{me['id']}", json={"role": "officer"})
    assert response.status_code == 409
    assert response.get_json()["code"] == "last_admin"


def test_deactivated_users_session_is_rejected(client):
    made = _create(client, "disable_me").get_json()["user"]
    other = app.test_client()
    assert other.post("/api/auth/login", json={
        "role": "individual", "username": "disable_me", "password": "password-123"}).status_code == 200
    assert other.get("/api/auth/me").status_code == 200
    assert client.patch(f"/api/users/{made['id']}", json={"active": False}).status_code == 200
    assert other.get("/api/auth/me").status_code == 401


def test_role_change_applies_to_an_existing_session_immediately(client, officer_client):
    assert officer_client.get("/api/audit").status_code == 200
    officer = next(u for u in client.get("/api/users").get_json()["users"]
                   if u["username"] == "test_officer")
    assert client.patch(f"/api/users/{officer['id']}", json={"role": "individual"}).status_code == 200
    response = officer_client.get("/api/audit")
    assert response.status_code == 401
    assert response.get_json()["code"] == "unauthenticated"


def test_username_and_password_changes_invalidate_existing_sessions(client):
    for username, change in (
            ("rename_session", {"username": "renamed_session"}),
            ("password_session", {"password": "replacement-password"})):
        made = _create(client, username).get_json()["user"]
        logged_in = app.test_client()
        assert logged_in.post("/api/auth/login", json={
            "role": "individual", "username": username,
            "password": "password-123"}).status_code == 200
        assert client.patch(f"/api/users/{made['id']}", json=change).status_code == 200
        assert logged_in.get("/api/auth/me").status_code == 401


def test_self_credential_edit_reissues_admin_session_and_audits_safely(client):
    me = client.get("/api/auth/me").get_json()["user"]
    response = client.patch(f"/api/users/{me['id']}", json={
        "username": "renamed_admin", "password": "replacement-password"})
    assert response.status_code == 200
    assert client.get("/api/auth/me").get_json()["user"]["username"] == "renamed_admin"
    entry = client.get("/api/audit?event=user_updated").get_json()["entries"][0]
    assert "تغيير اسم المستخدم: test_admin ← renamed_admin" in entry["detail"]
    assert "تغيير كلمة المرور" in entry["detail"]
    assert "replacement-password" not in json.dumps(entry, ensure_ascii=False)


def test_user_credential_update_validation_and_self_demotion_guard(client):
    second = _create(client, "second_admin", role="admin").get_json()["user"]
    target = _create(client, "validation_user").get_json()["user"]
    assert client.patch(f"/api/users/{target['id']}", json={
        "username": "second_ADMIN"}).get_json()["code"] == "username_taken"
    assert client.patch(f"/api/users/{target['id']}", json={
        "username": "x"}).get_json()["code"] == "invalid_username"
    assert client.patch(f"/api/users/{target['id']}", json={
        "password": "short"}).get_json()["code"] == "weak_password"
    me = client.get("/api/auth/me").get_json()["user"]
    demote = client.patch(f"/api/users/{me['id']}", json={"role": "officer"})
    assert demote.status_code == 409
    assert demote.get_json()["code"] == "cannot_demote_self"
    assert second["role"] == "admin"


def test_forged_actor_fields_and_header_are_ignored(client, tmp_path):
    from backend import store
    day = "2026-06-02"
    forged = {"X-Edited-By": "forged-header"}
    client.post(f"/api/assignments/{day}", json={"name": "خدمة", "kind": "خارجية"},
                headers=forged)
    confirmed = client.post(f"/api/board/{day}/confirm",
                            json={"confirmed_by": "forged-confirm"}, headers=forged).get_json()
    assert confirmed["by"] == "مدير الاختبارات"

    closed = client.post(f"/api/day-status/{day}/close",
                         json={"closed_by": "forged-close"}).get_json()
    assert closed["closed_by"] == "مدير الاختبارات"
    reopened = client.post(f"/api/day-status/{day}/reopen", json={
        "reason": "تصحيح", "reopened_by": "forged-reopen"}).get_json()
    assert reopened["reopened_by"] == "مدير الاختبارات"

    changes = client.get(f"/api/changes?day={day}").get_json()["entries"]
    assert changes
    assert all(entry["edited_by"] == "مدير الاختبارات" for entry in changes)
    assert all("forged" not in json.dumps(entry, ensure_ascii=False) for entry in changes)

    for handler in store._audit_logger.handlers:
        handler.flush()
    raw_rows = [json.loads(line) for line in (tmp_path / "audit.log").read_text(
        encoding="utf-8").splitlines()]
    writes = [row for row in raw_rows if row.get("event") == "write"]
    assert writes and all(row["display_name"] == "مدير الاختبارات" for row in writes)
    assert "forged-header" not in json.dumps(writes, ensure_ascii=False)


def test_auth_and_user_audit_events_have_actor_and_never_password(client, tmp_path):
    from backend import store
    password = "unique-temp-password"
    made = client.post("/api/users", json={
        "username": "audit_user", "display_name": "مستخدم التدقيق", "role": "officer",
        "password": password}).get_json()["user"]
    assert client.patch(f"/api/users/{made['id']}", json={
        "role": "individual", "display_name": "مستخدم محدث"}).status_code == 200
    login_client = app.test_client()
    assert login_client.post("/api/auth/login", json={
        "role": "individual", "username": "audit_user", "password": "wrong-password"}).status_code == 401
    assert login_client.post("/api/auth/login", json={
        "role": "individual", "username": "AUDIT_USER", "password": password}).status_code == 200
    assert client.post(f"/api/users/{made['id']}/reset-password", json={
        "password": "replacement-password"}).status_code == 200
    assert login_client.get("/api/auth/me").status_code == 401

    expected = {"login_failed": "audit_user", "login_ok": "audit_user",
                "user_created": "test_admin", "user_updated": "test_admin",
                "password_reset": "test_admin"}
    for event, username in expected.items():
        entries = client.get(f"/api/audit?event={event}").get_json()["entries"]
        assert entries and entries[0]["username"].casefold() == username.casefold()

    failed = client.get("/api/audit?event=login_failed").get_json()["entries"][0]
    assert failed["display_name"] == "audit_user"
    assert failed["role"] == "individual"
    assert failed["detail"] == "كلمة مرور خاطئة"

    created = client.get("/api/audit?event=user_created").get_json()["entries"][0]
    assert created["target_username"] == "audit_user"
    assert created["detail"] == "بدور ضابط"
    assert created["action_label"] == "إنشاء حساب «audit_user» بدور ضابط"

    updated = client.get("/api/audit?event=user_updated").get_json()["entries"][0]
    assert updated["target_username"] == "audit_user"
    assert "الدور: ضابط ← فرد" in updated["detail"]
    assert "الاسم الظاهر: مستخدم التدقيق ← مستخدم محدث" in updated["detail"]
    assert "audit_user" in updated["action_label"]

    reset = client.get("/api/audit?event=password_reset").get_json()["entries"][0]
    assert reset["target_username"] == "audit_user"
    assert reset["detail"] == "تغيير كلمة المرور"
    assert "audit_user" in reset["action_label"]
    serialized = json.dumps(client.get("/api/audit?limit=500").get_json(), ensure_ascii=False)
    assert password not in serialized
    assert "replacement-password" not in serialized
    for handler in store._audit_logger.handlers:
        handler.flush()
    raw = (tmp_path / "audit.log").read_text(encoding="utf-8")
    assert password not in raw and "replacement-password" not in raw
    failed_raw = next(row for row in map(json.loads, raw.splitlines())
                      if row.get("event") == "login_failed")
    assert failed_raw["display_name"] == "audit_user"
    assert failed_raw["edited_by"] == "audit_user"


def test_audit_file_cache_reuses_unchanged_file_and_invalidates_on_append(
        client, tmp_path, monkeypatch):
    from backend import store
    from backend.auth import audit_log

    emit("login_ok")
    for handler in store._audit_logger.handlers:
        handler.flush()
    with audit_log._CACHE_LOCK:
        audit_log._FILE_CACHE.clear()

    parsed = []
    original = audit_log._parse_file

    def counting_parse(path):
        parsed.append(path)
        return original(path)

    monkeypatch.setattr(audit_log, "_parse_file", counting_parse)
    assert client.get("/api/audit").status_code == 200
    first_count = len(parsed)
    assert first_count == 1
    assert client.get("/api/audit?event=login_ok").status_code == 200
    assert len(parsed) == first_count

    appended = {"ts": "2099-01-01T00:00:00", "event": "write", "method": "PATCH",
                "path": "/api/person/OFF-CACHE", "username": "cache_user",
                "display_name": "اختبار الكاش", "role": "admin", "status": 200}
    with (tmp_path / "audit.log").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(appended, ensure_ascii=False) + "\n")

    response = client.get("/api/audit?q=OFF-CACHE").get_json()
    assert len(parsed) == first_count + 1
    assert response["entries"][0]["username"] == "cache_user"
    assert "cache_user" in response["users"]


def test_audit_filters_pagination_and_legacy_line(client, tmp_path):
    from backend import store
    emit("login_ok")
    client.post("/api/assignments/2026-04-10", json={"name": "خدمة", "kind": "خارجية"})
    with (tmp_path / "audit.log").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"ts": "2020-01-01T01:02:03", "method": "PATCH",
                                 "path": "/api/person/OFF-1", "edited_by": "قديم"},
                                ensure_ascii=False) + "\n")
    first = client.get("/api/audit?limit=1").get_json()
    assert len(first["entries"]) == 1 and first["next_before"]
    second = client.get("/api/audit?limit=500&before=" + first["next_before"]).get_json()
    assert second["entries"]
    assert client.get("/api/audit?event=login_ok").get_json()["entries"]
    legacy = client.get("/api/audit?q=قديم").get_json()["entries"][0]
    assert legacy["event"] == "write"
    assert legacy["username"] is None
    assert legacy["display_name"] == "قديم"
    assert legacy["action_label"] == "تعديل بيانات فرد"


def test_system_actor_outside_request_context():
    assert current_actor()["display_name"] == "النظام"


def test_login_failed_reason_is_visible_in_audit_label(client, anon_client):
    """سبب فشل الدخول (دور غلط مثلًا) بيظهر للأدمن في سجل النشاط بس —
    الرد على المستخدم نفسه ثابت ومابيكشفش حاجة."""
    from backend.auth import users
    users.create("reason_user", "سبب", "officer", "password123", "اختبار")
    r = anon_client.post("/api/auth/login", headers={"X-Requested-With": "fetch"},
                         json={"role": "admin", "username": "reason_user", "password": "password123"})
    assert r.status_code == 401 and r.get_json()["code"] == "invalid_credentials"
    entry = client.get("/api/audit?event=login_failed").get_json()["entries"][0]
    assert "الدور المختار لا يطابق الحساب" in entry["action_label"]

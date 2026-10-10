"""الربط المركزي للمصادقة والصلاحيات مع Flask."""
from datetime import timedelta
from urllib.parse import quote

from flask import g, jsonify, redirect, render_template, request, session

from . import users
from .roles import can as role_can, capabilities
from .security import LazySecretSessionInterface, secret_key

PUBLIC = {("GET", "/login"), ("GET", "/setup"),
          ("POST", "/api/auth/login"), ("POST", "/api/auth/setup")}


def current_user():
    if hasattr(g, "auth_user"):
        return g.auth_user
    user = users.by_id(session.get("user_id")) if session.get("user_id") else None
    g.auth_user = user if user and user.get("active") else None
    return g.auth_user


def current_actor():
    """هوية آمنة للسجلات، وتعمل كمان خارج سياق أي طلب."""
    try:
        user = current_user()
        if user:
            return {"user_id": user["id"], "username": user["username"],
                    "display_name": user["display_name"], "role": user["role"],
                    "ip": request.remote_addr or None}
    except RuntimeError:
        pass
    return {"user_id": None, "username": None, "display_name": "النظام",
            "role": None, "ip": None}


def can(capability):
    user = current_user()
    return bool(user and role_can(user.get("role"), capability))


def _error(message, code, status):
    return jsonify({"error": message, "code": code}), status


def _required_capability(path):
    if path == "/changes" or path == "/audit" or path == "/api/changes" or path == "/api/audit" or path == "/api/bootstrap/changes":
        return "view_logs"
    if path == "/users" or path == "/api/users" or path.startswith("/api/users/"):
        return "manage_users"
    return None


def init_app(app):
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=8))
    app.session_interface = LazySecretSessionInterface()

    @app.before_request
    def enforce_auth():
        # المفتاح بيتحسب هنا عشان DATA_DIR المتغير في الاختبارات يفضل معزول.
        app.secret_key = secret_key()
        path = request.path
        if path.startswith("/static/") and request.method in ("GET", "HEAD"):
            return None
        if path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get("X-Requested-With") != "fetch":
                return _error("الطلب غير مسموح بدون ترويسة الحماية.", "csrf", 403)
        if (request.method, path) in PUBLIC:
            return None
        user = current_user()
        if not user:
            session.clear()
            page_endpoint = (request.endpoint or "").startswith("pages.") or request.endpoint in {
                "auth.login_page", "auth.setup_page", "auth.change_password_page"}
            if path.startswith("/api/") or not page_endpoint:
                return _error("لازم تسجّل الدخول أولًا.", "unauthenticated", 401)
            original = path + (("?" + request.query_string.decode()) if request.query_string else "")
            return redirect("/login?next=" + quote(original, safe=""))
        session.permanent = True
        cap = _required_capability(path)
        if cap and not can(cap):
            from .audit_log import emit
            emit("access_denied", status=403)
            if path.startswith("/api/"):
                return _error("غير مصرّح لك بالوصول.", "forbidden", 403)
            return render_template("403.html", page="forbidden", page_title="غير مصرّح"), 403
        if user.get("must_change_password") and path not in ("/change-password", "/api/auth/me", "/api/auth/password", "/api/auth/logout"):
            if path.startswith("/api/"):
                return _error("لازم تغيّر كلمة المرور أولًا.", "password_change_required", 403)
            return redirect("/change-password")

    @app.context_processor
    def auth_context():
        user = current_user()
        public_user = users.public(user, compact=True) if user else None
        if public_user:
            public_user.pop("must_change_password", None)
        return {"current_user": public_user, "can": can}

    @app.after_request
    def audit_successful_writes(response):
        count = getattr(g, "audit_writes", 0)
        if count:
            from .audit_log import emit
            for _ in range(count):
                emit("write", status=response.status_code)
        return response


__all__ = ["capabilities", "current_actor", "current_user", "init_app"]

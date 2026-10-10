"""صفحات ونداءات الدخول، الإعداد الأول، وتغيير كلمة المرور."""
import threading
import time

from flask import Blueprint, jsonify, redirect, render_template, request, session

from ..auth import capabilities, current_user
from ..auth import users
from ..auth.audit_log import emit

bp = Blueprint("auth", __name__)
_FAILURES = {}
_THROTTLE_LOCK = threading.Lock()


def reset_throttle():
    with _THROTTLE_LOCK:
        _FAILURES.clear()


def _safe_next(value):
    value = str(value or "")
    return value if (value.startswith("/") and not value.startswith("//")
                     and "\\" not in value and not any(ord(ch) < 32 for ch in value)) else "/"


def _failure_key(username):
    return (str(username or "").strip().casefold(), request.remote_addr or "")


def _throttled(key):
    now = time.monotonic()
    with _THROTTLE_LOCK:
        recent = [stamp for stamp in _FAILURES.get(key, []) if now - stamp < 300]
        _FAILURES[key] = recent
        return len(recent) >= 5


@bp.get("/login")
def login_page():
    if users.count() == 0:
        return redirect("/setup")
    return render_template("login.html", next=_safe_next(request.args.get("next")))


@bp.get("/setup")
def setup_page():
    if users.count():
        return redirect("/login")
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return render_template("403.html", page="forbidden", page_title="غير مصرّح"), 403
    return render_template("setup.html")


@bp.get("/change-password")
def change_password_page():
    return render_template("change_password.html")


@bp.post("/api/auth/login")
def login():
    body = request.get_json(silent=True) or {}
    username = str(body.get("username") or "").strip()
    key = _failure_key(username)
    if _throttled(key):
        emit("login_failed", status=429, username=username)
        return jsonify(error="محاولات كثيرة. حاول بعد خمس دقائق.", code="too_many_attempts"), 429
    user = users.by_username(username)
    if not users.verify(user, body.get("password")):
        with _THROTTLE_LOCK:
            _FAILURES.setdefault(key, []).append(time.monotonic())
        emit("login_failed", status=401, username=username)
        return jsonify(error="اسم المستخدم أو كلمة المرور غير صحيحة.", code="invalid_credentials"), 401
    with _THROTTLE_LOCK:
        _FAILURES.pop(key, None)
    session.clear()
    session["user_id"] = user["id"]
    session.permanent = True
    users.mark_login(user["id"])
    emit("login_ok")
    return jsonify(ok=True, next=_safe_next(body.get("next")),
                   must_change_password=bool(user.get("must_change_password")))


@bp.post("/api/auth/setup")
def setup():
    if users.count():
        return jsonify(error="تم إعداد النظام بالفعل.", code="setup_complete"), 403
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return jsonify(error="الإعداد الأول متاح من نفس الجهاز فقط.", code="forbidden"), 403
    body = request.get_json(silent=True) or {}
    try:
        user = users.create(body.get("username"), body.get("display_name"), "admin",
                            body.get("password"), "النظام", False)
    except users.UserError as exc:
        return jsonify(error=str(exc), code=exc.code), exc.status
    session["user_id"] = user["id"]
    session.permanent = True
    emit("setup_admin", status=201)
    return jsonify(ok=True), 201


@bp.post("/api/auth/logout")
def logout():
    emit("logout")
    session.clear()
    return jsonify(ok=True)


@bp.get("/api/auth/me")
def me():
    user = current_user()
    return jsonify(user=users.public(user, compact=True), caps=capabilities(user["role"]))


@bp.post("/api/auth/password")
def password():
    body = request.get_json(silent=True) or {}
    user = current_user()
    if not users.verify(user, body.get("current_password")):
        return jsonify(error="كلمة المرور الحالية غير صحيحة.", code="wrong_password"), 400
    try:
        users.change_password(user["id"], body.get("new_password"), False)
    except users.UserError as exc:
        return jsonify(error=str(exc), code=exc.code), exc.status
    emit("password_changed")
    return jsonify(ok=True)

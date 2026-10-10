"""إدارة الحسابات — متاحة للمدير فقط من الحارس المركزي."""
from flask import Blueprint, jsonify, request

from ..auth import current_user
from ..auth import users
from ..auth.audit_log import emit
from ..auth.roles import ROLE_LABELS

bp = Blueprint("users", __name__)


def _failed(exc):
    return jsonify(error=str(exc), code=exc.code), exc.status


@bp.get("/api/users")
def list_users():
    return jsonify(users=[users.public(u) for u in users.all_users()])


@bp.post("/api/users")
def create_user():
    body = request.get_json(silent=True) or {}
    try:
        user = users.create(body.get("username"), body.get("display_name"), body.get("role"),
                            body.get("password"), current_user()["username"])
    except users.UserError as exc:
        return _failed(exc)
    emit("user_created", status=201, target_username=user["username"],
         detail=f"بدور {ROLE_LABELS[user['role']]}")
    return jsonify(user=users.public(user)), 201


@bp.patch("/api/users/<user_id>")
def update_user(user_id):
    body = request.get_json(silent=True) or {}
    actor = current_user()
    values = {key: body[key] for key in ("display_name", "role", "active", "username", "password")
              if key in body}
    try:
        before, user = users.update(user_id, values, actor["id"], include_before=True)
    except users.UserError as exc:
        return _failed(exc)
    details = []
    if before and before.get("role") != user.get("role"):
        details.append(f"الدور: {ROLE_LABELS[before['role']]} ← {ROLE_LABELS[user['role']]}")
    if before and before.get("active") != user.get("active"):
        old = "نشط" if before.get("active") else "معطّل"
        new = "نشط" if user.get("active") else "معطّل"
        details.append(f"الحالة: {old} ← {new}")
    if before and before.get("display_name") != user.get("display_name"):
        details.append(f"الاسم الظاهر: {before['display_name']} ← {user['display_name']}")
    if before and before.get("username") != user.get("username"):
        details.append(f"تغيير اسم المستخدم: {before['username']} ← {user['username']}")
    if "password" in values:
        details.append("تغيير كلمة المرور")
    emit("user_updated", target_username=user["username"],
         detail="، ".join(details) or "بدون تغيير")
    if actor["id"] == user["id"]:
        from flask import session
        session["user_id"] = user["id"]
        session["session_version"] = int(user.get("session_version", 0))
        session.permanent = True
    return jsonify(user=users.public(user))


@bp.post("/api/users/<user_id>/reset-password")
def reset_password(user_id):
    body = request.get_json(silent=True) or {}
    actor = current_user()
    try:
        user = users.change_password(user_id, body.get("password"))
    except users.UserError as exc:
        return _failed(exc)
    emit("password_reset", target_username=user["username"], detail="تغيير كلمة المرور")
    if actor["id"] == user["id"]:
        from flask import session
        session["user_id"] = user["id"]
        session["session_version"] = int(user.get("session_version", 0))
        session.permanent = True
    return jsonify(ok=True)

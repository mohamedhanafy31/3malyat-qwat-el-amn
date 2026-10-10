"""مخزن الحسابات المنفصل عن بيانات التشغيل والنسخ الاحتياطية."""
import json
import os
import re
import threading
import uuid
from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

from backend import store
from .roles import ROLE_LABELS

LOCK = threading.Lock()
USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,32}$")


class UserError(ValueError):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.status = code, status


def path():
    return store.DATA_DIR / "users.json"


def _read_unlocked():
    try:
        raw = json.loads(path().read_text(encoding="utf-8"))
        return raw if isinstance(raw, list) else raw.get("users", [])
    except FileNotFoundError:
        return []


def _write_unlocked(rows):
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, target)


def all_users():
    with LOCK:
        return _read_unlocked()


def count():
    return len(all_users())


def by_id(user_id):
    return next((u for u in all_users() if u["id"] == user_id), None)


def by_username(username):
    key = str(username or "").strip().casefold()
    return next((u for u in all_users() if u["username"].casefold() == key), None)


def public(user, compact=False):
    keys = ("id", "username", "display_name", "role")
    out = {key: user.get(key) for key in keys}
    out["role_label"] = ROLE_LABELS.get(user.get("role"), user.get("role", ""))
    if not compact:
        for key in ("active", "created_at", "created_by", "last_login"):
            out[key] = user.get(key)
    return out


def _password_hash(password):
    if len(str(password or "")) < 8:
        raise UserError("weak_password", "كلمة المرور لازم تكون 8 حروف على الأقل.")
    return generate_password_hash(password, method="pbkdf2:sha256")


def create(username, display_name, role, password, created_by):
    username = str(username or "").strip()
    display_name = str(display_name or "").strip()
    if not USERNAME_RE.fullmatch(username):
        raise UserError("invalid_username", "اسم المستخدم لازم يكون من 3 إلى 32 حرف إنجليزي أو رقم أو ._-.")
    if not isinstance(role, str) or role not in ROLE_LABELS:
        raise UserError("invalid_role", "الدور غير صحيح.")
    password_hash = _password_hash(password)
    with LOCK:
        rows = _read_unlocked()
        if any(u["username"].casefold() == username.casefold() for u in rows):
            raise UserError("username_taken", "اسم المستخدم مستخدم بالفعل.", 409)
        now = datetime.now().isoformat(timespec="seconds")
        user = {"id": uuid.uuid4().hex, "username": username,
                "display_name": display_name or username, "role": role,
                "password_hash": password_hash, "active": True,
                "session_version": 0,
                "created_at": now, "created_by": created_by, "last_login": None}
        rows.append(user)
        _write_unlocked(rows)
        return user


def verify(user, password):
    return bool(user and user.get("active") and check_password_hash(user.get("password_hash", ""), password or ""))


def mark_login(user_id):
    return _mutate(user_id, lambda u: u.update(last_login=datetime.now().isoformat(timespec="seconds")))


def _mutate(user_id, operation):
    with LOCK:
        rows = _read_unlocked()
        user = next((u for u in rows if u["id"] == user_id), None)
        if not user:
            raise UserError("not_found", "الحساب غير موجود.", 404)
        operation(user)
        _write_unlocked(rows)
        return user


def update(user_id, values, actor_id, include_before=False):
    before = {}

    def apply(user):
        before.update(user)
        new_role = values.get("role", user["role"])
        if not isinstance(new_role, str) or new_role not in ROLE_LABELS:
            raise UserError("invalid_role", "الدور غير صحيح.")
        new_active = bool(values.get("active", user["active"]))
        if not new_active and user_id == actor_id:
            raise UserError("cannot_disable_self", "لا يمكن تعطيل حسابك الحالي.", 409)
        if user["role"] == "admin" and user["active"] and (new_role != "admin" or not new_active):
            admins = [u for u in _read_unlocked() if u["role"] == "admin" and u.get("active")]
            if len(admins) <= 1:
                raise UserError("last_admin", "لا يمكن تعطيل أو تخفيض آخر مدير نشط.", 409)
        if user_id == actor_id and user["role"] == "admin" and new_role != "admin":
            raise UserError("cannot_demote_self", "لا يمكن تخفيض دور حسابك الحالي.", 409)
        if "username" in values:
            username = str(values["username"] or "").strip()
            if not USERNAME_RE.fullmatch(username):
                raise UserError("invalid_username", "اسم المستخدم لازم يكون من 3 إلى 32 حرف إنجليزي أو رقم أو ._-.")
            if any(u["id"] != user_id and u["username"].casefold() == username.casefold()
                   for u in _read_unlocked()):
                raise UserError("username_taken", "اسم المستخدم مستخدم بالفعل.", 409)
            user["username"] = username
        if "password" in values:
            user["password_hash"] = _password_hash(values["password"])
        if "display_name" in values:
            user["display_name"] = str(values["display_name"] or "").strip() or user["username"]
        if "role" in values:
            user["role"] = new_role
        if "active" in values:
            user["active"] = new_active
        invalidating = (before.get("username") != user.get("username") or
                        before.get("password_hash") != user.get("password_hash") or
                        before.get("role") != user.get("role") or
                        before.get("active") != user.get("active"))
        if invalidating:
            user["session_version"] = int(user.get("session_version", 0)) + 1
    user = _mutate(user_id, apply)
    return (before, user) if include_before else user


def change_password(user_id, password):
    password_hash = _password_hash(password)

    def apply(user):
        user["password_hash"] = password_hash
        user["session_version"] = int(user.get("session_version", 0)) + 1

    return _mutate(user_id, apply)

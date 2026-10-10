"""كتابة وقراءة سجل النشاط الدوّار بصيغة JSON Lines."""
import base64
import hashlib
import json
import threading
from collections import OrderedDict
from datetime import datetime

from backend import store
from .labels import EVENT_LABELS, action_label
from .roles import ROLE_LABELS

_CACHE_MAX_FILES = 32
_FILE_CACHE = OrderedDict()
_CACHE_LOCK = threading.Lock()


def emit(event, status=200, username=None, **fields):
    from . import current_actor
    actor = current_actor()
    if username is not None:
        actor["username"] = username
    if event == "login_failed":
        # دي محاولة باسم الحساب المكتوب، مش عملية نفذها «النظام».
        actor.update(user_id=None, username=username, display_name=username or "—", role=None)
    try:
        from flask import request
        method, path = request.method, request.path
        actor["ip"] = request.remote_addr or actor.get("ip")
    except RuntimeError:
        method, path = fields.pop("method", None), fields.pop("path", None)
    row = {"ts": datetime.now().isoformat(timespec="seconds"), "event": event,
           "method": method, "path": path, **actor, "status": status}
    row.update(fields)
    row["edited_by"] = row.get("display_name") or "النظام"
    store._audit_logger.info(json.dumps(row, ensure_ascii=False))


def _files():
    base = store._LOG_DIR / "audit.log"
    found = [base] if base.exists() else []
    numbered = []
    for candidate in store._LOG_DIR.glob("audit.log.*") if store._LOG_DIR.exists() else ():
        try:
            numbered.append((int(candidate.name.rsplit(".", 1)[1]), candidate))
        except ValueError:
            continue
    return found + [p for _, p in sorted(numbered)]


def _account_action(event, target_username, detail, method, path):
    label = action_label(event, method, path)
    if event not in ("user_created", "user_updated", "password_reset") or not target_username:
        return label
    label += f" «{target_username}»"
    if detail:
        label += (" " if event == "user_created" else " — ") + detail
    return label


def _parse_file(target):
    rows = []
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
    for line_index, line in enumerate(lines):
        try:
            row = json.loads(line)
        except (ValueError, TypeError):
            continue
        event = row.get("event") or "write"
        username = row.get("username")
        display = row.get("display_name") or row.get("edited_by") or "—"
        target_username = row.get("target_username")
        detail = row.get("detail")
        ident = hashlib.sha256(f"{target}:{line_index}:{line}".encode()).hexdigest()[:20]
        rows.append({"id": ident, "ts": str(row.get("ts") or "")[:19], "event": event,
                     "event_label": EVENT_LABELS.get(event, event),
                     "action_label": _account_action(event, target_username, detail,
                                                     row.get("method"), row.get("path")),
                     "method": row.get("method"), "path": row.get("path"),
                     "username": username, "display_name": display,
                     "target_username": target_username, "detail": detail,
                     "role": row.get("role"), "role_label": ROLE_LABELS.get(row.get("role")),
                     "ip": row.get("ip"), "status": row.get("status")})
    return rows


def _cached_file(target):
    try:
        stat = target.stat()
    except OSError:
        return []
    key = (str(target), stat.st_mtime_ns, stat.st_size)
    with _CACHE_LOCK:
        cached = _FILE_CACHE.get(key)
        if cached is not None:
            _FILE_CACHE.move_to_end(key)
            return cached
    rows = _parse_file(target)
    with _CACHE_LOCK:
        _FILE_CACHE[key] = rows
        _FILE_CACHE.move_to_end(key)
        while len(_FILE_CACHE) > _CACHE_MAX_FILES:
            _FILE_CACHE.popitem(last=False)
    return rows


def _load():
    rows = []
    for target in _files():
        rows.extend(_cached_file(target))
    return sorted(rows, key=lambda r: (r["ts"], r["id"]), reverse=True)


def _encode(row):
    raw = json.dumps([row["ts"], row["id"]], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode(value):
    try:
        return tuple(json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))))
    except Exception:
        return None


def query(limit=100, before=None, user=None, event=None, from_day=None, to_day=None, q=None):
    rows = _load()
    usernames = sorted({r["username"] for r in rows if r.get("username")})
    cursor = _decode(before) if before else None
    if cursor:
        rows = [r for r in rows if (r["ts"], r["id"]) < cursor]
    if user:
        rows = [r for r in rows if (r.get("username") or "").casefold() == user.casefold()]
    if event:
        rows = [r for r in rows if r["event"] == event]
    if from_day:
        rows = [r for r in rows if r["ts"][:10] >= from_day]
    if to_day:
        rows = [r for r in rows if r["ts"][:10] <= to_day]
    if q:
        needle = q.casefold()
        rows = [r for r in rows if needle in " ".join(str(r.get(k) or "") for k in
                                                       ("username", "display_name", "target_username",
                                                        "detail", "path", "action_label")).casefold()]
    page = rows[:limit]
    return page, (_encode(page[-1]) if len(rows) > limit and page else None), usernames

"""كتابة وقراءة سجل النشاط الدوّار بصيغة JSON Lines."""
import base64
import hashlib
import json
import threading
from collections import Counter, OrderedDict, defaultdict
from datetime import date, datetime, timedelta

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
    except RuntimeError:
        method, path = fields.pop("method", None), fields.pop("path", None)
    actor.pop("ip", None)
    row = {"ts": datetime.now().isoformat(timespec="seconds"), "event": event,
           "action_label": _account_action(event, fields.get("target_username"),
                                             fields.get("detail"), method, path),
           **actor, "status": status}
    row.update(fields)
    # بيانات الشبكة ومسارات الـAPI لا تدخل سجل النشاط أو واجهته.
    for private_field in ("ip", "method", "path"):
        row.pop(private_field, None)
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
    if event == "login_failed" and detail:
        return f"{label} — {detail}"
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
                     "action_label": row.get("action_label") or _account_action(
                         event, target_username, detail, row.get("method"), row.get("path")),
                     "user_id": row.get("user_id"),
                     "username": username, "display_name": display,
                     "target_username": target_username, "detail": detail,
                     "role": row.get("role"), "role_label": ROLE_LABELS.get(row.get("role")),
                     "status": row.get("status")})
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
                                                        "detail", "action_label")).casefold()]
    # `user_id` مطلوب داخليًا للتجميع الموثوق بعد تغيير اسم المستخدم، لكنه
    # معرّف تخزين داخلي ولا حاجة لواجهة سجل النشاط أن تكشفه.
    page = [{key: value for key, value in row.items() if key != "user_id"}
            for row in rows[:limit]]
    return page, (_encode(page[-1]) if len(rows) > limit and page else None), usernames


_ACTIVE_GAP = timedelta(minutes=15)


def _as_datetime(value):
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _estimated_active_minutes(rows):
    """وقت نشاط تقريبي من الأحداث، مع سقف 15 دقيقة بين حدثين.

    السجل لا يراقب وجود المستخدم أمام الشاشة. لذلك لا نحسب مدة الجلسة كاملة؛
    كل فجوة نشاط تُحسب بحد أقصى 15 دقيقة، وتسجيل الخروج يقفل الجلسة.
    """
    total = timedelta()
    last = None
    session_open = False
    for row in sorted(rows, key=lambda item: item.get("ts") or ""):
        stamp = _as_datetime(row.get("ts"))
        if not stamp:
            continue
        if row.get("event") == "login_ok":
            last, session_open = stamp, True
            continue
        if not session_open:
            # سجلات قديمة قد تسبق إضافة حدث الدخول؛ أول نشاط موثّق يبدأ جلسة.
            last, session_open = stamp, True
        elif last is not None and stamp >= last:
            total += min(stamp - last, _ACTIVE_GAP)
            last = stamp
        if row.get("event") == "logout":
            session_open, last = False, None
    return round(total.total_seconds() / 60)


def _day_series(rows, from_day, to_day):
    start, end = date.fromisoformat(from_day), date.fromisoformat(to_day)
    changes, logins, active = Counter(), Counter(), defaultdict(set)
    for row in rows:
        day = row["ts"][:10]
        if row.get("event") == "write":
            changes[day] += 1
        if row.get("event") == "login_ok":
            logins[day] += 1
        if row.get("user_id") and row.get("event") != "login_failed":
            active[day].add(row["user_id"])
    days = []
    current = start
    while current <= end:
        key = current.isoformat()
        days.append({"day": key, "changes": changes[key], "logins": logins[key],
                     "active_members": len(active[key])})
        current += timedelta(days=1)
    return days


def activity_stats(from_day, to_day):
    """ملخص استخدام الحسابات في مدى محدد من سجل النشاط الدوّار."""
    from . import users

    rows = [row for row in _load() if from_day <= row["ts"][:10] <= to_day]
    accounts = users.all_users()
    by_user_id = defaultdict(list)
    failed_by_username = Counter()
    for row in rows:
        if row.get("event") == "login_failed":
            failed_by_username[(row.get("username") or "").casefold()] += 1
        elif row.get("user_id"):
            by_user_id[row["user_id"]].append(row)

    members = []
    for account in accounts:
        events = by_user_id.get(account["id"], [])
        writes = [row for row in events if row.get("event") == "write"]
        actions = Counter(row.get("action_label") or "تعديل بيانات" for row in writes)
        active_days = {row["ts"][:10] for row in events if row.get("ts")}
        last = max((row["ts"] for row in events), default=None)
        changes = len(writes)
        members.append({
            **users.public(account),
            "logins": sum(row.get("event") == "login_ok" for row in events),
            "changes": changes,
            "active_days": len(active_days),
            "changes_per_active_day": round(changes / len(active_days), 1) if active_days else 0,
            "estimated_active_minutes": _estimated_active_minutes(events),
            "last_activity": last,
            "denied_attempts": sum(row.get("event") == "access_denied" for row in events),
            "failed_logins": failed_by_username[account.get("username", "").casefold()],
            "top_action": actions.most_common(1)[0][0] if actions else None,
        })

    members.sort(key=lambda row: (-row["changes"], -row["logins"], row["display_name"]))
    hours = Counter()
    for row in rows:
        if row.get("user_id") and row.get("ts") and row.get("event") != "login_failed":
            try:
                hours[int(row["ts"][11:13])] += 1
            except (TypeError, ValueError):
                pass
    authenticated = [row for row in rows if row.get("user_id") and row.get("event") != "login_failed"]
    return {
        "date_from": from_day,
        "date_to": to_day,
        "estimate_idle_minutes": int(_ACTIVE_GAP.total_seconds() / 60),
        "summary": {
            "accounts": len(accounts),
            "active_members": sum(bool(by_user_id.get(account["id"])) for account in accounts),
            "logins": sum(row.get("event") == "login_ok" for row in authenticated),
            "changes": sum(row.get("event") == "write" for row in authenticated),
            "estimated_active_minutes": sum(member["estimated_active_minutes"] for member in members),
            "failed_logins": sum(row.get("event") == "login_failed" for row in rows),
        },
        "members": members,
        "daily": _day_series(rows, from_day, to_day),
        "by_hour": [{"hour": hour, "events": hours[hour]} for hour in range(24)],
        "coverage": {
            "first_activity": min((row["ts"] for row in rows), default=None),
            "last_activity": max((row["ts"] for row in rows), default=None),
        },
    }

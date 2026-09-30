"""الإعدادات والقوائم المرجعية المؤرَّخة."""
from copy import deepcopy
import re

from .constants import COMMAND_ROLES, GROUP_ROLES, TARGETS_FIRST, TARGET_NAMES


def _entry_on(entries, day):
    """آخر نسخة سارية، وأقدم نسخة للأيام السابقة لبداية السجل."""
    entries = [e for e in (entries or []) if isinstance(e, dict)]
    if not entries:
        return None
    applicable = [e for e in entries if (e.get("from") or "") <= day]
    return max(applicable or entries, key=lambda e: e.get("from") or "")


def command_on(data, day):
    entry = _entry_on(data.get("command_history"), day)
    source = (entry or {}).get("command") if entry else data.get("command")
    source = source or {}
    return {role: source.get(role) or None for role in COMMAND_ROLES}


def groups_on(data, day):
    entry = _entry_on(data.get("command_history"), day)
    source = (entry or {}).get("groups") if entry else data.get("command_groups")
    source = source or {}
    return {role: list(source.get(role) or []) for role in GROUP_ROLES}


def record_command_change(data, effective_from, *, command=None, groups=None):
    """يضيف/يستبدل نسخة القيادة، ويحدّث مرآة القيم الحالية."""
    history = data.setdefault("command_history", [])
    base_command = command_on(data, effective_from)
    base_groups = groups_on(data, effective_from)
    if not history:
        # أول تعديل لا يجعل الشاغل الجديد ظاهرًا في كل الأيام السابقة.
        days = [key for value in data.values() if isinstance(value, dict)
                for key in value if re.match(r"^\d{4}-\d{2}-\d{2}$", str(key))]
        start = min([effective_from, *days]) if days else effective_from
        history.append({"from": start, "command": deepcopy(base_command),
                        "groups": deepcopy(base_groups)})
    if command:
        base_command.update(command)
    if groups:
        base_groups.update({k: list(v or []) for k, v in groups.items()})
    row = next((e for e in history if e.get("from") == effective_from), None)
    value = {"from": effective_from, "command": base_command, "groups": base_groups}
    if row is None:
        history.append(value)
    else:
        row.clear()
        row.update(value)
    history.sort(key=lambda e: e.get("from") or "")
    newest = history[-1]
    data["command"] = deepcopy(newest["command"])
    data["command_groups"] = deepcopy(newest["groups"])


def _reference_on(data, key, day, default):
    entries = ((data.get("reference_lists") or {}).get(key) or [])
    row = _entry_on(entries, day)
    return deepcopy(row if row is not None else default)


def targets_on(data, day):
    row = _reference_on(data, "targets", day,
                        {"from": "", "names": [TARGETS_FIRST, *TARGET_NAMES]})
    return [str(v).strip() for v in row.get("names") or [] if str(v).strip()]


def afraad_basic_on(data, day):
    # استيراد محلي يمنع دورة بين المساعدات وبناء اليومية.
    from .afraad import BASIC_SERVICES

    entries = ((data.get("reference_lists") or {}).get("afraad_basic") or [])
    row = _reference_on(data, "afraad_basic", day, {"from": "", "items": BASIC_SERVICES})
    # الاسم المتكرر عبر النسخ يحتفظ بأول id؛ ملفات الأيام تخزن id لا الاسم.
    stable = {item["name"]: item["id"] for item in BASIC_SERVICES}
    for version in sorted(entries, key=lambda e: e.get("from") or ""):
        for item in version.get("items") or []:
            name, item_id = str(item.get("name") or "").strip(), str(item.get("id") or "").strip()
            if name and item_id:
                stable.setdefault(name, item_id)
    items = []
    for item in row.get("items") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        item_id = stable.get(name, str(item.get("id") or "").strip())
        if item_id and name:
            items.append({"id": item_id, "name": name})
    return items

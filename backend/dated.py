"""الإعدادات والقوائم المرجعية المؤرَّخة."""
from copy import deepcopy
import re

from .constants import COMMAND_ROLES, GROUP_ROLES, TARGETS_FIRST, TARGET_NAMES


MEDICAL_STATES = ("عمل", "راحة", "انتداب")


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


def medical_state_on(data, officer_id, day):
    """آخر حالة طبية سارية للضابط في اليوم؛ الافتراضي «عمل».

    السجل مؤرّخ في ``core.json`` بدل البحث للخلف في ملفات الأيام. كده قراءة
    يوم واحد بتراجع قائمة تغييرات صغيرة ومحمّلة أصلًا، ومابتفتحش تاريخ
    اليوميات كله عشان تورّث قيمة امبارح.
    """
    rows = [row for row in (data.get("officer_medical_states") or [])
            if isinstance(row, dict) and row.get("officer_id") == officer_id
            and (row.get("from") or "") <= day]
    row = max(rows, key=lambda item: item.get("from") or "", default=None)
    return {
        "state": (row or {}).get("state") or "عمل",
        "deputation_text": (row or {}).get("deputation_text") or "",
        "from": (row or {}).get("from") or "",
    }


def record_medical_state_change(data, officer_id, effective_from, state,
                                deputation_text=""):
    """يضيف/يستبدل اختيار الطبي الساري ابتداءً من يوم محدد."""
    history = data.setdefault("officer_medical_states", [])
    value = {"officer_id": officer_id, "from": effective_from, "state": state}
    if state == "انتداب" and deputation_text:
        value["deputation_text"] = deputation_text
    row = next((item for item in history
                if item.get("officer_id") == officer_id
                and item.get("from") == effective_from), None)
    if row is None:
        history.append(value)
    else:
        row.clear()
        row.update(value)
    history.sort(key=lambda item: (item.get("from") or "", item.get("officer_id") or ""))
    return value


def drop_medical_states(data, officer_id):
    """تنظيف سجل الطبي عند الحذف النهائي للضابط."""
    history = data.setdefault("officer_medical_states", [])
    kept = [row for row in history if row.get("officer_id") != officer_id]
    removed = len(history) - len(kept)
    history[:] = kept
    return removed


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


def record_afraad_basic_change(data, effective_from, items):
    """يسجل نسخة الخدمات الأساسية ابتداءً من يوم محدد."""
    lists = data.setdefault("reference_lists", {})
    history = lists.setdefault("afraad_basic", [])
    value = {"from": effective_from, "items": deepcopy(items)}
    row = next((entry for entry in history if entry.get("from") == effective_from), None)
    if row is None:
        history.append(value)
    else:
        row.clear(); row.update(value)
    history.sort(key=lambda entry: entry.get("from") or "")


def campaign_daily_on(data, day):
    entries = ((data.get("reference_lists") or {}).get("campaign_daily") or [])
    applicable = [entry for entry in entries if (entry.get("from") or "") <= day]
    row = max(applicable, key=lambda entry: entry.get("from") or "") if applicable else {"items": []}
    return [dict(item) for item in row.get("items") or []
            if isinstance(item, dict) and item.get("id") and str(item.get("name") or "").strip()]


def record_campaign_daily_change(data, effective_from, items):
    lists = data.setdefault("reference_lists", {})
    history = lists.setdefault("campaign_daily", [])
    value = {"from": effective_from, "items": deepcopy(items)}
    row = next((entry for entry in history if entry.get("from") == effective_from), None)
    if row is None:
        history.append(value)
    else:
        row.clear(); row.update(value)
    history.sort(key=lambda entry: entry.get("from") or "")


def campaign_posts_on(data, day):
    """الارتكازات السارية في يوم، مع الحفاظ على ترتيب النسخة المرجعية."""
    entries = ((data.get("reference_lists") or {}).get("campaign_posts") or [])
    applicable = [entry for entry in entries if (entry.get("from") or "") <= day]
    row = max(applicable, key=lambda entry: entry.get("from") or "") if applicable else {"items": []}
    return [dict(item) for item in row.get("items") or []
            if isinstance(item, dict) and item.get("id") and str(item.get("name") or "").strip()]


def record_campaign_posts_change(data, effective_from, items):
    """يسجل نسخة قائمة الارتكازات ابتداءً من يوم محدد."""
    lists = data.setdefault("reference_lists", {})
    history = lists.setdefault("campaign_posts", [])
    value = {"from": effective_from, "items": deepcopy(items)}
    row = next((entry for entry in history if entry.get("from") == effective_from), None)
    if row is None:
        history.append(value)
    else:
        row.clear(); row.update(value)
    history.sort(key=lambda entry: entry.get("from") or "")

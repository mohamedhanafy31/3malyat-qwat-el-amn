"""حل ربط أسماء الخدمات الحرة بهوية دليل الخدمات."""
from .service_catalog import catalog
from .text import core_service_name, norm

_ALIASES = {
    "قول مكبر": "القول المكبر", "الاسعاف": "الإسعاف", "ارتكاز الاسعاف": "الإسعاف",
    "التدخل سريع": "التدخل السريع", "تدخل سريع": "التدخل السريع",
    "مبنى المخابرات الحربية": "مبنى المخابرات", "استراحة القنصل السعودي": "استراحة القنصل",
    "اعلي كمين 109": "اعلى 109", "ارتكاز قسم فيصل الجديد": "ارتكاز قسم فيصل",
    "كول كورنيش": "قول الكورنيش", "قول كورنيش": "قول الكورنيش",
    "حملة أمن وطني 12ص": "حملة الأمن الوطني",
}


def _keys(name):
    raw = str(name or "")
    return norm(raw), norm(core_service_name(raw))


def resolve_service_id(data, name):
    by_name = {}
    for entry in catalog(data):
        for key in _keys(entry.get("name")):
            if key:
                by_name.setdefault(key, entry.get("id"))
    for key in _keys(name):
        if key in by_name:
            return by_name[key]
        alias = _ALIASES.get(key)
        if alias is None:
            alias = next((target for source, target in _ALIASES.items()
                          if key in _keys(source)), None)
        if alias:
            for alias_key in _keys(alias):
                if alias_key in by_name:
                    return by_name[alias_key]
    return None


def service_for_counts_entry(data, entry):
    stored = str((entry or {}).get("service_id") or "").strip()
    if stored and any(item.get("id") == stored for item in catalog(data)):
        return stored
    return resolve_service_id(data, (entry or {}).get("name"))

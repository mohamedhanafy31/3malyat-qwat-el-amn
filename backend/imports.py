"""علامة اليوم المستورد من الأرشيف."""


def import_info(data, day):
    """بيانات دفعة الاستيراد لليوم، أو None إن لم يكن مستوردًا."""
    info = (data.get("day_import") or {}).get(day)
    return info if isinstance(info, dict) and info else None


def is_imported(data, day):
    return import_info(data, day) is not None

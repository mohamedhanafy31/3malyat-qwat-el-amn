"""تحويل مواعيد الانتظام المكتوبة في الأرشيف إلى وقت منظم."""
import re

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_TIME = re.compile(r"(\d{1,2})(?:\s*[:.]\s*(\d{1,2}))?\s*(ص|ظ|م|ليل)?")


def _minutes(hour, minute, suffix):
    if not 0 <= minute <= 59 or not 0 <= hour <= 23:
        return None
    if suffix == "ليل":
        hour = hour % 12
    elif suffix in ("ص", "ظ"):
        hour = 12 if hour == 12 else hour % 12
    elif suffix == "م":
        hour = 0 if hour == 12 else hour % 12 + 12
    elif hour == 12:
        hour = 12
    elif 1 <= hour <= 6:
        hour += 12
    return hour * 60 + minute


def parse_time(text):
    """يرجع HH:MM. الرقم المجرد 1-6 مساءً، و7-11 صباحًا، و12 ظهرًا."""
    match = _TIME.search(str(text or "").translate(_DIGITS))
    if not match:
        return None
    total = _minutes(int(match.group(1)), int(match.group(2) or 0), match.group(3))
    return None if total is None else f"{total // 60:02d}:{total % 60:02d}"


def format_time(value):
    """صيغة الوورد: ص/ظ/م، و«12 ليل» لمنتصف الليل."""
    match = re.fullmatch(r"(\d{2}):(\d{2})", str(value or ""))
    if not match:
        raise ValueError("الوقت لازم يكون HH:MM")
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        raise ValueError("الوقت غير صحيح")
    if hour == 0:
        return "12 ليل" if minute == 0 else f"12:{minute:02d}ليل"
    if hour == 12:
        shown, suffix = 12, "ظ"
    elif hour < 12:
        shown, suffix = hour, "ص"
    else:
        shown, suffix = hour - 12, "م"
    return f"{shown if minute == 0 else f'{shown}:{minute:02d}'}{suffix}"


def parse_shift_pair(text):
    parts = [part.strip() for part in str(text or "").split("/")]
    return (parse_time(parts[0]) if parts and parts[0] else None,
            parse_time(parts[1]) if len(parts) > 1 and parts[1] else None)

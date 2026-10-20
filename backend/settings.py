"""قراءة وكتابة إعدادات بسيطة بجوار بيانات النظام."""

import json
import os


def _settings_path():
    """مسار الإعدادات وقت النداء.

    هذا يسمح للاختبارات بتغيير DATA_DIR بأمان.
    """
    from . import store

    return store.DATA_DIR / "settings.json"


def read_settings():
    """يقرأ الإعدادات.

    عند الغياب أو التلف يرجع قاموسًا فارغًا.
    """
    try:
        value = json.loads(_settings_path().read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def get_setting(key, default=None):
    """يرجع قيمة إعداد واحد مع قيمة افتراضية."""
    return read_settings().get(key, default)


def write_settings(values):
    """يكتب الإعدادات باستبدال ذري في نفس مجلد البيانات."""
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(dict(values), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)

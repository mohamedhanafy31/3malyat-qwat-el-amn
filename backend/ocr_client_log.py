"""أحداث مراحل قراءة اليومية من المتصفح (اختيار الملف، تحميل PDF، القص ...)
بتتسجّل في ocr.log بنفس ocr_session بتاع طلبات الخادم.

قائمة بيضاء صارمة: أسماء أحداث معروفة وحقول معروفة بأنواعها بس؛ أي حاجة تانية
بتتشال بصمت. قيم رقمية أو نصوص قصيرة محدودة الحروف — مفيش أسماء ملفات ولا محتوى."""
import logging
import re
import uuid

from . import tech_log

MAX_EVENTS = 20
MAX_BODY_BYTES = 8 * 1024
_SESSION_RE = re.compile(r"[A-Za-z0-9_-]{8,64}")
_SAFE_TEXT = re.compile(r"[^A-Za-z0-9_.:/+ -]")

# النوع: i = عدد صحيح، f = عشري، (قيم...) = قيم مسموحة، sN = نص قصير بطول أقصى N
EVENTS = {
    "file_selected": {"kind": ("image", "pdf"), "bytes": "i", "mime": "s40", "ext": "s5", "name_len": "i"},
    "pdf_loaded": {"pages": "i", "ms": "i"},
    "pdf_load_failed": {"error": "s60", "ms": "i"},
    "page_rendered": {"page": "i", "scale": "f", "width": "i", "height": "i", "ms": "i"},
    "crop_applied": {"x": "i", "y": "i", "w": "i", "h": "i"},
    "image_encoded": {"bytes": "i", "type": "s20", "width": "i", "height": "i", "ms": "i"},
    "upload_started": {"bytes": "i", "source": ("image", "pdf"), "page": "i"},
    "preview_received": {"rows": "i", "matched": "i", "status": "i", "ms": "i"},
    "preview_failed": {"status": "i", "code": "s40", "ms": "i"},
    "apply_sent": {"rows": "i"},
    "apply_result": {"status": "i", "applied": "i", "code": "s40", "ms": "i"},
    "cancelled": {"stage": "s20"},
}


def new_session():
    return uuid.uuid4().hex[:16]


def clean_session(value):
    value = str(value or "").strip()
    return value if _SESSION_RE.fullmatch(value) else ""


def _coerce(kind, value):
    if isinstance(value, bool):
        return None
    if kind == "i":
        if isinstance(value, (int, float)) and abs(value) < 10 ** 12:
            return int(value)
        return None
    if kind == "f":
        if isinstance(value, (int, float)) and abs(value) < 10 ** 6:
            return round(float(value), 3)
        return None
    if not isinstance(value, str):
        return None
    if isinstance(kind, tuple):
        return value if value in kind else None
    text = _SAFE_TEXT.sub("?", value)[:int(kind[1:])].strip()
    return text or None


def sanitize(events):
    """قائمة أحداث نظيفة [(name, fields)] — الأحداث/الحقول غير المعروفة بتتشال."""
    clean = []
    for item in events:
        spec = EVENTS.get(item.get("event")) if isinstance(item, dict) else None
        if spec is None:
            continue
        fields = {}
        for key, kind in spec.items():
            value = _coerce(kind, item.get(key))
            if value is not None:
                fields[key] = value
        clean.append((item["event"], fields))
    return clean


def log_events(events):
    for name, fields in events:
        tech_log.ocr_event(f"ocr.client.{name}", source="client", **fields)

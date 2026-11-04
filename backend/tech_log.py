"""السجلات الفنية (technical logs) — لتشخيص الأعطال، منفصلة عن سجل النشاط.

سجل النشاط (`backend/auth/audit_log.py`) بيجاوب «مين عمل إيه»؛ ده بيجاوب
«إيه اللي حصل جوه السيستم»: كل طلب (وقته وحالته)، الأخطاء بتتبّعها الكامل،
الحفظ والنسخ الاحتياطي، توليد الملفات اليومية، التصدير، الـOCR.

الملفات (في نفس مجلد سجل النشاط `store._LOG_DIR`، يعني `<PERSONNEL_DATA_DIR>/logs`):
  system.log  — كل شيء من مستوى LOG_LEVEL (الافتراضي INFO) فما فوق
  errors.log  — WARNING وأعلى فقط (نسخة مصغّرة لإرسالها للدعم)
  ocr.log     — قراءة اليومية من صورة/PDF فقط (logger باسم personnel.ocr)،
                وأحداثها بتفضل توصل system.log كمان

السطر:  <وقت ISO> | <مستوى> | <logger> | <رقم الطلب> | <المستخدم> | <الرسالة> | k=v ...
أي سطر لا يبدأ بتاريخ (تتبّع الاستثناء) تابع للسطر قبله.

قواعد لا تُكسر:
  - التسجيل ما يوقّعش التطبيق أبدًا (كل الأخطاء مبلوعة هنا).
  - ما يتسجّلش سرّ: كلمات مرور/توكن/كوكيز بتتحجب تلقائيًا بالاسم، وبنسجّل
    معرّفات وأعداد بس — مش أسماء ولا تليفونات ولا أجسام طلبات.
"""
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime
from logging.handlers import RotatingFileHandler

from flask import g, has_request_context, request

SYSTEM_LOG = "system.log"
ERRORS_LOG = "errors.log"
OCR_LOG = "ocr.log"
OCR_LOGGER = "personnel.ocr"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 10
DEFAULT_LEVEL = "INFO"
SLOW_REQUEST_MS = 1000

REQUEST_LOGGER = "personnel_system.request"
_TAG = "_personnel_tech_log"
_RECORD_START = re.compile(r"^\d{4}-\d{2}-\d{2}T")
_SECRET_KEY = re.compile(r"pass(word|wd)?|secret|token|cookie|authorization|session|api[_-]?key",
                         re.I)
_PUBLIC_KEYS = {"ocr_session"}       # معرّف عشوائي لتتبّع قراءة صورة — مش جلسة دخول
_RID_OK = re.compile(r"^[A-Za-z0-9._-]{6,64}$")
# حقول القياسية لـLogRecord — أي حاجة غيرها مش بتتطبع كـk=v
_FIELDS_ATTR = "tech_fields"


# ---------- التنسيق ----------

def _clean(value, limit=300):
    text = str(value)
    if len(text) > limit:
        text = text[:limit] + "…"
    return text.replace("\r", "\\r").replace("\n", "\\n")


def _format_value(value):
    text = _clean(value)
    if not text or any(ch in text for ch in ' ="'):
        return json.dumps(text, ensure_ascii=False)
    return text


def format_fields(fields):
    parts = []
    for key, value in (fields or {}).items():
        if value is None:
            continue
        secret = key not in _PUBLIC_KEYS and _SECRET_KEY.search(str(key))
        shown = "***" if secret else _format_value(value)
        parts.append(f"{key}={shown}")
    return " ".join(parts)


def current_request_id():
    if has_request_context():
        return getattr(g, "request_id", None)
    return None


def _current_username():
    if has_request_context():
        user = getattr(g, "auth_user", None)
        if user:
            return user.get("username")
    return None


class _ContextFilter(logging.Filter):
    """يحقن رقم الطلب والمستخدم في كل سجل (على الـhandler عشان يشمل كل الـloggers)."""

    def filter(self, record):
        try:
            record.request_id = current_request_id() or "-"
            record.tech_user = _current_username() or "-"
        except Exception:
            record.request_id = record.tech_user = "-"
        return True


class TechFormatter(logging.Formatter):
    def format(self, record):
        try:
            stamp = datetime.fromtimestamp(record.created).isoformat(timespec="milliseconds")
            message = _clean(record.getMessage(), 2000)
            fields = format_fields(getattr(record, _FIELDS_ATTR, None))
            line = (f"{stamp} | {record.levelname} | {record.name} | "
                    f"{getattr(record, 'request_id', '-')} | "
                    f"{getattr(record, 'tech_user', '-')} | {message}")
            if fields:
                line += " | " + fields
            if record.exc_info:
                line += "\n" + self.formatException(record.exc_info)
            return line
        except Exception:
            return f"{datetime.now().isoformat(timespec='milliseconds')} | ERROR | tech_log | - | - | تعذّر تنسيق سجل"


# ---------- الـhandler ----------

class SafeRotatingFileHandler(RotatingFileHandler):
    """تدوير بالحجم، وما بيرميش أبدًا.

    - `delay=True`: الملف ما يتفتحش إلا لما يتكتب فيه فعلًا (الاختبارات ما تلمسش القرص).
    - على ويندوز لو الملف ماسوك (مثلًا مفتوح في برنامج تاني) فالتدوير بيفشل بـ
      PermissionError؛ بنكمّل الكتابة في نفس الملف بدل ما نضيّع السطر أو نوقّع.
    """

    def __init__(self, path):
        super().__init__(path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT,
                         encoding="utf-8", delay=True)

    def doRollover(self):
        try:
            super().doRollover()
        except OSError:
            if self.stream is None:
                try:
                    self.stream = self._open()
                except OSError:
                    pass

    def emit(self, record):
        try:
            super().emit(record)
        except Exception:
            pass

    def handleError(self, record):          # noqa: D401 — التسجيل ما يوقّعش التطبيق
        pass


# ---------- الإعداد ----------

def _settings_level():
    try:
        from .settings import get_setting
        return get_setting("log_level")
    except Exception:
        return None


def resolve_level(explicit=None):
    """LOG_LEVEL (بيئة) ثم إعداد `log_level` في settings.json ثم INFO."""
    for candidate in (explicit, os.environ.get("LOG_LEVEL"), _settings_level()):
        if isinstance(candidate, int):
            return candidate
        name = str(candidate or "").strip().upper()
        value = logging.getLevelName(name) if name else None
        if isinstance(value, int):
            return value
    return logging.INFO


def log_dir():
    from . import store
    return store._LOG_DIR


def _remove_ours(root):
    for handler in list(root.handlers):
        if getattr(handler, _TAG, False):
            root.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass


def shutdown_logging():
    _remove_ours(logging.getLogger())
    _remove_ours(logging.getLogger(OCR_LOGGER))


def setup_logging(directory=None, level=None, console=False):
    """يركّب handlers النظام على الـroot logger. آمن للاستدعاء أكتر من مرة
    (بيشيل بتوعه القديمة الأول) فمفيش تكرار أسطر ولا تسريب ملفات."""
    root = logging.getLogger()
    _remove_ours(root)
    _remove_ours(logging.getLogger(OCR_LOGGER))
    try:
        target = os.fspath(directory if directory is not None else log_dir())
        resolved = resolve_level(level)
        try:
            os.makedirs(target, exist_ok=True)
        except OSError:
            pass
        formatter = TechFormatter()
        context = _ContextFilter()
        handlers = []
        system = SafeRotatingFileHandler(os.path.join(target, SYSTEM_LOG))
        system.setLevel(resolved)
        errors = SafeRotatingFileHandler(os.path.join(target, ERRORS_LOG))
        errors.setLevel(max(logging.WARNING, resolved))
        handlers += [system, errors]
        ocr = SafeRotatingFileHandler(os.path.join(target, OCR_LOG))
        ocr.setLevel(resolved)
        ocr.setFormatter(formatter)
        ocr.addFilter(context)
        setattr(ocr, _TAG, True)
        logging.getLogger(OCR_LOGGER).addHandler(ocr)       # + يكمّل لـroot (system/errors)
        if console:
            import sys
            if sys.stderr is not None:
                stream = logging.StreamHandler(sys.stderr)
                stream.setLevel(resolved)
                handlers.append(stream)
        for handler in handlers:
            handler.setFormatter(formatter)
            handler.addFilter(context)
            setattr(handler, _TAG, True)
            root.addHandler(handler)
        if root.level == logging.NOTSET or root.level > resolved:
            root.setLevel(resolved)
        # مكتبات صاخبة
        logging.getLogger("werkzeug").setLevel(logging.WARNING)
        logging.getLogger("PIL").setLevel(logging.WARNING)
        return {"dir": target, "level": logging.getLevelName(resolved)}
    except Exception:
        return {"dir": None, "level": None}


# ---------- أحداث منظّمة ----------

def event(logger, message, level=logging.INFO, exc_info=None, **fields):
    """سطر بمفاتيح منظّمة: event(LOG, "store.save", duration_ms=12, files=2)."""
    try:
        if isinstance(logger, str):
            logger = logging.getLogger(logger)
        if logger.isEnabledFor(level):
            logger.log(level, message, exc_info=exc_info, extra={_FIELDS_ATTR: fields})
    except Exception:
        pass


def ocr_event(message, level=logging.INFO, exc_info=None, **fields):
    """حدث في ocr.log: بيضيف ocr_session واليوم تلقائيًا من الطلب الحالي.
    معرّفات وأرقام بس — ممنوع أسماء أفراد أو أسماء/محتوى ملفات."""
    try:
        if has_request_context():
            fields.setdefault("ocr_session", getattr(g, "ocr_session", None))
            fields.setdefault("day", getattr(g, "ocr_day", None))
        fields = {"ocr_session": fields.pop("ocr_session", None),
                  "day": fields.pop("day", None), **fields}
        event(OCR_LOGGER, message, level=level, exc_info=exc_info, **fields)
    except Exception:
        pass


def ocr_stage(name):
    """يحدد المرحلة الجارية (للربط مع أي استثناء يتسجّل بعدها)."""
    try:
        if has_request_context():
            g.ocr_stage = name
    except Exception:
        pass


def ms_since(started):
    return round((time.perf_counter() - started) * 1000, 1)


def log_startup(app=None, source="app"):
    """سطر بدء التشغيل: النسخة وبايثون والنظام ومجلد البيانات وملخص الإعدادات."""
    import platform
    import sys
    try:
        from . import store
        from .settings import read_settings
        settings = read_settings()
        summary = ",".join(f"{k}={settings[k]}" for k in sorted(settings)
                           if isinstance(settings[k], (bool, int, float))
                           or k == "log_level")
        event(logging.getLogger("personnel_system.startup"), "server_start",
              source=source, schema=store.SCHEMA_VERSION,
              python=platform.python_version(), platform=platform.platform(),
              data_dir=str(store.DATA_DIR), log_dir=str(store._LOG_DIR),
              log_level=logging.getLevelName(logging.getLogger().level),
              settings=summary or None, pid=os.getpid())
    except Exception:
        pass


# ---------- وسيط الطلبات ----------

def _incoming_request_id():
    supplied = request.headers.get("X-Request-Id", "")
    return supplied if _RID_OK.match(supplied) else uuid.uuid4().hex[:12]


def _log_request(status, size):
    try:
        started = getattr(g, "_tech_started", None)
        duration = ms_since(started) if started is not None else None
        path = request.path
        is_static = path.startswith("/static/")
        slow = duration is not None and duration > SLOW_REQUEST_MS
        if status >= 500:
            level = logging.ERROR
        elif slow:
            level = logging.WARNING
        elif is_static and status < 400:
            level = logging.DEBUG       # ملفات ثابتة: ما نغرقش السجل
        else:
            level = logging.INFO
        event(REQUEST_LOGGER, f"{request.method} {path} {status}", level=level,
              method=request.method, path=path, status=status, duration_ms=duration,
              size=size, slow=True if slow else None)
        g._tech_logged = True
    except Exception:
        pass


def init_app(app):
    """لازم تتنادى قبل تسجيل باقي الـbefore_request (عشان رقم الطلب يكون جاهز
    حتى لرفض الدخول) وقبل ضغط الاستجابة (after_request بيشتغل بالعكس: ده آخرهم
    فالحجم المسجّل هو الحجم الفعلي المُرسَل)."""

    @app.before_request
    def _begin_request():
        g.request_id = _incoming_request_id()
        g._tech_started = time.perf_counter()

    @app.after_request
    def _end_request(response):
        try:
            response.headers["X-Request-Id"] = getattr(g, "request_id", "-")
            _log_request(response.status_code, response.content_length)
            _log_export(response)
        except Exception:
            pass
        return response

    @app.teardown_request
    def _teardown_request(exc):
        # استثناء اتقذف لبرّه (وضع الاختبار / فشل قبل after_request)
        if exc is not None and not getattr(g, "_tech_logged", False):
            _log_request(500, None)


def _log_export(response):
    path = request.path
    if "/export" not in path or request.method != "GET":
        return
    disposition = response.headers.get("Content-Disposition", "")
    if response.status_code == 200 and "attachment" in disposition:
        args = request.view_args or {}
        event("personnel_system.export", "export_ok", kind=request.endpoint,
              day=args.get("day"), size=response.content_length)
    elif response.status_code >= 400:
        args = request.view_args or {}
        event("personnel_system.export", "export_failed", level=logging.WARNING,
              kind=request.endpoint, day=args.get("day"), status=response.status_code)


# ---------- قراءة السجلات (صفحة المشرف) ----------

LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
FILES = {"system": SYSTEM_LOG, "errors": ERRORS_LOG, "ocr": OCR_LOG}
_MAX_SCAN_BYTES = 8 * 1024 * 1024


def read_tail(name, lines=300, min_level=None, query=None):
    """آخر `lines` سجل من ملف السجل (السجل المتعدد الأسطر = وحدة واحدة)."""
    filename = FILES.get(name)
    if filename is None:
        raise ValueError("ملف سجل غير معروف.")
    path = log_dir() / filename
    result = {"file": filename, "records": [], "size": 0, "truncated": False}
    try:
        size = path.stat().st_size
        with open(path, "rb") as handle:
            start = max(0, size - _MAX_SCAN_BYTES)
            handle.seek(start)
            raw = handle.read()
    except OSError:
        return result
    result["size"] = size
    result["truncated"] = start > 0
    text = raw.decode("utf-8", errors="replace")
    records, current = [], None
    for line in text.splitlines():
        if _RECORD_START.match(line):
            current = [line]
            records.append(current)
        elif current is not None:
            current.append(line)
    floor = LEVELS.index(min_level) if min_level in LEVELS else 0
    needle = (query or "").strip().lower()
    picked = []
    for record in reversed(records):
        parts = record[0].split(" | ", 2)
        level = parts[1] if len(parts) > 1 else "INFO"
        if level in LEVELS and LEVELS.index(level) < floor:
            continue
        block = "\n".join(record)
        if needle and needle not in block.lower():
            continue
        picked.append(block)
        if len(picked) >= lines:
            break
    result["records"] = list(reversed(picked))
    return result


def list_log_files():
    """ملفات السجل الفنية الموجودة (الحالي + المُدوَّر) لتنزيلها."""
    directory = log_dir()
    found = []
    try:
        for path in sorted(directory.iterdir()):
            if path.is_file() and re.fullmatch(r"(system|errors|ocr)\.log(\.\d+)?", path.name):
                found.append(path)
    except OSError:
        pass
    return found

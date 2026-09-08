"""تخزين البيانات — ملف JSON واحد، بقفل خيط وكتابة ذرية (tmp file replace)."""
import json
import logging
import shutil
import threading
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import unquote

from flask import request

from .constants import DEFAULT_DATA

DATA_FILE = Path(__file__).resolve().parent.parent / "data.json"
LOCK = threading.Lock()

# نسخة بنية الملف. أي هجرة بتغيّر شكل البيانات بترفع الرقم ده، والتطبيق
# بيرفض يشتغل على ملف برقم مختلف بدل ما يقرأه غلط في صمت. الملفات القديمة
# اللي مافيهاش الحقل أصلًا بتتعامل كـ 1.
SCHEMA_VERSION = 3

# نسخ احتياطي دوّار: قبل كل كتابة بنحتفظ بالنسخة السابقة. ده أمان تشغيلي
# يومي كان ناقص — الكتابة الذرية بتحمي من ملف نصّه مقطوع، مش من تعديل غلط.
BACKUP_DIR_NAME = "backups"
BACKUP_KEEP = 20


def backup_dir():
    """جنب ملف البيانات الحالي — بيتحسب وقت النداء عشان الاختبارات اللي
    بتحوّل DATA_FILE لملف مؤقت ما تكتبش نسخها في مجلد المشروع الحقيقي."""
    return DATA_FILE.parent / BACKUP_DIR_NAME


class SchemaMismatch(RuntimeError):
    """ملف بيانات ببنية مختلفة عن اللي الكود ده بيفهمها."""

# سجل تدقيق بسيط — مين عدّل ايه وامتى، بدون نظام حسابات أو تسجيل دخول. الاسم
# اختياري (حقل "اسمك" في الشريط العلوي)؛ لو فاضي بيتسجل null. الملف بيدور
# تلقائيًا (5 ميجا × 5 نسخ) عشان ما يكبرش من غير حد.
_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_audit_logger = logging.getLogger("personnel_system.audit")
_audit_logger.setLevel(logging.INFO)
if not _audit_logger.handlers:
    _audit_handler = RotatingFileHandler(_LOG_DIR / "audit.log", maxBytes=5 * 1024 * 1024,
                                          backupCount=5, encoding="utf-8")
    _audit_handler.setFormatter(logging.Formatter("%(message)s"))
    _audit_logger.addHandler(_audit_handler)
    _audit_logger.propagate = False


def _log_audit():
    try:
        # الفرونت إند بيبعت الاسم مشفّر (encodeURIComponent) لأن ترويسة HTTP
        # لازم تبقى ISO-8859-1 بس، والاسم هنا غالبًا عربي.
        edited_by = unquote(request.headers.get("X-Edited-By", "")).strip()
        _audit_logger.info(json.dumps({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "method": request.method,
            "path": request.path,
            "edited_by": edited_by or None,
        }, ensure_ascii=False))
    except RuntimeError:
        pass  # نداء بره سياق طلب HTTP (سكربت مستقبلي مثلًا) — تجاهل بهدوء


def _check_schema(data):
    """يتأكد إن الملف بنفس بنية الكود. الفرق بيتقفل بصوت عالي مش بالسكوت —
    قراءة ملف ببنية قديمة بالكود الجديد بتطلع أرقام غلط في اليوميات."""
    found = data.get("schema", 1)
    if found == SCHEMA_VERSION:
        return
    if found < SCHEMA_VERSION:
        raise SchemaMismatch(
            f"ملف البيانات ببنية {found} والكود بيتوقع {SCHEMA_VERSION}. "
            f"شغّل سكربتات الهجرة في migrations/ الأول (كل واحد بيعمل نسخة "
            f"احتياطية في {BACKUP_DIR_NAME}/ قبل ما يكتب)."
        )
    raise SchemaMismatch(
        f"ملف البيانات ببنية {found} أحدث من الكود ({SCHEMA_VERSION}). "
        f"حدّث الكود أو ارجع لنسخة من {BACKUP_DIR_NAME}/."
    )


def _read():
    """قراءة الملف وتطبيع بنيته — من غير قفل، لاستخدامها جوه أي بلوك ماسك الـ LOCK بالفعل."""
    if not DATA_FILE.exists():
        _write(json.loads(json.dumps(DEFAULT_DATA)))   # نسخة — _write بيختم الحقل schema
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return json.loads(json.dumps(DEFAULT_DATA))
    _check_schema(data)
    for cat in ("officers", "personnel"):
        data.setdefault(cat, {"active": [], "archive": []})
        data[cat].setdefault("active", [])
        data[cat].setdefault("archive", [])
    data.setdefault("leaves", [])
    data.setdefault("services", [])
    data.setdefault("day_assignments", {})
    data.setdefault("day_officers", {})
    data.setdefault("service_tags", [])
    command = data.setdefault("command", {})
    for role in DEFAULT_DATA["command"]:
        command.setdefault(role, None)
    data.setdefault("medical_officers", [])
    return data


def _snapshot():
    """نسخة من الملف الحالي قبل ما يتكتب فوقه، مع تنضيف الأقدم."""
    if not DATA_FILE.exists():
        return
    try:
        target = backup_dir()
        target.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        shutil.copy2(DATA_FILE, target / f"data-{stamp}.json")
        for f in sorted(target.glob("data-*.json"))[:-BACKUP_KEEP]:
            f.unlink(missing_ok=True)
    except OSError:
        pass          # النسخ الاحتياطي أمان إضافي — فشله ما يمنعش الحفظ


def _write(data):
    _snapshot()
    data["schema"] = SCHEMA_VERSION
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(DATA_FILE)


def load_data():
    """لقطة قراءة واحدة — تُستخدم في نقاط الـ GET اللي مالهاش أي تعديل على البيانات."""
    with LOCK:
        return _read()


def save_data(data):
    """حفظ مباشر بقفل خاص بيه. لو بتعدّل بيانات محمّلة برّه with_data() فالمفروض
    تستخدم with_data() بدالها عشان تضمن إن حد تاني ما يقرأش/يكتبش في النص."""
    with LOCK:
        _write(data)


class AbortRequest(Exception):
    """يتقذف من جوه دالة with_data() للرجوع بخطأ من غير ما يتحفظ أي تعديل."""
    def __init__(self, response):
        self.response = response


def with_data(fn):
    """يشغّل fn(data) تحت نفس القفل من التحميل للحفظ كوحدة واحدة ذرية — بيمنع
    فقد تعديل لو جه طلبين في نفس الوقت (كل الوقت السابق كان القفل بيحمي القراءة
    بس، فطلبين ممكن كل واحد يحمّل نسخة، يعدّل، والتاني يمسح تعديل الأول من غير
    قصد). fn بتعدّل data في مكانها وترجّع قيمة استجابة Flask؛ الحفظ بيحصل بس لو
    fn رجعت عادي — ارمي AbortRequest(response) من جواها للرجوع بخطأ من غير حفظ."""
    with LOCK:
        data = _read()
        try:
            result = fn(data)
        except AbortRequest as exc:
            return exc.response
        _write(data)
        _log_audit()
        return result


def next_id(items, prefix, width=3):
    nums = [int(x["id"].split("-")[-1]) for x in items
            if str(x.get("id", "")).startswith(prefix + "-") and x["id"].split("-")[-1].isdigit()]
    return f"{prefix}-{(max(nums) + 1) if nums else 1:0{width}d}"

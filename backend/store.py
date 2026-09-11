"""تخزين البيانات — ملف JSON واحد، بقفل خيط وكتابة ذرية (tmp file replace)."""
import gzip
import json
import logging
import os
import shutil
import threading
import zlib
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import unquote

from flask import request

from .constants import DEFAULT_DATA
from .utils import sort_active

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


class DataUnreadable(SchemaMismatch):
    """الملف موجود بس مش متقري — JSON مقطوع أو تالف أو صلاحيات ناقصة.

    بيرث من SchemaMismatch عشان يتمسك بنفس معالج الخطأ في app.py ويرجّع 503.
    """

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
    # ملف تالف **مايرجّعش** DEFAULT_DATA. الرجوع بقاعدة فاضية كان بيخلي
    # الأعطال دي تعدّي في صمت (الصفحات بتعرض صفر ضباط وكأن القوة اتفضّت)،
    # وأول عملية حفظ بعدها بتكتب الفاضي ده فوق الملف الحقيقي = ضياع كامل
    # للبيانات. ملف مقطوع من قطع كهربا لازم يوقف الدنيا بصوت عالي زي
    # اختلاف الـschema بالظبط، والنسخ في backups/ هي طريق الرجوع.
    try:
        raw = DATA_FILE.read_text(encoding="utf-8")
    except OSError as exc:
        raise DataUnreadable(
            f"تعذّرت قراءة ملف البيانات ({exc}). اتأكد من الصلاحيات، "
            f"أو ارجع لنسخة من {BACKUP_DIR_NAME}/."
        ) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DataUnreadable(
            f"ملف البيانات تالف وما اتقراش (سطر {exc.lineno}، عمود {exc.colno}). "
            f"ما اتكتبش عليه أي حاجة — ارجع لأحدث نسخة سليمة من {BACKUP_DIR_NAME}/."
        ) from exc
    if not isinstance(data, dict):
        raise DataUnreadable(
            f"ملف البيانات مش بالشكل المتوقع (لقى {type(data).__name__} بدل كائن). "
            f"ارجع لنسخة من {BACKUP_DIR_NAME}/."
        )
    _check_schema(data)
    for cat in ("officers", "personnel"):
        data.setdefault(cat, {"active": [], "archive": []})
        data[cat].setdefault("active", [])
        data[cat].setdefault("archive", [])
        sort_active(data, cat)
    data.setdefault("leaves", [])
    data.setdefault("services", [])
    data.setdefault("day_assignments", {})
    data.setdefault("day_officers", {})
    data.setdefault("service_tags", [])
    data.setdefault("courses", [])
    data.setdefault("course_terms", [])
    command = data.setdefault("command", {})
    for role in DEFAULT_DATA["command"]:
        command.setdefault(role, None)
    data.setdefault("medical_officers", [])
    data.setdefault("id_seq", {})      # عدّادات الأرقام — شوف reserve_id()
    return data


def _backup_files():
    """كل النسخ الاحتياطية مرتبة من الأقدم للأحدث.

    بترجّع الشكلين: `.json.gz` (الجديد) و`.json` (النسخ القديمة، ونسخ
    ما-قبل-الهجرة اللي migrations/ لسه بتكتبها بدون ضغط). ترتيب الاسم =
    ترتيب زمني لأن الطابع الزمني بعرض ثابت وفي أول الاسم.
    """
    target = backup_dir()
    if not target.exists():
        return []
    return sorted(
        [p for p in target.glob("data-*.json*") if p.suffix in (".json", ".gz")],
        key=lambda p: p.name)


def _snapshot():
    """نسخة مضغوطة من الملف الحالي قبل ما يتكتب فوقه، مع تنضيف الأقدم.

    الضغط بيوفّر ~97% من مساحة النسخ (2 ميجا -> ~70 كيلو للنسخة)، وده
    الفرق بين مجلد نسخ بيوصل مئات الميجات بعد سنتين وبين واحد بيفضل
    صغير. gzip من مكتبة بايثون القياسية — مفيش أي تثبيت ولا إنترنت.

    الملف الحيّ `data.json` **مابيتغيّرش شكله** — الضغط على النسخ بس.

    الكتابة بتتم على ملف `.part` وبعدين rename ذرّي، فلو الجهاز اتقفل في
    النص مايتسابش ملف نص-مضغوط شكله سليم في المجلد.
    """
    if not DATA_FILE.exists():
        return
    try:
        target = backup_dir()
        target.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        final = target / f"data-{stamp}.json.gz"
        part = final.with_suffix(".part")
        with open(DATA_FILE, "rb") as src, gzip.open(part, "wb", compresslevel=6) as dst:
            shutil.copyfileobj(src, dst)
        os.replace(part, final)                     # ذرّي على ويندوز و لينكس
        for f in _backup_files()[:-BACKUP_KEEP]:
            f.unlink(missing_ok=True)
    except OSError:
        pass          # النسخ الاحتياطي أمان إضافي — فشله ما يمنعش الحفظ


def read_backup(path):
    """محتوى نسخة احتياطية كـdict — بيفهم المضغوط والعادي.

    بيرمي DataUnreadable لو الملف ناقص أو متقطع أو مش JSON، عشان
    الاستعادة ما تكتبش نسخة تالفة فوق البيانات الشغالة.
    """
    path = Path(path)
    try:
        if path.suffix == ".gz":
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                raw = fh.read()
        else:
            raw = path.read_text(encoding="utf-8")
    except (OSError, EOFError, gzip.BadGzipFile, zlib.error) as exc:
        raise DataUnreadable(f"النسخة «{path.name}» تالفة أو غير مكتملة ({exc}).") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DataUnreadable(
            f"النسخة «{path.name}» مش JSON سليم (سطر {exc.lineno}).") from exc
    if not isinstance(data, dict):
        raise DataUnreadable(f"النسخة «{path.name}» مش بالشكل المتوقع.")
    return data


def backup_info(path):
    """سطر وصف لنسخة: الحجم، وهل هي سليمة، وكام سجل فيها."""
    path = Path(path)
    row = {"name": path.name, "size": path.stat().st_size,
           "compressed": path.suffix == ".gz", "ok": False, "error": None,
           "schema": None, "officers": None, "leaves": None}
    try:
        data = read_backup(path)
        row.update(ok=True, schema=data.get("schema"),
                   officers=len(data.get("officers", {}).get("active", [])),
                   leaves=len(data.get("leaves", [])))
    except DataUnreadable as exc:
        row["error"] = str(exc)
    return row


def list_backups():
    """كل النسخ من الأحدث للأقدم، مع حالة كل واحدة."""
    return [backup_info(p) for p in reversed(_backup_files())]


def restore_backup(name):
    """يرجّع نسخة احتياطية فوق data.json.

    بيتحقق إن النسخة تتقري وتتفهم **قبل** ما يلمس البيانات الشغالة، وبياخد
    لقطة من الوضع الحالي الأول عشان الاستعادة نفسها تبقى قابلة للتراجع.
    """
    path = backup_dir() / name
    if not path.exists():
        raise DataUnreadable(f"مافيش نسخة بالاسم «{name}».")
    data = read_backup(path)              # بيرمي قبل أي كتابة لو تالفة
    _check_schema(data)                   # ومش بنرجّع بنية الكود مايفهمهاش
    with LOCK:
        _snapshot()                       # لقطة للوضع الحالي قبل الاستبدال
        tmp = DATA_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, DATA_FILE)
    return data


def _write(data):
    _snapshot()
    data["schema"] = SCHEMA_VERSION
    # المفاتيح اللي بادئة بـ"_" فهارس مؤقتة بتتبني أثناء الطلب (زي فهرس
    # الراحات) — مالهاش لزمة تتخزن ولا تكبّر الملف
    payload = {k: v for k, v in data.items() if not k.startswith("_")}
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
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
    """أعلى رقم موجود + 1 — للأرقام المحلية اللي نطاقها قايمة واحدة.

    مناسبة لتكليفات اليوم (AS-xxxx) لأن العدّ بيبدأ من أول كل يوم، فإعادة
    استخدام رقم اتمسح في نفس اليوم مالهاش أثر برّه اليوم ده. أي كيان
    عمره أطول من كده لازم يستخدم reserve_id().
    """
    return f"{prefix}-{_max_num(items, prefix) + 1:0{width}d}"


def _max_num(items, prefix):
    nums = [int(x["id"].split("-")[-1]) for x in items
            if str(x.get("id", "")).startswith(prefix + "-") and x["id"].split("-")[-1].isdigit()]
    return max(nums) if nums else 0


def reserve_id(data, prefix, existing, width=3):
    """رقم جديد مايتكررش أبدًا، حتى بعد مسح اللي قبله.

    `next_id` بتحسب max+1 من الموجود، فمسح آخر سجل بيخلي اللي بعده ياخد
    نفس الرقم بالظبط — والرقم ده ممكن يكون متسجّل في audit.log أو مكتوب
    في ورق أو متبعت لحد. العدّاد هنا بيتخزّن في الملف وبيزيد بس.

    بياخد `max` بين العدّاد والموجود فعلًا، فبيصلّح نفسه لوحده على أي ملف
    قديم مافيهوش `id_seq` — مفيش هجرة مطلوبة.
    """
    seq = data.setdefault("id_seq", {})
    nxt = max(int(seq.get(prefix, 0)), _max_num(existing, prefix)) + 1
    seq[prefix] = nxt
    return f"{prefix}-{nxt:0{width}d}"

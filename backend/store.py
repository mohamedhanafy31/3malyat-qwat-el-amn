"""تخزين البيانات — مجلد `data/`، ملف لكل يوم وملف واحد للقوة.

## ليه مجلد مش ملف واحد

كان كله ملف واحد `data.json`. تعديل خانة واحدة في اليومية التفصيلية كان
بيقرا الملف كله، يسلسله كله، يكتبه كله، وياخد منه نسخة مضغوطة كمان —
أكتر من 2 ميجابايت شغل عشان تغيير 40 حرف. والملف بيكبر مع كل يوم شغل
جديد (101 يوم = 64% من الملف)، يعني التكلفة دي بتزيد للأبد.

دلوقتي:

    data/
      core.json                        القوة والراحات والفرق — بتتغيّر نادرًا
      days/2026/09/2026-09-05.json     تكليفات اليوم وحالات ضباطه وتأكيده وقفله

تعديل خانة = كتابة ملف اليوم بس (~10 كيلو). تعديل بيانات ضابط = كتابة
`core.json` بس. **الملفات اللي ما اتغيّرتش ما بتتلمسش خالص** — المقارنة
ببصمة sha256 للمحتوى المسلسل، فمفيش كتابة على قرص من غير تغيير حقيقي.

## الشكل في الذاكرة ما اتغيّرش

`_read()` بتفكّ الملفات وترجّع **نفس** الـdict اللي كان بيترجّع من الملف
الواحد بالظبط: `data["day_assignments"][day]` و`data["officers"]` وكده.
ده مقصود — ولا مسار ولا مستودع ولا نموذج اتغيّر عشان التقسيم ده. التقسيم
تفصيلة تخزين، مش شكل بيانات.

## النسخ الاحتياطية

النسخة لسه **ملف واحد مضغوط** فيه كل حاجة مجمّعة (`data-<وقت>.json.gz`)،
عشان الاستعادة تفضل «ارجع للحظة دي» مش «ركّب مية ملف». اللي اتغيّر إن
النسخة مابقتش بتتاخد مع **كل** كتابة — دي كانت نص المشكلة. القاعدة:

  * أي تغيير في `core.json` (قوة، راحات، فرق) -> نسخة فورًا. دي البيانات
    اللي مالهاش مصدر تاني تترجع منه.
  * تغيير في أيام بس -> نسخة كل `BACKUP_MIN_GAP` ثانية على الأكثر.
    اليوميات ليها سجل تغييرات (`change_log`) بيوثّق كل تأكيد، فاللي ممكن
    يضيع بين نسختين موصوف في السجل.
"""
import gzip
import hashlib
import json
import logging
import os
import threading
import time
import zlib
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import unquote

from flask import request

from .constants import DEFAULT_DATA
from .repo.people import as_roster
from .utils import sort_active

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
LOCK = threading.Lock()

CORE_NAME = "core.json"
DAYS_NAME = "days"

# نسخة بنية البيانات. أي هجرة بتغيّر الشكل بترفع الرقم ده، والتطبيق بيرفض
# يشتغل على بيانات برقم مختلف بدل ما يقرأها غلط في صمت.
SCHEMA_VERSION = 6

BACKUP_DIR_NAME = "backups"
BACKUP_KEEP = 20
BACKUP_MIN_GAP = 120        # ثانية بين نسختين لما التغيير في الأيام بس

# مفاتيح مفهرسة باليوم -> اسمها جوّه ملف اليوم. ده التعريف الوحيد
# للتقسيم: أي مفتاح هنا بيتوزّع على ملفات الأيام، وأي مفتاح غيره بيروح
# لـ`core.json`.
DAY_SECTIONS = {
    "day_assignments": "assignments",
    "day_officers": "officer_states",
    "day_confirm": "confirm",
    "day_status": "status",
    "service_counts": "counts",
}


def core_file():
    return DATA_DIR / CORE_NAME


def days_dir():
    return DATA_DIR / DAYS_NAME


def day_path(day):
    """`data/days/2026/09/2026-09-05.json` — متشعّب بالسنة والشهر عشان
    مجلد واحد فيه آلاف الملفات تقيل في متصفح الملفات على ويندوز."""
    return days_dir() / day[:4] / day[5:7] / f"{day}.json"


def backup_dir():
    """جنب مجلد البيانات الحالي — بيتحسب وقت النداء عشان الاختبارات اللي
    بتحوّل DATA_DIR لمجلد مؤقت ما تكتبش نسخها في مجلد المشروع الحقيقي."""
    return DATA_DIR.parent / BACKUP_DIR_NAME


class SchemaMismatch(RuntimeError):
    """بيانات ببنية مختلفة عن اللي الكود ده بيفهمها."""


class DataUnreadable(SchemaMismatch):
    """الملف موجود بس مش متقري — JSON مقطوع أو تالف أو صلاحيات ناقصة.

    بيرث من SchemaMismatch عشان يتمسك بنفس معالج الخطأ في app.py ويرجّع 503.
    """

# سجل تدقيق بسيط — مين عدّل ايه وامتى، بدون نظام حسابات أو تسجيل دخول. الاسم
# اختياري (حقل "اسمك" في الشريط العلوي)؛ لو فاضي بيتسجل null. الملف بيدور
# تلقائيًا (5 ميجا × 5 نسخ) عشان ما يكبرش من غير حد.
_LOG_DIR = ROOT / "logs"
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


# ---------- أدوات الملفات ----------

def _dumps(value):
    return json.dumps(value, ensure_ascii=False, indent=2)


def _fingerprint(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_text(path):
    """قراءة ملف برسالة خطأ بتقول للمشغّل يعمل إيه."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DataUnreadable(
            f"تعذّرت قراءة «{path.name}» ({exc}). اتأكد من الصلاحيات، "
            f"أو ارجع لنسخة من {BACKUP_DIR_NAME}/."
        ) from exc


def _parse(raw, path):
    """تحليل JSON برسائل خطأ واضحة.

    ملف تالف **مايرجّعش فاضي**. الرجوع بقاعدة فاضية كان بيخلي الأعطال
    تعدّي في صمت (الصفحة بتعرض صفر ضباط وكأن القوة اتفضّت)، وأول حفظ
    بعدها بيكتب الفاضي ده فوق البيانات الحقيقية = ضياع كامل. ملف مقطوع
    من قطع كهربا لازم يوقف الدنيا بصوت عالي، والنسخ في backups/ هي طريق
    الرجوع.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DataUnreadable(
            f"الملف «{path.name}» تالف وما اتقراش (سطر {exc.lineno}، عمود {exc.colno}). "
            f"ما اتكتبش عليه أي حاجة — ارجع لأحدث نسخة سليمة من {BACKUP_DIR_NAME}/."
        ) from exc
    if not isinstance(data, dict):
        raise DataUnreadable(
            f"الملف «{path.name}» مش بالشكل المتوقع (لقى {type(data).__name__} بدل كائن). "
            f"ارجع لنسخة من {BACKUP_DIR_NAME}/."
        )
    return data


def _write_atomic(path, text):
    """كتابة ذرّية: ملف `.tmp` جنبه وبعدين استبدال — فلو الجهاز اتقفل في
    النص مايتسابش ملف نص-مكتوب مكان البيانات."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _check_schema(found):
    """يتأكد إن البيانات بنفس بنية الكود. الفرق بيتقفل بصوت عالي مش
    بالسكوت — قراءة بنية قديمة بالكود الجديد بتطلع أرقام غلط في اليوميات."""
    if found == SCHEMA_VERSION:
        return
    if found < SCHEMA_VERSION:
        raise SchemaMismatch(
            f"البيانات ببنية {found} والكود بيتوقع {SCHEMA_VERSION}. "
            f"شغّل سكربتات الهجرة في migrations/ الأول (كل واحد بيعمل نسخة "
            f"احتياطية في {BACKUP_DIR_NAME}/ قبل ما يكتب)."
        )
    raise SchemaMismatch(
        f"البيانات ببنية {found} أحدث من الكود ({SCHEMA_VERSION}). "
        f"حدّث الكود أو ارجع لنسخة من {BACKUP_DIR_NAME}/."
    )


# ---------- تفكيك وتجميع ----------

def all_day_files():
    """كل ملفات الأيام مرتبة بالتاريخ."""
    if not days_dir().exists():
        return []
    return sorted(days_dir().glob("*/*/*.json"), key=lambda p: p.stem)


def split(data):
    """-> (core, {يوم: محتوى ملفه}) — عكس `merge()` بالظبط.

    اليوم اللي كل أقسامه فاضية مابيتكتبش له ملف، و`_write` بيشيل ملفه
    القديم لو كان موجود.
    """
    core = {k: v for k, v in data.items()
            if not k.startswith("_") and k not in DAY_SECTIONS}
    days = {}
    for key, name in DAY_SECTIONS.items():
        for day, value in (data.get(key) or {}).items():
            if not value:
                continue
            days.setdefault(day, {})[name] = value
    return core, days


def merge(core, days):
    """core + ملفات الأيام -> نفس الشكل القديم في الذاكرة.

    القسم الفاضي بيتخطّى زي ما `split` بيتخطّاه، عشان الاتنين يفضلوا
    عكس بعض بالظبط مهما كان اللي على القرص (ملف اتكتب بالإيد مثلًا).
    """
    data = dict(core)
    for key in DAY_SECTIONS:
        data.setdefault(key, {})
    for day, blob in days.items():
        for key, name in DAY_SECTIONS.items():
            if blob.get(name):
                data[key][day] = blob[name]
    return data


# ---------- القراءة ----------

_cache = {}        # {path: (mtime_ns, size, text, fingerprint)}


def _cached(path):
    """-> (نص الملف، بصمته). بيتقرا من القرص بس لو اتغيّر.

    **النص** هو اللي بيتخزّن مش الكائن المتفكوك، وده مقصود لسببين:

      * كل قارئ محتاج كائن **مستقل** يعدّل فيه بحرية. لو الكاش بيدّي
        كائن مشترك كان لازم ننسخه نسخة عميقة في كل قراءة — وده كان
        أغلى (34 مللي) من تحليل النص من الأول (17)، لأن النسخ العميق
        بيسلسل ويحلّل، يعني مرورين بدل واحد.
      * البصمة بتتحسب مرة واحدة هنا مش في كل قراءة. حسابها لكل الأيام
        في كل طلب كان 21 مللي ثانية شغل مكرر.

    الكاش آمن لأن كل القراءات والكتابات تحت `LOCK` واحد.
    """
    stat = path.stat()
    key = str(path)
    hit = _cache.get(key)
    if hit and hit[0] == stat.st_mtime_ns and hit[1] == stat.st_size:
        return hit[2], hit[3]
    text = _read_text(path)
    entry = (stat.st_mtime_ns, stat.st_size, text, _fingerprint(text))
    _cache[key] = entry
    return entry[2], entry[3]


def _load_cached(path):
    """محتوى الملف متفكوك — كائن جديد في كل نداء."""
    return _parse(_cached(path)[0], path)


def _read():
    """قراءة المجلد وتطبيع بنيته — من غير قفل، لاستخدامها جوه أي بلوك
    ماسك الـLOCK بالفعل."""
    if not core_file().exists():
        if DATA_DIR.exists() and any(DATA_DIR.iterdir()):
            raise DataUnreadable(
                f"مجلد البيانات «{DATA_DIR.name}» موجود بس مافيهوش {CORE_NAME}. "
                f"ارجع لنسخة من {BACKUP_DIR_NAME}/."
            )
        legacy = ROOT / "data.json"
        if legacy.exists():
            raise SchemaMismatch(
                f"البيانات لسه في الملف الواحد القديم «{legacy.name}». "
                f"شغّل migrations/010_split_data_files.py عشان يفكّه لمجلد "
                f"«{DATA_DIR.name}/» (بيعمل نسخة احتياطية قبل ما يكتب)."
            )
        explode(json.loads(json.dumps(DEFAULT_DATA)))    # نسخة — explode بيعدّل

    core_text, core_fp = _cached(core_file())
    core = _parse(core_text, core_file())
    _check_schema(core.get("schema", 1))

    days, fingerprints = {}, {"core": core_fp}
    for path in all_day_files():
        text, stamp = _cached(path)
        days[path.stem] = _parse(text, path)
        fingerprints[path.stem] = stamp

    data = merge(core, days)

    for cat in ("officers", "personnel"):
        data[cat] = as_roster(data.get(cat))
        sort_active(data, cat)
    data.setdefault("leaves", [])
    data.setdefault("service_tags", [])
    data.setdefault("courses", [])
    data.setdefault("course_terms", [])
    command = data.setdefault("command", {})
    for role in DEFAULT_DATA["command"]:
        command.setdefault(role, None)
    data.setdefault("medical_officers", [])
    data.setdefault("id_seq", {})      # عدّادات الأرقام — شوف reserve_id()

    # بصمات اللي اتقرا — `_write` بيقارن بيها ويكتب اللي اتغيّر بس.
    # المفتاح بيبدأ بـ`_` فما بيتخزّنش (شوف `split`).
    data["_fp"] = fingerprints
    return data


# ---------- الكتابة ----------

def _write(data):
    """بيكتب اللي اتغيّر بس. بيرجّع (الملفات المكتوبة، الملفات المشالة).

    الترتيب مقصود: بنحسب الفرق الأول، بعدين ناخد النسخة الاحتياطية
    (وهي بتقرا القرص، يعني بتلقط الحالة **قبل** التعديل)، وبعدين نكتب.
    لو الكتابة سبقت النسخة كانت النسخة هتبقى صورة من الوضع الجديد —
    يعني مفيش رجوع أصلًا.
    """
    data["schema"] = SCHEMA_VERSION
    before = data.get("_fp") or {}
    core, days = split(data)

    core_text = _dumps(core)
    core_stamp = _fingerprint(core_text)
    core_changed = core_stamp != before.get("core")

    new_fp = {"core": core_stamp}
    pending = {}
    for day, blob in days.items():
        text = _dumps(blob)
        stamp = _fingerprint(text)
        new_fp[day] = stamp
        if stamp != before.get(day):
            pending[day] = text

    # يوم كان له ملف وبقى فاضي — الملف بيتشال عشان القرص يفضل مطابق
    # للذاكرة، وإلا اليوم الممسوح بيرجع لوحده في أول قراءة جاية.
    gone = [day for day in before if day != "core" and day not in new_fp]

    written = ([CORE_NAME] if core_changed else []) + [f"{d}.json" for d in pending]
    removed = [f"{d}.json" for d in gone]
    if written or removed:
        _snapshot(core_changed=core_changed)

    if core_changed:
        _write_atomic(core_file(), core_text)
    for day, text in pending.items():
        _write_atomic(day_path(day), text)
    for day in gone:
        day_path(day).unlink(missing_ok=True)

    data["_fp"] = new_fp
    return written, removed


def _last_backup_age():
    files = _backup_files()
    if not files:
        return None
    try:
        return time.time() - files[-1].stat().st_mtime
    except OSError:
        return None


def _snapshot(core_changed):
    """نسخة مضغوطة من كل البيانات مجمّعة، مع تنضيف الأقدم.

    الضغط بيوفّر ~97% من المساحة، وده الفرق بين مجلد نسخ بيوصل مئات
    الميجات بعد سنتين وبين واحد بيفضل صغير. gzip من مكتبة بايثون
    القياسية — مفيش أي تثبيت ولا إنترنت.

    مابتتاخدش مع كل كتابة (دي كانت نص مشكلة الأداء): تغيير في القوة أو
    الراحات بياخد نسخة فورًا لأنها بيانات مالهاش مصدر تاني، وتغيير في
    اليوميات بس بياخد نسخة كل `BACKUP_MIN_GAP` ثانية على الأكثر.
    """
    if not core_changed:
        age = _last_backup_age()
        if age is not None and age < BACKUP_MIN_GAP:
            return
    snapshot_now()


def snapshot_now():
    """نسخة كاملة دلوقتي مهما كان وقت آخر واحدة — للاستعادة والهجرات."""
    if not core_file().exists():
        return None
    try:
        target = backup_dir()
        target.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        final = target / f"data-{stamp}.json.gz"
        part = final.with_suffix(".part")
        with gzip.open(part, "wt", encoding="utf-8", compresslevel=6) as fh:
            fh.write(_dumps(assemble()))
        os.replace(part, final)                     # ذرّي على ويندوز و لينكس
        for f in _backup_files()[:-BACKUP_KEEP]:
            f.unlink(missing_ok=True)
        return final
    except OSError:
        return None    # النسخ الاحتياطي أمان إضافي — فشله ما يمنعش الحفظ


def assemble():
    """كل البيانات في dict واحد — للنسخ الاحتياطية وأدوات الفحص."""
    return merge(_load_cached(core_file()),
                 {p.stem: _load_cached(p) for p in all_day_files()})


def explode(data):
    """بيكتب dict كامل على المجلد — عكس `assemble()`.

    بيمسح ملفات الأيام اللي مش في الـdict عشان الاستعادة تبقى «رجّع
    للحظة دي» بالظبط، مش «دمج فوق اللي موجود».
    """
    data = dict(data)
    data.setdefault("schema", SCHEMA_VERSION)
    core, days = split(data)
    _write_atomic(core_file(), _dumps(core))
    for path in all_day_files():
        if path.stem not in days:
            path.unlink(missing_ok=True)
    for day, blob in days.items():
        _write_atomic(day_path(day), _dumps(blob))
    _cache.clear()


# ---------- النسخ الاحتياطية ----------

def _backup_files():
    """كل النسخ الاحتياطية مرتبة من الأقدم للأحدث.

    بترجّع الشكلين: `.json.gz` (المضغوط) و`.json` (النسخ القديمة، ونسخ
    ما-قبل-الهجرة اللي migrations/ لسه بتكتبها بدون ضغط). ترتيب الاسم =
    ترتيب زمني لأن الطابع الزمني بعرض ثابت وفي أول الاسم.
    """
    target = backup_dir()
    if not target.exists():
        return []
    return sorted(
        [p for p in target.glob("data-*.json*") if p.suffix in (".json", ".gz")],
        key=lambda p: p.name)


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
        # `as_roster` بيفهم شكل القوة القديم والجديد — النسخ الاحتياطية
        # القديمة لسه بالشكل المتداخل، والوصف ده لازم يشتغل عليها كمان
        # عشان المشغّل يقدر يقارن نسخة قبل ما يستعيدها.
        officers = [p for p in as_roster(data.get("officers"))
                    if (p.get("status") or "active") == "active"]
        row.update(ok=True, schema=data.get("schema"),
                   officers=len(officers),
                   leaves=len(data.get("leaves", [])))
    except DataUnreadable as exc:
        row["error"] = str(exc)
    return row


def list_backups():
    """كل النسخ من الأحدث للأقدم، مع حالة كل واحدة."""
    return [backup_info(p) for p in reversed(_backup_files())]


def restore_backup(name):
    """يرجّع نسخة احتياطية فوق مجلد البيانات.

    بيتحقق إن النسخة تتقري وتتفهم **قبل** ما يلمس البيانات الشغالة، وبياخد
    لقطة من الوضع الحالي الأول عشان الاستعادة نفسها تبقى قابلة للتراجع.
    """
    path = backup_dir() / name
    if not path.exists():
        raise DataUnreadable(f"مافيش نسخة بالاسم «{name}».")
    data = read_backup(path)              # بيرمي قبل أي كتابة لو تالفة
    _check_schema(data.get("schema", 1))  # ومش بنرجّع بنية الكود مايفهمهاش
    with LOCK:
        snapshot_now()                    # لقطة للوضع الحالي قبل الاستبدال
        explode(data)
    return data


# ---------- الواجهة ----------

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


# ---------- المعرّفات ----------

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

    بياخد `max` بين العدّاد والموجود فعلًا، فبيصلّح نفسه لوحده على أي بيانات
    قديمة مافيهاش `id_seq` — مفيش هجرة مطلوبة.
    """
    seq = data.setdefault("id_seq", {})
    nxt = max(int(seq.get(prefix, 0)), _max_num(existing, prefix)) + 1
    seq[prefix] = nxt
    return f"{prefix}-{nxt:0{width}d}"

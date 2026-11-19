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
import pickle
import re
import shutil
import threading
import time
import zlib
import zipfile
from collections import OrderedDict
from datetime import datetime
from logging.handlers import RotatingFileHandler
from collections.abc import MutableSequence
from pathlib import Path
from typing import NamedTuple

from . import tech_log
from .constants import DEFAULT_DATA, SECTION_OCCASIONAL
from .repo.people import as_roster
from .utils import sort_active

ROOT = Path(__file__).resolve().parent.parent


def _initial_data_dir():
    raw = os.environ.get("PERSONNEL_DATA_DIR", "").strip()
    if not raw:
        return ROOT / "data"
    path = Path(raw)
    if not path.is_absolute():
        raise RuntimeError("PERSONNEL_DATA_DIR must be an absolute path")
    return path


DATA_DIR = _initial_data_dir()
_ENV_DATA_DIR = DATA_DIR if os.environ.get("PERSONNEL_DATA_DIR", "").strip() else None
LOCK = threading.Lock()


class Changeset(NamedTuple):
    days: frozenset
    created_days: frozenset
    removed_days: frozenset
    core_keys: frozenset
    changed_sections: dict = {}


ALL_CORE_KEYS = frozenset({"*"})
_AFTER_COMMIT_HOOKS = []
_HOOKS_LOCK = threading.Lock()


def register_after_commit(fn):
    with _HOOKS_LOCK:
        if fn not in _AFTER_COMMIT_HOOKS:
            _AFTER_COMMIT_HOOKS.append(fn)


def clear_after_commit_hooks():
    with _HOOKS_LOCK:
        _AFTER_COMMIT_HOOKS.clear()


def _run_after_commit(changeset):
    with _HOOKS_LOCK:
        hooks = tuple(_AFTER_COMMIT_HOOKS)
    for hook in hooks:
        try:
            hook(changeset)
        except Exception:
            logging.getLogger(__name__).exception("after-commit hook failed")

CORE_NAME = "core.json"
CORE_DIR_NAME = "core"
DAYS_NAME = "days"
SOURCE_DOCS_NAME = "source_docs"

# نسخة بنية البيانات. أي هجرة بتغيّر الشكل بترفع الرقم ده، والتطبيق بيرفض
# يشتغل على بيانات برقم مختلف بدل ما يقرأها غلط في صمت.
SCHEMA_VERSION = 6

BACKUP_DIR_NAME = "backups"
BACKUP_KEEP = 20
BACKUP_MIN_GAP = 120        # ثانية بين نسختين لما التغيير في الأيام بس
BACKUP_STOP_TIMEOUT = 15    # أقصى انتظار لنسخة جارية وقت قفل السيرفر (بعدها الخيط daemon بيموت)

# مفاتيح مفهرسة باليوم -> اسمها جوّه ملف اليوم. ده التعريف الوحيد
# للتقسيم: أي مفتاح هنا بيتوزّع على ملفات الأيام، وأي مفتاح غيره بيروح
# لـ`core.json`.
DAY_SECTIONS = {
    "day_assignments": "assignments",
    "day_officers": "officer_states",
    "day_confirm": "confirm",
    "day_status": "status",
    "service_counts": "counts",
    # عدّاد أرقام التكليفات (AS-xxxx) لكل يوم — جوّه ملف اليوم نفسه عشان
    # ما يتوليدش نفس الرقم تاني بعد مسح آخر تكليف، من غير ما يلمس
    # core.json مع كل حفظ خانة (backend/assignments.py new_id).
    "day_assignment_seq": "assignment_seq",
    # يومية الأفراد — القائم بها والتليفون والانتظام لكل خدمة أساسية
    # (دليل الخدمات) في يوم بعينه؛ الخدمة نفسها (الاسم/العدد/التسليح)
    # ثابتة في `service_catalog` بـcore.json، اللي بيتغيّر يوميًا بس هنا.
    "day_afraad": "afraad_basic",
    # فتح اليوم لأول مرة هو اللي بيسجّل الراحة الأسبوعية التلقائية. العلامة
    # تخص اليوم نفسه عشان حذف الراحة بعد كده مايرجعهاش في الفتح التالي.
    "weekly_rest_seeded_days": "weekly_rest_seeded",
    # النسخة المبدئية لضباط الأهداف جاية من آخر تأكيد لليوم السابق. بنحفظ
    # المصدر والبصمة جوّه ملف اليوم عشان نعرف هل المشغّل لمسها قبل تحديثها.
    "target_defaults": "target_defaults",
    "day_campaign": "campaign",
    "day_service_runs": "service_runs",
    # علامة مصدر اليوم المستورد؛ غيابها يعني أن اليوم أُنشئ داخل النظام.
    "day_import": "import",
}


def core_file():
    """`data/core.json` — الشكل القديم (ملف واحد). الشكل الحالي مجلد `data/core/` (شوف `CORE_BUNDLES`)."""
    return DATA_DIR / CORE_NAME


def core_dir():
    return DATA_DIR / CORE_DIR_NAME


def days_dir():
    return DATA_DIR / DAYS_NAME


def board_source_doc_path(day: str) -> Path:
    """Preserved authoritative Word roster used for lossless export."""
    return DATA_DIR / SOURCE_DOCS_NAME / "board" / f"{day}.docx"


# شكل تخزين اليوم: «folder» (الافتراضي) = مجلد لكل يوم فيه ملف لكل جانب
# (data/days/2026/09/2026-09-05/assignments.json …)، و«legacy» = ملف JSON واحد. القراءة بتفهم
# الاتنين دايمًا؛ الكتابة بتحوّل اليوم للشكل المطلوب أول ما يتعدّل (في نفس معاملة الدفتر).
DAY_LAYOUT = os.environ.get("PERSONNEL_DAY_LAYOUT", "folder").strip().lower() or "folder"

# ملفات المجلد: كل جانب في ملف، والأقسام اللي بتتغيّر مع بعض في نفس الملف (بالتوزيع ده الحفظ بيكتب
# الملف/الملفين اللي اتغيّروا بس، وتفاصيل الخدمة ورئاستها في `assignments.json` لوحده).
DAY_BUNDLES = (
    ("assignments.json", ("assignments", "assignment_seq")),
    ("officers.json", ("officer_states",)),
    ("confirm.json", ("confirm", "status")),
    ("counts.json", ("counts", "service_runs")),
    ("afraad.json", ("afraad_basic",)),
    ("campaign.json", ("campaign",)),
    ("extras.json", ("weekly_rest_seeded", "target_defaults", "import")),
)
_BUNDLE_OF = {section: name for name, sections in DAY_BUNDLES for section in sections}
_DEFAULT_BUNDLE = "extras.json"


def legacy_day_file(day):
    """`data/days/2026/09/2026-09-05.json` — الشكل القديم (ملف واحد). متشعّب بالسنة والشهر عشان
    مجلد واحد فيه آلاف الملفات تقيل في متصفح الملفات على ويندوز."""
    return days_dir() / day[:4] / day[5:7] / f"{day}.json"


def day_folder(day):
    return days_dir() / day[:4] / day[5:7] / day


def day_path(day):
    """مكان اليوم الحالي على القرص: مجلده لو اتحوّل، وإلا ملفه القديم (حتى لو لسه مش موجود)."""
    folder = day_folder(day)
    return folder if folder.is_dir() and _dir_sig(folder) else legacy_day_file(day)


def _split_bundles(blob):
    """محتوى اليوم -> {اسم الملف: {قسم: قيمة}} للملفات اللي فيها حاجة بس."""
    groups = {}
    for section, value in blob.items():
        groups.setdefault(_BUNDLE_OF.get(section, _DEFAULT_BUNDLE), {})[section] = value
    return groups


def _combine(parts):
    """بصمة اليوم من بصمات ملفاته (ثابتة مهما كان ترتيب القراءة)."""
    return _fingerprint("\n".join(f"{name}:{parts[name]}" for name in sorted(parts)))


def _dir_sig(folder):
    try:
        return tuple(sorted((e.name, e.stat().st_mtime_ns, e.stat().st_size)
                            for e in os.scandir(folder)
                            if e.name.endswith(".json") and e.is_file()))
    except FileNotFoundError:
        return None


# ---------- مجلد القوة (core) ----------
#
# `core` بقى مجلد فيه ملف لكل موضوع بدل ملف واحد (760KB): تعديل راحة بيكتب `leaves.json` بس. أي مفتاح
# مش مذكور هنا بيروح `misc.json`، فمفتاح جديد في الكود مايحتاجش تعديل. الشكل القديم (`core.json`)
# لسه بيتقرا، وأول حفظ بيحوّله للمجلد في نفس معاملة الدفتر.
CORE_BUNDLES = (
    ("force.json", ("officers", "personnel", "conscripts", "officer_status_periods",
                    "officer_medical_states", "custom_officer_statuses")),
    ("leaves.json", ("leaves", "leave_history", "rest_suspensions")),
    ("courses.json", ("courses", "course_terms")),
    ("services.json", ("service_catalog", "service_lines", "service_tags", "counts_template",
                       "print_collections", "afraad_basic_ids")),
    ("command.json", ("command", "command_groups", "command_history")),
    ("vehicles.json", ("vehicles",)),
    ("reference.json", ("reference_lists",)),
    ("regularity.json", ("regularity_inputs", "inspection_schedule", "inspection_seeded_days")),
)
_CORE_BUNDLE_OF = {key: name for name, keys in CORE_BUNDLES for key in keys}
_CORE_DEFAULT = "misc.json"


def _split_core(core):
    """core -> {اسم الملف: {مفتاح: قيمة}} للملفات اللي فيها حاجة بس."""
    groups = {}
    for key, value in core.items():
        groups.setdefault(_CORE_BUNDLE_OF.get(key, _CORE_DEFAULT), {})[key] = value
    return groups


def core_path():
    """مكان core الحالي: مجلده لو اتحوّل، وإلا ملفه القديم (حتى لو لسه مش موجود)."""
    folder = core_dir()
    return folder if folder.is_dir() and _dir_sig(folder) else core_file()


def core_exists():
    return core_path().exists()


def read_core_at(data_dir):
    """core من مجلد بيانات معيّن بأي شكل تخزين (للأدوات)؛ {} لو مفيش."""
    folder = Path(data_dir) / CORE_DIR_NAME
    if folder.is_dir():
        core = {}
        for entry in sorted(os.scandir(folder), key=lambda e: e.name):
            if entry.name.endswith(".json") and entry.is_file():
                core.update(_parse(_read_text(Path(entry.path)), Path(entry.path)))
        if core:
            return core
    legacy = Path(data_dir) / CORE_NAME
    return _parse(_read_text(legacy), legacy) if legacy.exists() else {}


def _plan_core_write(core, old_parts):
    """ملفات core اللي هتتكتب/تتشال: {files, delete, fingerprint, parts, texts}."""
    legacy, folder = core_file(), core_dir()
    in_folder = folder.is_dir() and bool(_dir_sig(folder))
    migrating = legacy.exists()
    known = {} if migrating or not in_folder else dict(old_parts or {})
    parts, files, texts = {}, {}, {}
    for name, group in _split_core(core).items():
        text = _dumps(group)
        texts[name] = text
        parts[name] = stamp = _fingerprint(text)
        if known.get(name) != stamp:
            files[_rel(folder / name)] = text
    delete = [_rel(folder / name) for name in known if name not in parts]
    if migrating:
        delete.append(_rel(legacy))
    return {"files": files, "delete": delete, "fingerprint": _combine(parts), "parts": parts,
            "texts": texts}


def core_changed_paths(core):
    """المسارات النسبية اللي هتتكتب أو تتشال عند حفظ `core`، في أي layout."""
    path = core_path()
    entry = _load_entry(path, core=True, cache=False)[0] if path.exists() else None
    plan = _plan_core_write({**core, "schema": core.get("schema", SCHEMA_VERSION)},
                            entry.parts if entry is not None else None)
    return sorted({*plan["files"], *plan["delete"]})


def _apply_core_plan(plan):
    """ينفّذ الخطة ويحط core الجديد في الكاش. -> المحتوى المحلّل."""
    for rel, text in plan["files"].items():
        _write_atomic(DATA_DIR / rel, text)
    for rel in plan["delete"]:
        (DATA_DIR / rel).unlink(missing_ok=True)
    folder = core_dir()
    blob = {}
    for name in sorted(plan["parts"]):
        blob.update(_parse(plan["texts"][name], folder / name))
    entry = _Entry(_dir_sig(folder), plan["fingerprint"], _pack(blob), dict(plan["parts"]))
    with _STATE_LOCK:
        _cache.put(str(folder), entry, True)
    return blob


def day_changed_paths(day, blob):
    """المسارات النسبية (لمجلد البيانات) اللي `_write` هيكتبها أو يشيلها لو اليوم بقى `blob` — للأدوات
    (زي الاستيراد) اللي بتاخد نسخة أصل قبل الكتابة. [] لو المحتوى هو هو."""
    path = day_path(day)
    entry = _load_entry(path, cache=False)[0] if path.exists() else None
    if entry is not None and pickle.loads(entry.packed) == blob:
        return []
    plan = _plan_day_write(day, blob, entry.parts if entry is not None else None)
    return sorted({*plan["files"], *plan["delete"]})


def read_day_dir(data_dir, day):
    """محتوى يوم من مجلد بيانات معيّن (مش بالضرورة الشغّال) بأي شكل تخزين؛ None لو مفيش."""
    base = Path(data_dir) / DAYS_NAME / day[:4] / day[5:7]
    folder = base / day
    if folder.is_dir():
        blob = {}
        for entry in sorted(os.scandir(folder), key=lambda e: e.name):
            if entry.name.endswith(".json") and entry.is_file():
                blob.update(_parse(_read_text(Path(entry.path)), Path(entry.path)))
        if blob:
            return blob
    legacy = base / f"{day}.json"
    return _parse(_read_text(legacy), legacy) if legacy.exists() else None


def day_blobs_at(data_dir):
    """{يوم: محتواه} لكل أيام مجلد بيانات (الشكلين) — للأدوات."""
    root = Path(data_dir) / DAYS_NAME
    days = set()
    for year in (root.iterdir() if root.exists() else ()):
        for month in (year.iterdir() if year.is_dir() else ()):
            for item in (month.iterdir() if month.is_dir() else ()):
                stem = item.stem if item.is_file() and item.suffix == ".json" else item.name
                if _DAY_STEM.fullmatch(stem):
                    days.add(stem)
    return {day: read_day_dir(data_dir, day) for day in sorted(days)
            if read_day_dir(data_dir, day) is not None}


def day_files(day):
    """ملفات اليوم على القرص (ملفات المجلد، أو الملف القديم) — للأدوات والاختبارات."""
    path = day_path(day)
    if path.is_dir():
        return sorted(Path(e.path) for e in os.scandir(path) if e.name.endswith(".json") and e.is_file())
    return [path] if path.exists() else []


def day_bytes(day):
    """محتوى ملفات اليوم كلها متتالي بالترتيب — لمقارنة «ما اتلمسش» في الاختبارات والأدوات."""
    return b"".join(path.read_bytes() for path in day_files(day))


def copy_day_files(day, dest_root):
    """ينسخ ملفات اليوم (أي شكل) لـ`dest_root` بنفس المسار النسبي لمجلد البيانات — لنسخ الأصل قبل تعديل."""
    for source in day_files(day):
        target = Path(dest_root) / source.relative_to(DATA_DIR)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def read_day_blob(day):
    """محتوى يوم واحد من القرص (أي شكل) — للأدوات والاختبارات؛ {} لو مفيش ملف."""
    path = day_path(day)
    if not path.exists():
        return {}
    return _load(path, cache=False)[1]


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

# سجل النشاط بيدور تلقائيًا (5 ميجا × 20 نسخة) عشان يفضل حجمه محدود.
_LOG_DIR = (DATA_DIR / "logs") if _ENV_DATA_DIR is not None else (ROOT / "logs")
_LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG = logging.getLogger(__name__)
_audit_logger = logging.getLogger("personnel_system.audit")
_audit_logger.setLevel(logging.INFO)
if not _audit_logger.handlers:
    _audit_handler = RotatingFileHandler(_LOG_DIR / "audit.log", maxBytes=5 * 1024 * 1024,
                                          backupCount=20, encoding="utf-8")
    _audit_handler.setFormatter(logging.Formatter("%(message)s"))
    _audit_logger.addHandler(_audit_handler)
    _audit_logger.propagate = False


def _log_audit():
    # الاستيراد هنا يمنع دايرة store -> auth.users -> store وقت بدء البرنامج.
    from flask import g, has_request_context
    if has_request_context():
        # كود الاستجابة لسه مش معروف هنا؛ after_request يسجله بعد ما المسار يخلص.
        g.audit_writes = getattr(g, "audit_writes", 0) + 1
    else:
        from .auth.audit_log import emit
        emit("write")


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
            f"تعذّرت قراءة «{path.name}» ({exc}). تأكد من الصلاحيات، "
            f"أو استعد نسخة من {BACKUP_DIR_NAME}/."
        ) from exc


def _parse(raw, path):
    """تحليل JSON برسائل خطأ واضحة.

    ملف تالف **مايرجّعش فاضي**. الرجوع بقاعدة فاضية كان بيخلي الأعطال
    تعدّي في صمت (الصفحة بتعرض صفر ضباط وكأن القوة اتفضّت)، وأول حفظ
    بعدها بيكتب الفاضي ده فوق البيانات الحقيقية = ضياع كامل. ملف مقطوع
    من قطع كهربا لازم يوقف الدنيا بصوت عالي، والنسخ في backups/ هي طريق
    الرجوع.
    """
    label = f"{path.parent.name}/{path.name}" if _DAY_STEM.fullmatch(path.parent.name) else path.name
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DataUnreadable(
            f"الملف «{label}» تالف وتعذّرت قراءته (السطر {exc.lineno}، العمود {exc.colno}). "
            f"لم تُكتب عليه أي بيانات — استعد أحدث نسخة سليمة من {BACKUP_DIR_NAME}/."
        ) from exc
    if not isinstance(data, dict):
        raise DataUnreadable(
            f"الملف «{label}» ليس بالشكل المتوقع (وُجد {type(data).__name__} بدلًا من كائن). "
            f"استعد نسخة من {BACKUP_DIR_NAME}/."
        )
    return data


def _fsync_file(fd, path):
    """`fsync` لملف مفتوح. `path` للتشخيص والاختبارات بس."""
    os.fsync(fd)


def _fsync_dir(path):
    """`fsync` لمجلد عشان إنشاء/استبدال/مسح ملف جوّاه يبقى ثابت على القرص.
    ويندوز مابيدعمش فتح مجلد للمزامنة (و`os.replace` هناك بيكتب البيانات
    الوصفية بنفسه)، وبعض أنظمة الملفات بترفضه — الاتنين بيتخطّوا بهدوء."""
    if os.name == "nt":
        return
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _replace(src, dst):
    """`os.replace` باسم في الموديول — نقطة حقن أعطال في الاختبارات."""
    os.replace(src, dst)


def _write_atomic(path, text):
    """كتابة ذرّية ومتزامنة: ملف `.tmp` جنبه، `fsync`، استبدال، و`fsync`
    للمجلد — فلو الجهاز اتقفل في النص مايتسابش ملف نص-مكتوب مكان البيانات.

    البايتات UTF-8 بالظبط (من غير تحويل سطور ويندوز) عشان بصمة sha256
    في دفتر المعاملات تطابق اللي على القرص حرفيًا."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as fh:
        fh.write(text.encode("utf-8"))
        fh.flush()
        _fsync_file(fh.fileno(), tmp)
    _replace(tmp, path)
    _fsync_dir(path.parent)


def _check_schema(found):
    """يتأكد إن البيانات بنفس بنية الكود. الفرق بيتقفل بصوت عالي مش
    بالسكوت — قراءة بنية قديمة بالكود الجديد بتطلع أرقام غلط في اليوميات."""
    if found == SCHEMA_VERSION:
        return
    if found < SCHEMA_VERSION:
        raise SchemaMismatch(
            f"البيانات ببنية {found}، بينما يتوقع البرنامج البنية {SCHEMA_VERSION}. "
            f"شغّل برامج الهجرة النصية في migrations/ أولًا (ينشئ كل منها نسخة "
            f"احتياطية في {BACKUP_DIR_NAME}/ قبل الكتابة)."
        )
    raise SchemaMismatch(
        f"البيانات ببنية {found} أحدث من الكود ({SCHEMA_VERSION}). "
        f"حدّث البرنامج أو استعد نسخة من {BACKUP_DIR_NAME}/."
    )


# ---------- تفكيك وتجميع ----------

def _scan_day_files():
    """{يوم: (مسار, بصمة)} بمسح os.scandir (≈3ms لـ1100 ملف) بدل pathlib.glob+sorted (≈23ms)."""
    root = days_dir()
    out = {}
    try:
        years = [e for e in os.scandir(root) if e.is_dir()]
    except FileNotFoundError:
        return out
    for year in years:
        try:
            months = [e for e in os.scandir(year.path) if e.is_dir()]
        except OSError:
            continue
        for month in months:
            try:
                entries = list(os.scandir(month.path))
            except OSError:
                continue
            folders = []
            for entry in entries:
                name = entry.name
                if name.endswith(".json") and not name.startswith(".") and entry.is_file():
                    stat = entry.stat()
                    out[name[:-5]] = (Path(entry.path), (stat.st_mtime_ns, stat.st_size))
                elif entry.is_dir() and _DAY_STEM.fullmatch(name):
                    folders.append(entry)
            for entry in folders:                    # المجلد بيغلب الملف القديم لو الاتنين موجودين
                sig = _dir_sig(entry.path)
                if sig:
                    out[entry.name] = (Path(entry.path), sig)
    return out


def all_day_files():
    """كل ملفات الأيام مرتبة بالتاريخ."""
    scanned = _scan_day_files()
    return [scanned[day][0] for day in sorted(scanned)]


def day_names():
    """تواريخ ملفات الأيام الموجودة، مرتبة — من الفهرس، من غير قراءة محتواها."""
    return _ensure_index().days()


def split(data):
    """-> (core, {يوم: محتوى ملفه}) — عكس `merge()` بالظبط.

    اليوم اللي كل أقسامه فاضية مابيتكتبش له ملف، و`_write` بيشيل ملفه
    القديم لو كان موجود.
    """
    # change_log له ملفه (changes/log.jsonl) — append-only، مابيدخلش في core.json أبدًا
    core = {k: v for k, v in data.items()
            if not k.startswith("_") and k not in DAY_SECTIONS and k != "change_log"}
    days = {}
    for key, name in DAY_SECTIONS.items():
        for day, value in (data.get(key) or {}).items():
            if not value:
                continue
            days.setdefault(day, {})[name] = value
    return core, days


def revision(data, days=None):
    """Stable optimistic-concurrency token for the loaded scope."""
    core, day_map = split(data)
    if days is not None:
        wanted = set(days)
        day_map = {day: value for day, value in day_map.items() if day in wanted}
    return _fingerprint(_dumps({"core": core, "days": day_map}))


def stale_revision(data, supplied, days=None):
    """Return the current token when a supplied UI token is stale."""
    if supplied in (None, ""):
        return None
    current = revision(data, days)
    return current if str(supplied) != current else None


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


# ---------- نطاق القراءة ----------
#
# كل مسار بيعلن الأيام اللي محتاجها: قايمة أيام صريحة، أو دالة بتاخد
# `ScopeView` (القوة + فهرس الأيام) وترجّع القايمة. القراءة والمقارنة
# والكتابة بتلمس `core.json` والأيام دي بس. `ALL_DAYS` (الأرشيف كله)
# للعمليات الصريحة بس: النسخ الاحتياطي والهجرات والاستيراد والتصدير الشامل.

class OutOfScope(RuntimeError):
    """كود لمس يوم ليه بيانات على القرص من غير ما المسار يعلنه في نطاقه.

    خطأ برمجي مش خطأ مستخدم: الرجوع بيوم فاضي كان هيعرض بيانات ناقصة،
    والكتابة عليه كانت هتمسح الملف الحقيقي.
    """


class _AllDays:
    def __repr__(self):
        return "ALL_DAYS"


ALL_DAYS = _AllDays()


class ScopeView:
    """اللي دالة النطاق تقدر تشوفه قبل تحميل أي يوم: القوة والفهرس."""

    def __init__(self, data, index):
        self.data = data
        self.index = index


class _ScopedSection(dict):
    """قسم يومي متحمّل جزئيًا. الوصول بالمفتاح ليوم مش في النطاق وعنده
    القسم ده على القرص بيرمي `OutOfScope` بدل ما يرجّع فاضي في صمت.

    القسم دايمًا «مش فاضي» في الشرط (`__bool__`) عشان `data.get(k) or {}`
    مايستبدلوش بقاموس عادي من غير حراسة.
    """
    __slots__ = ("_key", "_guard")

    def __init__(self, key, values, guard):
        super().__init__(values)
        self._key = key
        self._guard = guard

    def _check(self, day):
        if not dict.__contains__(self, day):
            self._guard(self._key, day)

    def __getitem__(self, day):
        self._check(day)
        return dict.__getitem__(self, day)

    def get(self, day, default=None):
        self._check(day)
        return dict.get(self, day, default)

    def __contains__(self, day):
        self._check(day)
        return dict.__contains__(self, day)

    def setdefault(self, day, default=None):
        self._check(day)
        return dict.setdefault(self, day, default)

    def __setitem__(self, day, value):
        self._check(day)
        dict.__setitem__(self, day, value)

    def pop(self, day, *default):
        self._check(day)
        return dict.pop(self, day, *default)

    def __delitem__(self, day):
        self._check(day)
        dict.__delitem__(self, day)

    def __bool__(self):
        return True


def _guard_for(index, loaded):
    def guard(key, day):
        if day not in loaded and isinstance(day, str) and index.has(day, key):
            raise OutOfScope(f"اليوم {day} ({key}) خارج نطاق القراءة المعلن لهذا المسار.")
    return guard


# ---------- فهرس الأيام ----------
#
# في الذاكرة بس، ومبني من الملفات نفسها: أي عملية جديدة بتعيد بناءه من
# القرص أول ما تحتاجه. لكل يوم: بصمة الملف (mtime، الحجم)، الأقسام اللي
# فيه، أسماء أقسام صفوف اللوحة بترتيب ظهورها، والأشخاص المذكورين فيه.
# الكتابة بتحدّثه مع الملف نفسه؛ وأي ملف اتغيّر من برّه (بصمة مختلفة) أو
# اتضاف أو اتشال بيتصلّح عند أول استخدام.

class _DayMeta(NamedTuple):
    sig: tuple
    sections: frozenset
    board_sections: tuple
    people: frozenset


def _board_names(rows):
    names = []
    for row in rows if isinstance(rows, list) else ():
        if not isinstance(row, dict):
            continue
        name = str(row.get("section") or SECTION_OCCASIONAL).strip()
        if name not in names:
            names.append(name)
    return tuple(names)


def _ids(value):
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _day_meta(sig, blob):
    sections = frozenset(key for key, name in DAY_SECTIONS.items() if blob.get(name))
    people = set()
    rows = blob.get("assignments")
    for row in rows if isinstance(rows, list) else ():
        if isinstance(row, dict):
            people.update(_ids(row.get("officer_ids")))
            people.update(_ids(row.get("personnel_ids")))
    states = blob.get("officer_states")
    if isinstance(states, dict):
        people.update(k for k in states if isinstance(k, str))
    afraad = blob.get("afraad_basic")
    for entry in (afraad.values() if isinstance(afraad, dict) else ()):
        if isinstance(entry, dict):
            people.update(entry[k] for k in ("morning_person_id", "night_person_id")
                          if isinstance(entry.get(k), str) and entry.get(k))
    campaign = blob.get("campaign") or {}
    for section in ("lorries", "services", "daily"):
        for value in (campaign.get(section) or {}).values():
            driver = value.get("driver") or {}
            if driver.get("id"):
                people.add(driver["id"])
    return _DayMeta(sig, sections, _board_names(rows), frozenset(people))


class DayIndex:
    """لقطة ثابتة من الفهرس — مابتتغيّرش بعد ما تتسلّم."""

    def __init__(self, entries):
        self._entries = entries

    def __contains__(self, day):
        return day in self._entries

    def __len__(self):
        return len(self._entries)

    def days(self):
        return sorted(self._entries)

    def has(self, day, key):
        meta = self._entries.get(day)
        return meta is not None and key in meta.sections

    def signature(self, day):
        meta = self._entries.get(day)
        return meta.sig if meta is not None else None

    def days_with(self, *keys, start=None, end=None):
        """الأيام اللي فيها أي قسم من `keys` (أو أي يوم لو مفيش)، بين
        `start` و`end` شاملهم لو اتحددوا."""
        wanted = set(keys)
        return sorted(
            day for day, meta in self._entries.items()
            if (not wanted or meta.sections & wanted)
            and (start is None or day >= start) and (end is None or day <= end))

    def recorded(self):
        """أيام الشغل الفعلي: تكليف أو حالة ضابط (`utils.resolve_recorded_range`)."""
        return self.days_with("day_assignments", "day_officers")

    def recorded_between(self, date_from, date_to):
        if date_from > date_to:
            date_from, date_to = date_to, date_from
        return self.days_with("day_assignments", "day_officers",
                              start=date_from, end=date_to)

    def person_days(self, person_id):
        return sorted(d for d, meta in self._entries.items() if person_id in meta.people)

    def board_sections(self):
        """[(يوم, أسماء أقسام صفوفه)] لكل يوم فيه تكليفات، بالتاريخ."""
        return [(d, self._entries[d].board_sections) for d in sorted(self._entries)
                if self._entries[d].board_sections]


_STATE_LOCK = threading.RLock()     # الكاش والفهرس — مستقل عن LOCK بتاع المعاملة
_index_state = {"dir": None, "entries": None, "checked": 0.0}
# بصمة كل ملف في كل يوم (≈8000 `stat` لمجلدات الأيام) مش لازم تتعمل مع كل طلب: كتابات التطبيق بتحدّث
# الفهرس بنفسها (`_index_put`)، فالمسح الكامل بس لاكتشاف تعديل من «برّه» (محرر/سكربت) بعد الفترة دي.
INDEX_RECHECK_SECONDS = 1.0
INDEX_STATS = {"rebuilds": 0, "repairs": 0}


def _forget_index():
    with _STATE_LOCK:
        _index_state.update(dir=None, entries=None, checked=0.0)


def _file_sig(path):
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def _meta_from_file(path, cache=True):
    entry, blob = _load(path, cache=cache)
    return _day_meta(entry.sig, blob)


def _ensure_index():
    """الفهرس الحالي — بيتبني لو مش موجود وبيتصلّح لو أي ملف اتغيّر."""
    with _STATE_LOCK:
        root = str(DATA_DIR)
        entries = _index_state["entries"] if _index_state["dir"] == root else None
        if (entries is not None and INDEX_RECHECK_SECONDS > 0
                and time.monotonic() - _index_state.get("checked", 0.0) < INDEX_RECHECK_SECONDS):
            return DayIndex(entries)
        scanned = _scan_day_files()
        files = {day: item[0] for day, item in scanned.items()}
        if entries is None:
            # البناء الكامل مايملاش الكاش — الأيام المستخدمة فعلًا هي اللي تستاهل الذاكرة
            entries = {day: _meta_from_file(path, cache=False)
                       for day, path in sorted(files.items())}
            _index_state.update(dir=root, entries=entries, checked=time.monotonic())
            INDEX_STATS["rebuilds"] += 1
            return DayIndex(entries)
        fresh = None
        for day in entries.keys() - files.keys():
            fresh = fresh if fresh is not None else dict(entries)
            fresh.pop(day, None)
        for day, path in files.items():
            meta = entries.get(day)
            if meta is not None and meta.sig == scanned[day][1]:
                continue
            fresh = fresh if fresh is not None else dict(entries)
            fresh[day] = _meta_from_file(path)
        if fresh is not None:
            _index_state["entries"] = fresh
            INDEX_STATS["repairs"] += 1
        _index_state["checked"] = time.monotonic()
        return DayIndex(_index_state["entries"])


def _index_put(day, meta):
    """تحديث يوم واحد في الفهرس (نسخة جديدة — اللقطات المسلّمة ما تتغيّرش)."""
    with _STATE_LOCK:
        if _index_state["dir"] != str(DATA_DIR) or _index_state["entries"] is None:
            return
        fresh = dict(_index_state["entries"])
        if meta is None:
            fresh.pop(day, None)
        else:
            fresh[day] = meta
        _index_state["entries"] = fresh


def day_index():
    """لقطة من فهرس الأيام الحالي."""
    return _ensure_index()


# ---------- الكاش ----------
#
# نسخة واحدة مسلسلة (pickle) لكل ملف، مش الكائن المحلّل: كل قراءة بتفكّ
# كائن جديد، فمفيش إشارة مشتركة ممكن تتعدّل برّه معاملة. `core.json` في
# خانة لوحده؛ الأيام في LRU سقفه `DAY_CACHE_SIZE`. `pickle` هنا نسخ داخلي
# لكائنات موثوقة حُلّلت من JSON، وليس قراءة لملف pickle خارجي.

DAY_CACHE_SIZE = 128


class _Entry(NamedTuple):
    sig: tuple
    fingerprint: str
    packed: bytes
    parts: dict = None          # {ملف: بصمته} لمجلد يوم؛ None لملف واحد


class _FileCache:
    def __init__(self, limit):
        self.limit = limit
        self.core = None              # (المسار, _Entry)
        self.days = OrderedDict()     # {المسار: _Entry} — الأقدم استخدامًا أولًا
        self.evictions = 0

    def get(self, key, core):
        if core:
            return self.core[1] if self.core and self.core[0] == key else None
        hit = self.days.get(key)
        if hit is not None:
            self.days.move_to_end(key)
        return hit

    def put(self, key, entry, core):
        if core:
            self.core = (key, entry)
            return
        self.days[key] = entry
        self.days.move_to_end(key)
        while len(self.days) > self.limit:
            self.days.popitem(last=False)
            self.evictions += 1

    def drop(self, key):
        self.days.pop(key, None)

    def clear(self):
        """ينسى كل اللي في الذاكرة — الكاش والفهرس وسجل التغييرات."""
        with _STATE_LOCK:
            self.days.clear()
            self.core = None
            _forget_index()
            _log_state.clear()


_cache = _FileCache(DAY_CACHE_SIZE)


def _pack(value):
    return pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)


def _load_entry(path, core=False, cache=True):
    """-> (_Entry, كائن محلّل جديد أو None لو جه من الكاش). بيعيد القراءة
    بس لما الملف يتغيّر. `cache=False` بيقرا من غير ما يزحم كاش الأيام
    (النسخ الاحتياطي وبناء الفهرس)."""
    with _STATE_LOCK:
        key = str(path)
        if path.is_dir():
            sig = _dir_sig(path)
            hit = _cache.get(key, core)
            if hit is not None and hit.sig == sig:
                return hit, None
            blob, parts = {}, {}
            for name in sorted(n for n, *_ in sig or ()):
                text = _read_text(path / name)
                parsed = _parse(text, path / name)
                parts[name] = _fingerprint(text)
                blob.update(parsed)
            entry = _Entry(sig, _combine(parts), _pack(blob), parts)
            if cache or core:
                _cache.put(key, entry, core)
            return entry, blob
        stat = path.stat()
        sig = (stat.st_mtime_ns, stat.st_size)
        hit = _cache.get(key, core)
        if hit is not None and hit.sig == sig:
            return hit, None
        text = _read_text(path)
        parsed = _parse(text, path)
        entry = _Entry(sig, _fingerprint(text), _pack(parsed))
        if cache or core:
            _cache.put(key, entry, core)
        return entry, parsed


def _load(path, core=False, cache=True):
    """-> (_Entry, محتوى الملف كائن جديد مش متشارك مع الكاش)."""
    entry, parsed = _load_entry(path, core=core, cache=cache)
    return entry, (parsed if parsed is not None else pickle.loads(entry.packed))


def _remember(path, text, core=False):
    """بعد كتابة ملف: يحطّه في الكاش بنسخته الجديدة. -> (_Entry, محتواه)."""
    parsed = _parse(text, path)
    entry = _Entry(_file_sig(path), _fingerprint(text), _pack(parsed))
    with _STATE_LOCK:
        _cache.put(str(path), entry, core)
    return entry, parsed


# ---------- القراءة ----------

def _normalise(data):
    for cat in ("officers", "personnel"):
        data[cat] = as_roster(data.get(cat))
        sort_active(data, cat)
    data.setdefault("leaves", [])
    if "leave_history" not in data:
        # بيانات قديمة قبل السجل الدائم: نبذره مرة من change_log الموجود
        # (نفس عمل migrations/027) عشان حذف حصل قبل التحديث يظهر ويتسترجع.
        data["leave_history"] = []
        if data.get("change_log"):
            try:
                from .leaves import backfill_history
                backfill_history(data)
            except Exception:   # السجل مساعد؛ فشله مايوقفش تحميل البيانات
                data["leave_history"] = []
    data.setdefault("service_tags", [])
    data.setdefault("courses", [])
    data.setdefault("course_terms", [])
    data.setdefault("vehicles", [])
    data.setdefault("service_lines", [])
    data.setdefault("conscripts", [])
    command = data.setdefault("command", {})
    for role in DEFAULT_DATA["command"]:
        command.setdefault(role, None)
    groups = data.setdefault("command_groups", {})
    for role in DEFAULT_DATA["command_groups"]:
        groups.setdefault(role, [])
    data.setdefault("id_seq", {})      # عدّادات الأرقام — شوف reserve_id()


def _resolve_scope(days, view):
    if callable(days) and days is not ALL_DAYS:
        days = days(view)
    if days is ALL_DAYS:
        return None
    if days is None or isinstance(days, (str, bytes)) or not hasattr(days, "__iter__"):
        raise TypeError("نطاق الأيام لازم يكون قايمة أيام صريحة أو دالة أو ALL_DAYS، "
                        f"مش {days!r}.")
    return frozenset(str(day) for day in days if day)


def _attach_change_log(data, core):
    """يحط `data["change_log"]` (نافذة آخر السجلات) من ملفه، أو من core.json لو لسه بالشكل القديم.
    -> بصمة الأساس اللي `_write` بيحسب منها اللي اتضاف."""
    state = _log_window()
    if state is not None:
        data["change_log"] = ChangeLogView(state["packed"], state["count"])
        return {"legacy": False, "last_id": state["last_id"], "count": state["count"],
                "size": state["size"]}
    if isinstance(core.get("change_log"), list):
        data["change_log"] = core["change_log"]
        return {"legacy": True, "last_id": None, "count": 0, "size": 0}
    data["change_log"] = []
    return {"legacy": False, "last_id": None, "count": 0, "size": 0}


def _read(days=ALL_DAYS):
    """قراءة `core.json` والأيام اللي في النطاق بس — من غير قفل، لاستخدامها
    جوه أي بلوك ماسك الـLOCK بالفعل.

    `days`: قايمة أيام، أو دالة `(ScopeView) -> أيام`، أو `ALL_DAYS`.
    الأقسام اليومية في النتيجة فيها أيام النطاق بس، ومحروسة ضد أي يوم
    برّاه (`_ScopedSection`).
    """
    started = time.perf_counter()
    if not core_exists():
        if DATA_DIR.exists() and any(DATA_DIR.iterdir()):
            raise DataUnreadable(
                f"مجلد البيانات «{DATA_DIR.name}» موجود، لكنه لا يحتوي على {CORE_NAME}. "
                f"استعد نسخة من {BACKUP_DIR_NAME}/."
            )
        legacy = ROOT / "data.json"
        if legacy.exists():
            raise SchemaMismatch(
                f"لا تزال البيانات في الملف القديم الواحد «{legacy.name}». "
                f"شغّل migrations/010_split_data_files.py لتفكيكه في مجلد "
                f"«{DATA_DIR.name}/» (ينشئ نسخة احتياطية قبل الكتابة)."
            )
        tech_log.event(LOG, "store.initialised_empty", level=logging.WARNING,
                       data_dir=str(DATA_DIR))
        explode(json.loads(json.dumps(DEFAULT_DATA)))    # نسخة — explode بيعدّل

    core_entry, core = _load(core_path(), core=True)
    _check_schema(core.get("schema", 1))
    data = merge(core, {})
    log_base = _attach_change_log(data, core)
    _normalise(data)

    index = _ensure_index()
    scope = _resolve_scope(days, ScopeView(data, index))
    wanted = index.days() if scope is None else sorted(d for d in scope if d in index)

    originals, fingerprints, day_parts = {}, {"core": core_entry.fingerprint}, {}
    for day in wanted:
        entry, blob = _load(day_path(day))
        originals[day] = entry.packed
        fingerprints[day] = entry.fingerprint
        if entry.parts is not None:
            day_parts[day] = dict(entry.parts)
        for key, name in DAY_SECTIONS.items():
            if blob.get(name):
                data[key][day] = blob[name]

    if scope is not None:
        guard = _guard_for(index, scope)
        for key in DAY_SECTIONS:
            data[key] = _ScopedSection(key, data[key], guard)

    # بصمات اللي اتقرا ونطاقه — `_write` بيقارن بيها ويكتب اللي اتغيّر بس.
    # المفتاح بيبدأ بـ`_` فما بيتخزّنش (شوف `split`).
    data["_fp"] = {"fingerprints": fingerprints, "originals": originals,
                   "scope": scope, "index": index, "log": log_base, "parts": day_parts,
                   "core_parts": dict(core_entry.parts or {})}
    elapsed = tech_log.ms_since(started)
    tech_log.event(LOG, "store.load",
                   level=logging.WARNING if elapsed > 1000 else logging.DEBUG,
                   duration_ms=elapsed, day_files=len(wanted),
                   scope="all" if scope is None else len(scope))
    return data


# ---------- أسئلة على الأرشيف من غير تحميله ----------
#
# الأسئلة اللي إجابتها محتاجة كل الأيام («آخر يوم فيه تكليف»، «أقسام
# اللوحة المستخدمة قبل كده») بتتجاوب من الأيام المحمّلة لأيام النطاق، ومن
# الفهرس للباقي. بيانات من غير `_fp` (تجميع كامل) بتتجاوب منها هي بس.

def _tracking(data):
    fp = data.get("_fp") or {}
    return fp.get("scope"), fp.get("index")


def known_days(data, *keys):
    """الأيام اللي فيها أي قسم من `keys`، مرتبة."""
    scope, index = _tracking(data)
    out = {day for key in keys for day, value in dict.items(data.get(key) or {}) if value}
    if scope is not None and index is not None:
        out.update(day for day in index.days_with(*keys) if day not in scope)
    return sorted(out)


def previous_section(data, key, day):
    """(آخر يوم قبل `day` فيه القسم ده، قيمته) أو ("", {}) — للتوريث من اليوم
    اللي قبله. لو اليوم ده برّه نطاق القراءة بتتقرا قيمته من ملفه للعرض بس،
    ومابيدخلش في الحفظ، فماتتعدلش القيمة الراجعة."""
    days = [value for value in known_days(data, key) if value < day]
    if not days:
        return "", {}
    source = days[-1]
    section = data.get(key) or {}
    if dict.__contains__(section, source):
        return source, dict.__getitem__(section, source) or {}
    _entry, blob = _load(day_path(source))
    return source, blob.get(DAY_SECTIONS[key]) or {}


def recorded_days(data):
    """أيام الشغل الفعلي (تكليف أو حالة ضابط) — من غير تحميلها."""
    return known_days(data, "day_assignments", "day_officers")


def board_section_days(data):
    """[(يوم, أسماء أقسام صفوفه بترتيب ظهورها)] لكل يوم فيه تكليفات."""
    scope, index = _tracking(data)
    out = {}
    if scope is not None and index is not None:
        out.update((day, names) for day, names in index.board_sections() if day not in scope)
    for day, rows in dict.items(data.get("day_assignments") or {}):
        names = _board_names(rows)
        if names:
            out[day] = names
    return sorted(out.items())


def require_person_days(data, person_id):
    """يتأكد إن كل يوم مذكور فيه الشخص ده محمّل — قبل أي تنظيف بيلف على
    الأيام المحمّلة على إنها كل الأيام."""
    scope, index = _tracking(data)
    if scope is None or index is None:
        return
    missing = [day for day in index.person_days(person_id) if day not in scope]
    if missing:
        raise OutOfScope(f"أيام مذكور فيها {person_id} خارج النطاق المعلن: {', '.join(missing)}")


# ---------- الكتابة ----------

def _rel(path):
    return str(Path(path).relative_to(DATA_DIR))


def _plan_day_write(day, blob, old_parts):
    """ملفات اليوم اللي هتتكتب/تتشال: {files: {مسار نسبي: نص}, delete, fingerprint, parts, force}."""
    legacy = legacy_day_file(day)
    folder = day_folder(day)
    in_folder = folder.is_dir() and bool(_dir_sig(folder))
    if DAY_LAYOUT != "folder" and not in_folder:
        text = _dumps(blob)
        return {"files": {_rel(legacy): text}, "delete": [], "fingerprint": _fingerprint(text),
                "parts": None, "force": False, "layout": "legacy"}
    migrating = legacy.exists()
    known = {} if migrating or not in_folder else dict(old_parts or {})
    parts, files = {}, {}
    for name, group in _split_bundles(blob).items():
        text = _dumps(group)
        stamp = _fingerprint(text)
        parts[name] = stamp
        if known.get(name) != stamp:
            files[_rel(folder / name)] = text
    delete = [_rel(folder / name) for name in known if name not in parts]
    if migrating:
        delete.append(_rel(legacy))
    return {"files": files, "delete": delete, "fingerprint": _combine(parts), "parts": parts,
            "force": migrating, "layout": "folder"}


def _day_files_on_disk(day):
    """كل ملفات اليوم الموجودة فعلًا (مجلده وملفه القديم) كمسارات نسبية."""
    out = []
    folder = day_folder(day)
    if folder.is_dir():
        out.extend(_rel(folder / e.name) for e in os.scandir(folder) if e.is_file())
    if legacy_day_file(day).exists():
        out.append(_rel(legacy_day_file(day)))
    return out


def _apply_day_plan(day, plan):
    """ينفّذ الخطة ويرجّع (_Entry, محتوى اليوم المحلّل) للكاش والفهرس."""
    texts = {}
    for rel, text in plan["files"].items():
        _write_atomic(DATA_DIR / rel, text)
        texts[Path(rel).name] = text
    for rel in plan["delete"]:
        (DATA_DIR / rel).unlink(missing_ok=True)
    with _STATE_LOCK:
        _cache.drop(str(legacy_day_file(day)))
        _cache.drop(str(day_folder(day)))
    if plan["layout"] == "legacy":
        path = legacy_day_file(day)
        parsed = _parse(next(iter(plan["files"].values())), path)
        entry = _Entry(_file_sig(path), plan["fingerprint"], _pack(parsed))
        with _STATE_LOCK:
            _cache.put(str(path), entry, False)
        return entry, parsed
    folder = day_folder(day)
    blob = {}
    for name in plan["parts"]:
        text = texts.get(name)
        if text is None:
            text = _read_text(folder / name)
        blob.update(_parse(text, folder / name))
    entry = _Entry(_dir_sig(folder), plan["fingerprint"], _pack(blob), dict(plan["parts"]))
    with _STATE_LOCK:
        _cache.put(str(folder), entry, False)
    return entry, blob


def _remove_day(day):
    """يمسح كل ملفات اليوم (مجلده وملفه القديم) من القرص والكاش."""
    folder = day_folder(day)
    if folder.is_dir():
        for entry in list(os.scandir(folder)):
            if entry.is_file():
                os.unlink(entry.path)
        try:
            folder.rmdir()
        except OSError:
            pass
    legacy_day_file(day).unlink(missing_ok=True)
    with _STATE_LOCK:
        _cache.drop(str(folder))
        _cache.drop(str(legacy_day_file(day)))


def _write(data):
    """بيكتب اللي اتغيّر بس. بيرجّع (الملفات المكتوبة، الملفات المشالة).

    الترتيب مقصود: بنحسب الفرق الأول، بعدين ناخد النسخة الاحتياطية
    (وهي بتقرا القرص، يعني بتلقط الحالة **قبل** التعديل)، وبعدين نكتب.
    لو الكتابة سبقت النسخة كانت النسخة هتبقى صورة من الوضع الجديد —
    يعني مفيش رجوع أصلًا.

    القراءة الجزئية بتقارن أيام نطاقها بس؛ يوم برّا النطاق ليه ملف على
    القرص مايتكتبش فوقه أبدًا (`OutOfScope`) قبل ما أي ملف يتلمس.
    """
    started = time.perf_counter()
    data["schema"] = SCHEMA_VERSION
    tracking = data.get("_fp") or {}
    # قراءة بصمات الشكل القديم تبقى ممكنة لكائن حمّله اختبار أو أداة.
    before = tracking.get("fingerprints", tracking)
    originals = tracking.get("originals", {})
    scope = tracking.get("scope")
    core, days = split(data)

    old_core = None
    with _STATE_LOCK:
        cached_core = _cache.get(str(core_path()), True)
        if cached_core is not None:
            old_core = pickle.loads(cached_core.packed)
    core_plan = _plan_core_write(core, tracking.get("core_parts"))
    core_stamp = core_plan["fingerprint"]
    core_changed = core_stamp != before.get("core") or core_file().exists()
    # سجل التغييرات: اللي اتضاف بس (أو نقله كله لملفه في أول حفظ بعد الترقية)
    raw_log = data.get("change_log")
    log_base = tracking.get("log")
    if isinstance(raw_log, ChangeLogView) and raw_log.untouched:
        log_list, log_plan = raw_log, None          # ما اتقراش ولا اتعدّل: مفيش حاجة تتكتب ولا تتفك
    else:
        log_list = list(raw_log) if isinstance(raw_log, (list, ChangeLogView)) else []
        log_plan = (_plan_log_write(log_list, log_base, data.get("_change_pending"))
                    if log_base is not None else None)

    new_fp = {"core": core_stamp}
    old_parts, new_parts = tracking.get("parts") or {}, {}
    pending = {}
    for day, blob in days.items():
        if scope is not None and day not in scope and day_path(day).exists():
            raise OutOfScope(f"محاولة كتابة اليوم {day} من غير ما يكون في نطاق المعاملة.")
        if day in originals and _pack(blob) == originals[day]:
            new_fp[day] = before[day]
            if day in old_parts:
                new_parts[day] = old_parts[day]
            continue
        plan = _plan_day_write(day, blob, old_parts.get(day))
        new_fp[day] = plan["fingerprint"]
        if plan["parts"] is not None:
            new_parts[day] = plan["parts"]
        if plan["fingerprint"] != before.get(day) or plan["force"]:
            pending[day] = plan

    # يوم كان له ملف وبقى فاضي — الملف بيتشال عشان القرص يفضل مطابق
    # للذاكرة، وإلا اليوم الممسوح بيرجع لوحده في أول قراءة جاية.
    gone = [day for day in before if day != "core" and day not in new_fp]

    core_files = [*core_plan["files"], *core_plan["delete"]] if core_changed else []
    written = (core_files + [f"{d}.json" for d in pending]
               + ([CHANGE_LOG_FILE] if log_plan else []))
    removed = [f"{d}.json" for d in gone]
    if written or removed:
        operations = []
        if log_plan and log_plan["mode"] == "replace":
            # الأول: لو الانقطاع جه بعدها، core.json القديم لسه فيه السجل فمفيش حاجة بتضيع
            operations.append({"action": "replace", "target": CHANGE_LOG_FILE, "text": log_plan["text"]})
        elif log_plan:
            operations.append({"action": "append", "target": CHANGE_LOG_FILE,
                               "text": log_plan["text"], "offset": log_plan["offset"]})
        if core_changed:
            operations.extend({"action": "replace", "target": rel, "text": text}
                              for rel, text in core_plan["files"].items())
            operations.extend({"action": "delete", "target": rel} for rel in core_plan["delete"])
        for day, plan in pending.items():
            operations.extend({"action": "replace", "target": rel, "text": text}
                              for rel, text in plan["files"].items())
            operations.extend({"action": "delete", "target": rel} for rel in plan["delete"])
        for day in gone:
            operations.extend({"action": "delete", "target": rel} for rel in _day_files_on_disk(day))
        _write_journal(operations)
        _snapshot(core_changed=core_changed)

    new_originals = {day: originals[day] for day in days
                     if day in originals and day not in pending}
    try:
        if log_plan:
            if log_plan["mode"] == "replace":
                _write_atomic(change_log_path(), log_plan["text"])
            else:
                _append_log(change_log_path(), log_plan["text"], log_plan["offset"])
        if core_changed:
            _apply_core_plan(core_plan)
        for day, plan in pending.items():
            entry, blob = _apply_day_plan(day, plan)
            new_originals[day] = entry.packed
            _index_put(day, _day_meta(entry.sig, blob))
        for day in gone:
            _remove_day(day)
            _index_put(day, None)
    except BaseException:
        _forget_index()                  # كتابة وقعت في النص — يتبني من القرص تاني
        raise
    else:
        if written or removed:
            _clear_journal()

    index = _ensure_index() if scope is not None else tracking.get("index")
    new_log_base = log_base
    if log_base is not None and (log_plan or log_base.get("legacy")):
        try:
            stat = change_log_path().stat()
            state = _log_remember_state(
                log_list[-CHANGE_WINDOW:], (stat.st_mtime_ns, stat.st_size), stat.st_size)
            new_log_base = {"legacy": False, "last_id": state["last_id"],
                            "count": state["count"], "size": state["size"]}
        except FileNotFoundError:
            new_log_base = {"legacy": False, "last_id": None, "count": 0, "size": 0}
    data["_change_pending"] = []
    data["_fp"] = {"fingerprints": new_fp, "originals": new_originals,
                   "scope": scope, "index": index, "log": new_log_base, "parts": new_parts,
                   "core_parts": dict(core_plan["parts"]) if core_changed
                   else dict(tracking.get("core_parts") or {})}
    changed_days = frozenset(pending)
    created_days = frozenset(day for day in changed_days if day not in before)
    removed_days = frozenset(p[:-5] for p in removed if p.endswith(".json"))
    if core_changed:
        if old_core is None:
            core_keys = ALL_CORE_KEYS
        else:
            changed = set()
            for key in set(old_core) | set(core):
                old_value = old_core.get(key)
                new_value = core.get(key)
                if old_value != new_value:
                    changed.add(key)
            defaults = {
                key: value for key, value in DEFAULT_DATA.items()
                if key not in old_core and core.get(key) == value
            }
            core_keys = frozenset(changed - set(defaults))
    else:
        core_keys = frozenset()
    changed_sections = {}
    for day in changed_days:
        old_blob = pickle.loads(originals[day]) if day in originals else {}
        new_blob = days.get(day, {})
        changed_sections[day] = frozenset(
            name for name in DAY_SECTIONS.values()
            if old_blob.get(name) != new_blob.get(name))
    if written or removed:
        tech_log.event(LOG, "store.save", duration_ms=tech_log.ms_since(started),
                       files_written=len(written), files_removed=len(removed),
                       core_changed=core_changed, days=",".join(sorted(changed_days)[:10]) or None,
                       bytes=sum(len(t) for t in core_plan["files"].values()) * core_changed
                       + sum(len(t) for plan in pending.values() for t in plan["files"].values()))
    return Changeset(changed_days, created_days, removed_days, core_keys, changed_sections)


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

    مابتتاخدش مع كل كتابة (دي كانت نص مشكلة الأداء): كل النسخ التلقائية
    (قوة أو يوميات) بتاخد نسخة كل `BACKUP_MIN_GAP` ثانية على الأكثر.

    بتتنادى من `_write` تحت `LOCK` بعد دفتر المعاملة وقبل التنفيذ، يعني
    القرص لسه على الحالة **قبل** التعديل. لو عامل النسخ شغّال (السيرفر،
    `start_backup_worker`) بنقرا بايتات الملفات بس هنا (`_capture_backup`) —
    قراءة من غير ضغط — والضغط والتنضيف بيحصلوا في العامل برّه القفل، فالطلب
    مابيستناش الأرشيف. من غير عامل (أدوات، هجرات، اختبارات) بتفضل متزامنة زي الأول.
    """
    worker = _backup_worker
    if worker is None:
        age = _last_backup_age()
        if age is not None and age < BACKUP_MIN_GAP:
            return
        snapshot_now()
        return
    if not worker.accepting():
        return          # نسخة منتظرة أو بتتبني دلوقتي — الطلب ده بيتدمج فيها
    last = worker.last_offer
    if last is not None and time.time() - last < BACKUP_MIN_GAP:
        return          # محاولة قريبة (حتى لو فشلت) — ما نعيدش القراءة مع كل كتابة
    age = _last_backup_age()
    if age is not None and age < BACKUP_MIN_GAP:
        return
    started = time.perf_counter()
    try:
        capture = _capture_backup()
    except OSError as exc:
        tech_log.event(LOG, "backup.failed", level=logging.WARNING, mode="capture",
                       error=type(exc).__name__, detail=str(exc))
        return          # النسخ الاحتياطي أمان إضافي — فشله ما يمنعش الحفظ
    if capture is not None and worker.offer(capture):
        tech_log.event(LOG, "backup.captured", files=len(capture["members"]),
                       bytes=sum(len(b) for _, b in capture["members"]),
                       duration_ms=tech_log.ms_since(started))


def _backup_members():
    """[(مسار, اسمه جوّه الأرشيف)] لملفات البيانات: core + كل يوم + سجل التغييرات الكامل."""
    members = []
    if core_dir().is_dir() and _dir_sig(core_dir()):
        for member in sorted(e.path for e in os.scandir(core_dir())
                             if e.name.endswith(".json") and e.is_file()):
            members.append((Path(member), f"{CORE_DIR_NAME}/{Path(member).name}"))
    else:
        members.append((core_file(), CORE_NAME))
    for day, (anchor, _sig) in sorted(_scan_day_files().items()):
        if anchor.is_dir():
            for member in sorted(e.path for e in os.scandir(anchor) if e.is_file()):
                members.append((Path(member), "days/" + Path(member).relative_to(days_dir()).as_posix()))
        else:
            members.append((anchor, "days/" + anchor.relative_to(days_dir()).as_posix()))
    log_file = change_log_path()
    if log_file.exists():
        members.append((log_file, CHANGE_LOG_FILE))      # التاريخ كله، مش آخر 5000 بس
    return members


def _upload_members():
    uploads = DATA_DIR / "uploads"
    if not uploads.exists():
        return []
    return [(source, source.relative_to(DATA_DIR).as_posix())
            for source in sorted(uploads.rglob("*")) if source.is_file()]


def _capture_backup():
    """لقطة متسقة للنسخة التلقائية — لازم تتنادى تحت `LOCK`.

    بتقرا **بايتات** ملفات البيانات للذاكرة (من غير ضغط، فالمدة قراءة بس) عشان
    الأرشيف اللي هيتبني بعدين برّه القفل يبقى نفس حالة معاملة واحدة بالظبط، مهما
    اتكتب بعدها. ماينفعش نقرا الملفات نفسها وقت البناء: ملف يوم ممكن يتبدّل وسجل
    التغييرات بيتضاف له، فالنسخة تبقى خليط من معاملات مختلفة؛ وعلى ويندوز ملف مفتوح
    للقراءة بيمنع `os.replace` عليه. المرفقات (`uploads/`) كمان بايتاتها بتتقرا هنا:
    صورة ممكن تتمسح أو تتبدّل وقت البناء، والنسخة لازم تشيل اللي كان موجود لحظة اللقطة.
    مرفق اتمسح بين المسح والقراءة (الرفع/المسح بيحصلوا برّه `LOCK`) بيتخطّى."""
    if not core_exists():
        return None
    members = [(arcname, path.read_bytes()) for path, arcname in _backup_members()]
    for source, arcname in _upload_members():
        try:
            members.append((arcname, source.read_bytes()))
        except FileNotFoundError:
            continue
    return {"members": members, "target": backup_dir(), "created": datetime.now()}


# البناء نفسه (ضغط + استبدال + تنضيف) واحد في المرة، سواء من العامل أو من `snapshot_now`
# المتزامنة، عشان التنضيف ما يمسحش ملف لسه التاني بيعدّ عليه. مابيتاخدش جوّه العامل مع `LOCK`
# أبدًا (العامل مابياخدش `LOCK` خالص)، فمفيش ترتيب أقفال يقفل على نفسه.
_BACKUP_BUILD_LOCK = threading.Lock()


def _write_archive(members, uploads, target, created, started, mode):
    """يبني `data-<وقت>.zip` في `target`. `members`: [(اسم جوّه الأرشيف, مسار أو bytes)]،
    `uploads`: [(مسار, اسم)] (اللي اتمسح يتخطّى). بيرمي OSError. -> مسار النسخة.

    ملف `.part` بيتعمل بإنشاء حصري (`xb`)، فلو البناء وقع بنمسحه هو بس — عمره ما
    يكون ملف عملية تانية — بدل ما ملفات ناقصة تتراكم في مجلد النسخ."""
    with _BACKUP_BUILD_LOCK:
        target.mkdir(exist_ok=True)
        final = target / f"data-{created.strftime('%Y%m%d-%H%M%S-%f')}.zip"
        part = final.with_suffix(".part")
        owned = False
        try:
            # الصيغة 2: الملفات الخام زي ما هي على القرص (core + كل يوم + سجل التغييرات الكامل) بدل ما
            # نحمّل كل الأيام ونحوّلها لنص تاني. الصيغة القديمة (data.json واحد) لسه بتتقرا.
            with open(part, "xb") as fh:
                owned = True
                with zipfile.ZipFile(fh, "w", compression=zipfile.ZIP_DEFLATED,
                                     compresslevel=1) as zf:
                    zf.writestr("manifest.json", json.dumps(
                        {"format": 2, "schema": SCHEMA_VERSION, "created": created.isoformat()}))
                    for arcname, source in members:
                        if isinstance(source, bytes):
                            zf.writestr(arcname, source)
                        else:
                            zf.write(source, arcname)
                    for source, arcname in uploads:
                        try:
                            payload = source.read_bytes()      # الملف ما يفضلش مفتوح وقت الضغط
                        except FileNotFoundError:
                            continue
                        zf.writestr(arcname, payload)
            _replace(part, final)
        except BaseException:
            if owned:
                try:
                    part.unlink(missing_ok=True)
                except OSError:
                    pass                    # أحسن محاولة — الخطأ الأصلي هو اللي يطلع
            raise
        _fsync_dir(target)
        _prune_backups(target)
    tech_log.event(LOG, "backup.created", file=final.name, mode=mode,
                   bytes=final.stat().st_size, duration_ms=tech_log.ms_since(started))
    return final


def snapshot_now():
    """نسخة كاملة دلوقتي مهما كان وقت آخر واحدة — للاستعادة والهجرات.

    متزامنة دايمًا (حتى لو عامل النسخ شغّال): بترجع بعد ما الأرشيف يبقى في مكانه. -> مساره أو None."""
    if not core_exists():
        return None
    started = time.perf_counter()
    try:
        return _write_archive([(arcname, path) for path, arcname in _backup_members()],
                              _upload_members(), backup_dir(), datetime.now(), started, "sync")
    except OSError as exc:
        tech_log.event(LOG, "backup.failed", level=logging.WARNING, mode="sync",
                       error=type(exc).__name__, detail=str(exc))
        return None    # النسخ الاحتياطي أمان إضافي — فشله ما يمنعش الحفظ


class BackupWorker:
    """عامل واحد بيبني النسخ التلقائية برّه `LOCK` — نفس شكل `daily_files.DailyFilesWorker`.

    خانة انتظار واحدة بس: لقطة جديدة بتتقبل لما العامل فاضي تمامًا، وأي طلب تاني
    وقت الانتظار أو البناء بيتدمج (بيترفض من غير قراءة)، فمفيش طابور بيكبر ولا
    بناءين في نفس الوقت. فشل البناء بيتسجّل والعامل بيكمّل للطلب الجاي."""

    def __init__(self):
        self.last_offer = None          # time.time() لآخر لقطة اتقبلت — للتهدئة حتى لو فشلت
        self.built = 0
        self.failed = 0
        self._pending = None
        self._busy = False
        self._stop = False
        self._condition = threading.Condition()
        self._thread = threading.Thread(target=self._run, name="store-backup", daemon=True)
        self._thread.start()

    def accepting(self):
        with self._condition:
            return not (self._stop or self._busy or self._pending is not None)

    def offer(self, capture):
        """-> True لو اتقبلت. False لو فيه شغل منتظر/جاري أو العامل اتقفل."""
        with self._condition:
            if self._stop or self._busy or self._pending is not None:
                return False
            self._pending = capture
            self.last_offer = time.time()
            self._condition.notify_all()
            return True

    def flush(self, timeout=30):
        """ينتظر اللقطة المنتظرة والبناء الجاري. -> False لو المهلة خلصت."""
        end = time.monotonic() + timeout
        with self._condition:
            while self._pending is not None or self._busy:
                remaining = end - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
        return True

    def is_alive(self):
        return self._thread.is_alive()

    def stopping(self):
        with self._condition:
            return self._stop

    def stop(self, timeout=None):
        """بيخلّص اللقطة المنتظرة/الجارية وبيقف. -> True لو الخيط وقف جوّه المهلة."""
        with self._condition:
            self._stop = True
            self._condition.notify_all()
        if self._thread is not threading.current_thread():
            self._thread.join(BACKUP_STOP_TIMEOUT if timeout is None else timeout)
        return not self._thread.is_alive()

    def _run(self):
        try:
            self._loop()
        finally:
            _forget_backup_worker(self)     # بعد ما الخيط يخلص بس يبقى فيه مكان لعامل جديد

    def _loop(self):
        while True:
            with self._condition:
                while self._pending is None and not self._stop:
                    self._condition.wait()
                if self._pending is None:
                    return
                capture, self._pending = self._pending, None
                self._busy = True
            ok = False
            try:
                _write_archive(capture["members"], (), capture["target"],
                               capture["created"], time.perf_counter(), "async")
                ok = True
            except Exception as exc:
                tech_log.event(LOG, "backup.failed", level=logging.WARNING, exc_info=exc,
                               mode="async", error=type(exc).__name__, detail=str(exc))
            finally:
                capture = None              # البايتات ما تفضلش في الذاكرة لحد اللقطة الجاية
                with self._condition:
                    self._busy = False
                    if ok:
                        self.built += 1
                    else:
                        self.failed += 1
                    self._condition.notify_all()


_backup_worker = None
_BACKUP_WORKER_LOCK = threading.Lock()
_backup_atexit_registered = False


def start_backup_worker():
    """يشغّل عامل النسخ التلقائية (مرة واحدة؛ النداء التاني بيرجّع نفس العامل).

    لازم بعد `acquire_process_lock()` في `serve.py`/`app.py` — مش وقت `import`، عشان
    الأدوات والاختبارات تفضل نسخها متزامنة. بيسجّل `stop_backup_worker` في atexit.

    عامل بيقف ولسه خيطه شغّال (إيقاف خلصت مهلته والضغط لسه جاري) ما بيتبدّلش: النداء
    بيرجّعه هو نفسه (`stopping()` = True) عشان مايبقاش فيه بنّاءين. بعد ما خيطه يخلص
    بيشيل نفسه، والنداء الجاي بيشغّل عامل جديد."""
    global _backup_worker, _backup_atexit_registered
    with _BACKUP_WORKER_LOCK:
        if _backup_worker is not None and not _backup_worker.is_alive():
            _backup_worker = None
        if _backup_worker is None:
            _backup_worker = BackupWorker()
            if not _backup_atexit_registered:
                import atexit
                atexit.register(stop_backup_worker)
                _backup_atexit_registered = True
            tech_log.event(LOG, "backup.worker_started")
        elif _backup_worker.stopping():
            tech_log.event(LOG, "backup.worker_restart_deferred", level=logging.WARNING)
        return _backup_worker


def _forget_backup_worker(worker):
    global _backup_worker
    with _BACKUP_WORKER_LOCK:
        if _backup_worker is worker:
            _backup_worker = None


def stop_backup_worker(timeout=None):
    """يوقف العامل بعد ما يخلّص اللي في إيده (بمهلة محدودة). آمنة لو اتنادت أكتر من مرة.

    المرجع بيفضل محفوظ لحد ما الخيط يخلص فعلًا: لو المهلة خلصت والضغط لسه جاري بترجع
    False، والعامل يفضل هو العامل الوحيد (مابيقبلش لقطات جديدة، والنسخ التلقائية
    بتتخطّى لحد ما يخلص)، ونداء تاني بيستناه تاني. -> True لو مفيش عامل أو وقف.
    بعد ما يقف النسخ التلقائية بترجع متزامنة."""
    with _BACKUP_WORKER_LOCK:
        worker = _backup_worker
    if worker is None:
        return True
    if not worker.stop(timeout):
        return False
    _forget_backup_worker(worker)
    return True


def backup_worker():
    """العامل الحالي (أو None) — للاختبارات ونقاط الحالة."""
    return _backup_worker


def assemble():
    """كل البيانات في dict واحد — للنسخ الاحتياطية وأدوات الفحص."""
    # قراءة كاملة من غير ما تطرد أيام الشغل من الكاش
    core = _load(core_path(), core=True)[1]
    data = merge(core, {p.stem: _load(p, cache=False)[1] for p in all_day_files()})
    _attach_change_log(data, core)
    if isinstance(data.get("change_log"), ChangeLogView):
        data["change_log"] = data["change_log"].to_list()      # للتحويل لـJSON (نسخ/أدوات)
    return data


_DAY_STEM = re.compile(r"\d{4}-\d{2}-\d{2}")
_CORE_LISTS = ("leaves", "leave_history", "service_tags", "courses", "course_terms", "vehicles",
               "service_lines", "conscripts", "officer_status_periods",
               "officer_medical_states", "print_collections")
_CORE_DICTS = ("command", "command_groups", "id_seq")
_DAY_TYPES = {
    "assignments": list,
    "officer_states": dict,
    "confirm": dict,
    "status": dict,
    "counts": dict,
    "assignment_seq": int,
    "afraad_basic": dict,
    "weekly_rest_seeded": bool,
    "target_defaults": dict,
    "campaign": dict,
    "service_runs": dict,
    "import": dict,
}


def _invalid(path, why):
    return DataUnreadable(
        f"الملف «{path.name}» ببنية غير صالحة: {why}. لم تُكتب عليه أي بيانات — "
        f"استعد أحدث نسخة سليمة من {BACKUP_DIR_NAME}/."
    )


def _validate_core_shape(core, path):
    schema = core.get("schema", 1)
    if isinstance(schema, bool) or not isinstance(schema, int):
        raise _invalid(path, "رقم البنية «schema» ليس عددًا صحيحًا")
    _check_schema(schema)
    for key in _CORE_LISTS:
        if key in core and not isinstance(core[key], list):
            raise _invalid(path, f"«{key}» يجب أن تكون قائمة")
    for key in _CORE_DICTS:
        if key in core and not isinstance(core[key], dict):
            raise _invalid(path, f"«{key}» يجب أن يكون كائنًا")
    for key in ("officers", "personnel"):
        if key in core and not isinstance(core[key], (list, dict)):
            raise _invalid(path, f"«{key}» يجب أن تكون قائمة أو كائنًا")
    return schema


def resync_all():
    """مزامنة كاملة مع القرص وقت تشغيل النظام: بيكمّل أي معاملة اتقطعت، وينسى كل كاش وفهرس في الذاكرة،
    ويقرا كل الملفات (القوة وكل الأيام وسجل التغييرات) من الأول ويفحصها. بكده أي ملف اتبدّل برّه النظام
    (نسخ من جهاز تاني، استعادة، تعديل يدوي) يتحسب من أول طلب. مابيكتبش حاجة.

    -> dict: status ("ok"|"fresh"|"error")، days، ms، error."""
    started = time.perf_counter()
    try:
        with LOCK:
            recovered = recover_journal()
            _cache.clear()
        result = validate_data(full=True, recover=False)     # بياخد القفل بنفسه
        with LOCK:
            _ensure_index()
        report = {"status": result.get("status", "ok"), "days": result.get("days", 0),
                  "recovered": bool(recovered), "error": None}
    except (DataUnreadable, SchemaMismatch) as exc:
        report = {"status": "error", "days": 0, "recovered": False, "error": str(exc)}
    report["ms"] = tech_log.ms_since(started)
    tech_log.event(LOG, "store.resync", level=logging.ERROR if report["error"] else logging.INFO,
                   **{k: v for k, v in report.items() if v is not None})
    return report


def validate_data(full=True, recover=True):
    """يتحقق من البيانات المضبوطة فعليًا **من غير ما يكتب أي حاجة**.

    بيحمّل `core.json` وملفات الأيام المفهرسة بنفس مسار القراءة الحقيقي،
    ويرمي `SchemaMismatch`/`DataUnreadable` برسالة تسمّي الملف. الاستثناء الوحيد
    الذي يكتب هو تعافي دفتر المعاملات (`recover_journal`) — نفس سلوك أي قراءة.
    مجلد بيانات فاضي تمامًا معناه تثبيت جديد: بيرجّع status="fresh" ومابيبنيش
    بيانات افتراضية (ده بيحصل عند أول استخدام فعلي).

    `full=False` (فحص الجاهزية المتكرر): النواة والفهرس بس — الفهرس بيقرا كل
    ملف يوم مرة واحدة ثم بيعتمد على بصمات الملفات. `full=True` بيفحص كل ملف يوم
    وشكله ومكانه.

    `recover=False` لأدوات الفحص الخارجية لما سيرفر تاني ماسك قفل البيانات —
    ماينفعش عملية تانية تعيد تشغيل دفتر معاملة ممكن يكون شغّال دلوقتي.

    -> dict: status ("ok"|"fresh")، schema، days.
    """
    with LOCK:
        if recover:
            recover_journal()
        core_at = core_path()
        if not core_at.exists():
            if DATA_DIR.exists() and any(DATA_DIR.iterdir()):
                raise DataUnreadable(
                    f"مجلد البيانات «{DATA_DIR.name}» موجود، لكنه لا يحتوي على {CORE_NAME}. "
                    f"استعد نسخة من {BACKUP_DIR_NAME}/."
                )
            legacy = ROOT / "data.json"
            if legacy.exists():
                raise SchemaMismatch(
                    f"لا تزال البيانات في الملف القديم الواحد «{legacy.name}». "
                    f"شغّل migrations/010_split_data_files.py لتفكيكه في مجلد "
                    f"«{DATA_DIR.name}/» (ينشئ نسخة احتياطية قبل الكتابة)."
                )
            return {"status": "fresh", "schema": SCHEMA_VERSION, "days": 0}

        _, core = _load(core_at, core=True, cache=False)
        schema = _validate_core_shape(core, core_at)
        try:
            data = merge(core, {})
            _normalise(data)
        except (TypeError, AttributeError, KeyError, ValueError) as exc:
            raise _invalid(core_at, f"تعذّر تجميع البيانات ({type(exc).__name__})") from exc

        files = all_day_files()
        if full:
            for path in files:
                if not _DAY_STEM.fullmatch(path.stem) or path != day_path(path.stem):
                    raise _invalid(path, "اسم الملف أو مكانه لا يطابق تاريخ اليوم")
                _, blob = _load(path, cache=False)
                if not isinstance(blob, dict):
                    raise _invalid(path, "محتوى ملف اليوم يجب أن يكون كائنًا")
                for name, expected in _DAY_TYPES.items():
                    value = blob.get(name)
                    if name in blob and (isinstance(value, bool) != (expected is bool)
                                         or not isinstance(value, expected)):
                        raise _invalid(path, f"القسم «{name}» ليس بالشكل المتوقع")
        try:
            index = _ensure_index()
        except SchemaMismatch:
            raise
        except (TypeError, AttributeError, KeyError, ValueError) as exc:
            raise DataUnreadable(
                f"تعذّر فهرسة ملفات الأيام ({type(exc).__name__}). "
                f"استعد نسخة من {BACKUP_DIR_NAME}/."
            ) from exc
        return {"status": "ok", "schema": schema, "days": len(index.days())}


def explode(data, _notify=True):
    """بيكتب dict كامل على المجلد — عكس `assemble()`.

    بيمسح ملفات الأيام اللي مش في الـdict عشان الاستعادة تبقى «رجّع
    للحظة دي» بالظبط، مش «دمج فوق اللي موجود».
    """
    existing_days = {path.stem for path in all_day_files()}
    data = dict(data)
    data.setdefault("schema", SCHEMA_VERSION)
    core, days = split(data)
    plan = _plan_core_write(core, None)
    _apply_core_plan(plan)
    if core_dir().is_dir():                     # ملفات قديمة من تقسيم تاني ما تفضلش
        for entry in os.scandir(core_dir()):
            if entry.name.endswith(".json") and entry.name not in plan["parts"]:
                os.unlink(entry.path)
    _write_atomic(change_log_path(), _log_text(data.get("change_log")))
    for path in all_day_files():
        if path.stem not in days:
            _remove_day(path.stem)
    for day, blob in days.items():
        _remove_day(day)                       # نبدأ من يوم نضيف: مفيش ملفات قديمة من شكل تاني تفضل
        _apply_day_plan(day, _plan_day_write(day, blob, None))
    _cache.clear()
    touched_days = frozenset(existing_days | set(days))
    changeset = Changeset(touched_days, touched_days, frozenset(), ALL_CORE_KEYS)
    if _notify:
        _run_after_commit(changeset)
    return changeset


# ---------- النسخ الاحتياطية ----------

def _backup_files(target=None):
    """كل النسخ الاحتياطية مرتبة من الأقدم للأحدث.

    بترجّع الشكلين: `.json.gz` (المضغوط) و`.json` (النسخ القديمة، ونسخ
    ما-قبل-الهجرة اللي migrations/ لسه بتكتبها بدون ضغط). ترتيب الاسم =
    ترتيب زمني لأن الطابع الزمني بعرض ثابت وفي أول الاسم.
    """
    target = backup_dir() if target is None else target
    if not target.exists():
        return []
    return sorted(
        [p for p in target.glob("data-*") if p.suffix in (".json", ".gz", ".zip")],
        key=lambda p: p.name)


def _prune_backups(target=None):
    files = _backup_files(target)
    keep = set(files[-min(10, BACKUP_KEEP):])
    now = datetime.now().timestamp()
    for path in reversed(files[:-min(10, BACKUP_KEEP)]):
        age = now - path.stat().st_mtime
        if age <= 24 * 3600:
            bucket = path.stat().st_mtime // 3600
            if not any(p.stat().st_mtime // 3600 == bucket for p in keep):
                keep.add(path)
        elif age <= 30 * 86400:
            bucket = path.stat().st_mtime // 86400
            if not any(p.stat().st_mtime // 86400 == bucket for p in keep):
                keep.add(path)
    pruned = 0
    for path in files:
        if path not in keep:
            path.unlink(missing_ok=True)
            pruned += 1
    if pruned:
        tech_log.event(LOG, "backup.pruned", removed=pruned, kept=len(keep))


def _read_backup_v2(zf, path):
    """نسخة بالصيغة 2 (ملفات خام) -> نفس الـdict اللي كان بيرجّعه data.json القديم."""
    try:
        if CORE_NAME in zf.namelist():
            core = json.loads(zf.read(CORE_NAME).decode("utf-8"))
        else:
            core = {}
            for name in sorted(zf.namelist()):
                if name.startswith(CORE_DIR_NAME + "/") and name.endswith(".json"):
                    core.update(json.loads(zf.read(name).decode("utf-8")))
        days = {}
        for name in zf.namelist():
            if name.startswith("days/") and name.endswith(".json"):
                member = Path(name)
                # ملف يوم قديم (…/2026-11-16.json) أو ملف جانب من مجلد يوم (…/2026-11-16/assignments.json)
                day = member.stem if _DAY_STEM.fullmatch(member.stem) else member.parent.name
                days.setdefault(day, {}).update(json.loads(zf.read(name).decode("utf-8")))
        data = merge(core, days)
        if CHANGE_LOG_FILE in zf.namelist():
            lines = [line for line in zf.read(CHANGE_LOG_FILE).decode("utf-8").splitlines() if line.strip()]
            data["change_log"] = [json.loads(line) for line in lines[-CHANGE_WINDOW:]]
        elif "change_log" not in data:
            data["change_log"] = []
    except (KeyError, ValueError, UnicodeDecodeError) as exc:
        raise DataUnreadable(f"النسخة «{path.name}» تالفة أو غير مكتملة ({exc}).") from exc
    if not isinstance(data, dict):
        raise DataUnreadable(f"النسخة «{path.name}» ليست بالشكل المتوقع.")
    return data


def read_backup(path):
    """محتوى نسخة احتياطية كـdict — بيفهم المضغوط والعادي.

    بيرمي DataUnreadable لو الملف ناقص أو متقطع أو مش JSON، عشان
    الاستعادة ما تكتبش نسخة تالفة فوق البيانات الشغالة.
    """
    path = Path(path)
    try:
        if path.suffix == ".zip":
            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()
                if "data.json" not in names and (
                        CORE_NAME in names or any(n.startswith(CORE_DIR_NAME + "/") for n in names)):
                    return _read_backup_v2(zf, path)
                raw = zf.read("data.json").decode("utf-8")
        elif path.suffix == ".gz":
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
            f"النسخة «{path.name}» ليست ملف JSON سليمًا (السطر {exc.lineno}).") from exc
    if not isinstance(data, dict):
        raise DataUnreadable(f"النسخة «{path.name}» ليست بالشكل المتوقع.")
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
    # الاسم لازم يطابق حرفيًا ملف في قايمة النسخ نفسها — مش مسار يتركّب.
    # «../data/core.json» أو مجلد اسمه data-x.json كانوا بيعدّوا من `exists()`.
    inventory = {p.name: p for p in _backup_files() if p.is_file()}
    path = inventory.get(name) if isinstance(name, str) else None
    if path is None:
        raise DataUnreadable(f"لا توجد نسخة بالاسم «{name}».")
    data = read_backup(path)              # بيرمي قبل أي كتابة لو تالفة
    _check_schema(data.get("schema", 1))  # ومش بنرجّع بنية الكود مايفهمهاش
    zip_members = []
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as zf:
            uploads_root = (DATA_DIR / "uploads").resolve()
            for member in zf.infolist():
                if member.filename in ("data.json", "manifest.json", CORE_NAME, CHANGE_LOG_FILE) \
                        or member.is_dir() or member.filename.startswith(("days/", CORE_DIR_NAME + "/")):
                    continue
                if not member.filename.startswith("uploads/"):
                    raise DataUnreadable("الأرشيف يحتوي ملفًا خارج data.json أو uploads/.")
                target = (DATA_DIR / member.filename).resolve()
                if uploads_root not in target.parents:
                    raise DataUnreadable("الأرشيف يحتوي مسار مرفق غير آمن.")
                zip_members.append(member)
    old_days = set(day_index().days())
    with LOCK:
        snapshot_now()                    # لقطة للوضع الحالي قبل الاستبدال
        explode(data, _notify=False)
        if path.suffix == ".zip":
            with zipfile.ZipFile(path) as zf:
                if CHANGE_LOG_FILE in zf.namelist():      # سجل التغييرات الكامل بدل النافذة
                    _write_atomic(change_log_path(),
                                  zf.read(CHANGE_LOG_FILE).decode("utf-8"))
                    _cache.clear()
                for member in zip_members:
                    target = (DATA_DIR / member.filename).resolve()
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as source, open(target, "wb") as dest:
                        shutil.copyfileobj(source, dest)
    restored_days = set(day_index().days()) | old_days
    tech_log.event(LOG, "backup.restored", file=name, days=len(restored_days))
    _run_after_commit(Changeset(frozenset(restored_days),
                                frozenset(restored_days),
                                frozenset(), ALL_CORE_KEYS))
    return data


# ---------- قفل العملية الواحدة ----------

LOCK_FILE_NAME = ".lock"
JOURNAL_NAME = ".transaction-journal.json"
_PROCESS_LOCK_FD = None


def _journal_path():
    return DATA_DIR / JOURNAL_NAME

# ---------- سجل التغييرات: ملف append-only خارج core.json ----------
#
# كان `change_log` (5000 سجل ≈ 2MB) جوّه core.json، فكل حفظ كان بيحوّله لنص مرتين
# (core + نسخة logs/ + دفتر المعاملات) — ~70% من وقت أي حفظ. دلوقتي كل تغيير سطر JSON
# بيتضاف في آخر `changes/log.jsonl` (التاريخ كله، مابيتقصّش)، والذاكرة بتشيل آخر
# `CHANGE_WINDOW` سجل بس — نفس سلوك القايمة المسقوفة القديمة، والكود اللي بيقرا
# `data["change_log"]` ما اتغيّرش. الحفظ بيحسب اللي اتضاف بعد آخر سجل اتقرا (بالـid) ويضيفه
# بس، والإضافة نفسها بتتسجّل في دفتر المعاملات بإزاحة متوقعة عشان تتكمّل مرة واحدة بس
# بعد أي انقطاع.

CHANGE_LOG_FILE = "changes/log.jsonl"
CHANGE_WINDOW = 5000
_log_state = {}


def change_log_path():
    return DATA_DIR / CHANGE_LOG_FILE


def _log_line(entry):
    return json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n"


def _log_text(entries):
    return "".join(_log_line(entry) for entry in (entries or []))


def _read_log_tail(path, limit):
    """آخر `limit` سجل من الملف (الأقدم أولًا) من غير قراءته كله. -> (سجلات, حجم الملف)."""
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return [], 0
    if size == 0:
        return [], 0
    block, buf, pos = 1 << 16, b"", size
    with open(path, "rb") as fh:
        while pos > 0 and buf.count(b"\n") <= limit:
            take = min(block, pos)
            pos -= take
            fh.seek(pos)
            buf = fh.read(take) + buf
    lines = buf.split(b"\n")
    if pos > 0:
        lines = lines[1:]          # أول سطر ممكن يبقى ناقص من بدايته
    lines = [line for line in lines if line.strip()][-limit:]
    return [json.loads(line.decode("utf-8")) for line in lines], size


def _log_window():
    """نافذة السجل من الملف (مع كاش بالبصمة) أو None لو الملف مش موجود."""
    path = change_log_path()
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    sig = (stat.st_mtime_ns, stat.st_size)
    with _STATE_LOCK:
        state = _log_state.get("window")
        if state and state["dir"] == str(DATA_DIR) and state["sig"] == sig:
            return state
    entries, size = _read_log_tail(path, CHANGE_WINDOW)
    state = _log_remember_state(entries, sig, size)
    return state


def _log_remember_state(entries, sig, size):
    window = entries[-CHANGE_WINDOW:]
    state = {"dir": str(DATA_DIR), "sig": sig, "size": size, "packed": _pack(window),
             "last_id": window[-1]["id"] if window else None, "count": len(window)}
    with _STATE_LOCK:
        _log_state["window"] = state
    return state


class ChangeLogView(MutableSequence):
    """نافذة سجل التغييرات كقايمة عادية، بس مابتتفكّش من الـpickle إلا لما حد يقراها أو يعدّلها —
    أغلب الطلبات (القراءة) ما بتلمسهاش، فمفيش 10ms فك pickle لـ5000 سجل في كل طلب."""

    __slots__ = ("_packed", "_count", "_list")

    def __init__(self, packed, count):
        self._packed, self._count, self._list = packed, count, None

    @classmethod
    def of(cls, entries):
        view = cls(None, 0)
        view._list = list(entries)
        return view

    @property
    def untouched(self):
        return self._list is None

    def _items(self):
        if self._list is None:
            self._list = pickle.loads(self._packed)
            self._packed = None
        return self._list

    def __len__(self):
        return self._count if self._list is None else len(self._list)

    def __getitem__(self, index):
        return self._items()[index]

    def __setitem__(self, index, value):
        self._items()[index] = value

    def __delitem__(self, index):
        del self._items()[index]

    def insert(self, index, value):
        self._items().insert(index, value)

    def __iter__(self):
        return iter(self._items())

    def __reversed__(self):
        return reversed(self._items())

    def __bool__(self):
        return len(self) > 0

    def __eq__(self, other):
        return list(self._items()) == (list(other._items()) if isinstance(other, ChangeLogView) else other)

    __hash__ = None

    def __repr__(self):
        return f"ChangeLogView({len(self)} entries)"

    def __deepcopy__(self, memo):
        if self._list is None:
            # لسه متفكّتش: الـpickle bytes ثابتة، فكل نسخة بتفكّ قايمتها لوحدها لما تتلمس —
            # من غير فك ونسخ 5000 سجل مع كل deepcopy للقطة (اللوحة/الخدمة بتعمله في كل طلب)
            return ChangeLogView(self._packed, self._count)
        import copy
        return ChangeLogView.of(copy.deepcopy(self._list, memo))

    def __copy__(self):
        return ChangeLogView.of(self._items())

    def to_list(self):
        return list(self._items())


def _legacy_history(window):
    """التاريخ الأقدم من النافذة (من أرشيف التقليم القديم logs/change_log_archive.jsonl) +
    النافذة نفسها — للهجرة الأولى بس، من غير تكرار."""
    seen = {entry.get("id") for entry in window}
    older = []
    try:
        with open(_LOG_DIR / "change_log_archive.jsonl", "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("id") not in seen:
                    seen.add(entry.get("id"))
                    older.append(entry)
    except OSError:
        pass
    return older + list(window)


def _plan_log_write(log, baseline, pending=None):
    """-> None لو مفيش جديد، أو {"mode": "append"|"replace", "text", "offset"}.

    `pending`: السجلات اللي `changes.record` أضافتها في المعاملة دي بالترتيب — بنحتاجها لأن
    النافذة في الذاكرة بتتقصّ من الأول، فمعاملة بتضيف أكتر من سقف النافذة كانت هتفقد أولها."""
    if baseline.get("legacy"):
        # أول حفظ بعد الترقية: السجل كله ينتقل لملفه (مع الأرشيف القديم) في نفس المعاملة
        return {"mode": "replace", "text": _log_text(_legacy_history(log)), "offset": None}
    last_id, count = baseline.get("last_id"), baseline.get("count", 0)
    if last_id is None:
        new = log
    else:
        index = next((i for i in range(len(log) - 1, -1, -1)
                      if log[i].get("id") == last_id), None)
        if index is None:
            # السجل اتعدّل من غير الإضافة (مسح/استبدال): نحتفظ بكل اللي قبل النافذة ونكتب النافذة الجديدة
            try:
                kept = change_log_path().read_text(encoding="utf-8").splitlines()
            except OSError:
                kept = []
            head = kept[:max(0, len(kept) - count)]
            return {"mode": "replace", "offset": None,
                    "text": "".join(line + "\n" for line in head) + _log_text(log)}
        new = log[index + 1:]
    if pending:
        ids = {entry.get("id") for entry in pending}
        new = list(pending) + [entry for entry in new if entry.get("id") not in ids]
    if not new:
        return None
    return {"mode": "append", "text": _log_text(new), "offset": baseline.get("size", 0)}


def _append_log(path, text, offset):
    """إضافة للملف بشرط إنه لسه عند الإزاحة المتوقعة (نفس العملية بتتكرر بأمان من دفتر المعاملات)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = text.encode("utf-8")
    with open(path, "ab+") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        if size == offset:
            pass
        elif size >= offset + len(payload):
            fh.seek(offset)
            if fh.read(len(payload)) == payload:
                return                      # اتنفّذت قبل كده (تعافي بعد انقطاع)
            raise DataUnreadable("سجل التغييرات اتغيّر من خارج المعاملة؛ لا يمكن إضافته بأمان.")
        elif size > offset:
            fh.seek(offset)
            partial = fh.read(size - offset)
            if payload.startswith(partial):
                fh.truncate(offset)          # كتابة ناقصة من انقطاع: نكمّلها من أولها
                size = offset
            else:
                raise DataUnreadable("سجل التغييرات فيه كتابة ناقصة غير متوقعة.")
        else:
            raise DataUnreadable("ملف سجل التغييرات أقصر من المتوقع.")
        fh.seek(offset)
        fh.write(payload)
        fh.flush()
        _fsync_file(fh.fileno(), path)
    _fsync_dir(path.parent)



def _fsync_parent(path):
    _fsync_dir(path.parent)


def _write_journal(operations):
    """Persist the complete intended transaction before touching targets."""
    path = _journal_path()
    payload = json.dumps({"version": 1, "operations": operations},
                         ensure_ascii=False, separators=(",", ":"))
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as fh:
        fh.write(payload.encode("utf-8"))
        fh.flush()
        _fsync_file(fh.fileno(), tmp)
    _replace(tmp, path)
    _fsync_dir(path.parent)


def _clear_journal():
    try:
        _journal_path().unlink()
    except FileNotFoundError:
        return
    _fsync_dir(DATA_DIR)


def recover_journal():
    """Idempotently roll forward an interrupted transaction, if present."""
    path = _journal_path()
    if not path.exists():
        return False
    try:
        payload = json.loads(_read_text(path))
        operations = payload["operations"]
        if payload.get("version") != 1 or not isinstance(operations, list):
            raise ValueError("invalid transaction journal")
        for op in operations:
            target = DATA_DIR / op["target"]
            if op["action"] == "delete":
                target.unlink(missing_ok=True)
                _fsync_dir(target.parent)
            elif op["action"] == "replace":
                _write_atomic(target, op["text"])
            elif op["action"] == "append":
                _append_log(target, op["text"], int(op["offset"]))
            else:
                raise ValueError("unknown transaction operation")
        _clear_journal()
        tech_log.event(LOG, "journal.recovered", level=logging.WARNING,
                       operations=len(operations))
        return True
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        tech_log.event(LOG, "journal.corrupt", level=logging.ERROR, error=type(exc).__name__)
        raise DataUnreadable(f"دفتر المعاملة تالف: {exc}") from exc


def acquire_process_lock():
    """يمنع سيرفرين يشتغلوا على نفس مجلد `data/` في نفس اللحظة.

    `LOCK` فوق بيحمي الكتابة **جوّه** عملية واحدة بس — طلبين في نفس
    اللحظة من المتصفح لنفس السيرفر. من غير القفل ده، سيرفرين شغّالين
    على بورتات مختلفة (أو من جهازين على نفس المجلد المشترك على الشبكة)
    كل واحد فيهم عنده نسخته من `_cache` في الذاكرة، وكتابة من الاتنين
    في نفس اللحظة ممكن تمسح تعديل بعضها من غير ما أي حد ياخد باله —
    نفس المشكلة اللي `with_data()` بيحلّها جوّه العملية الواحدة، بس هنا
    بين عمليتين مختلفتين تمامًا.

    الملف يحمل PID للتشخيص فقط؛ الملكية الفعلية للقفل يحتفظ بها نظام
    التشغيل على واصف الملف، ولذلك يحرره تلقائيًا عند انهيار العملية.

    لازم تتنادى بس لما السيرفر فعلًا بيشتغل (`if __name__ == "__main__"`
    في `app.py`/`serve.py`)، مش وقت `import app` — الاختبارات بتعمل
    `import` للملف من غير ما تشغّل سيرفر حقيقي."""
    global _PROCESS_LOCK_FD
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = DATA_DIR / LOCK_FILE_NAME
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        if os.name == "nt":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, b"0")
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError) as exc:
        os.close(fd)
        tech_log.event(LOG, "process_lock.busy", level=logging.ERROR, data_dir=str(DATA_DIR))
        raise SystemExit(
            "\n[X] النظام قيد التشغيل بالفعل من عملية أخرى على مجلد data/ نفسه.\n"
            "\n    أغلق النسخة الأخرى أولًا، ثم حاول مجددًا.\n"
        ) from exc
    _PROCESS_LOCK_FD = fd
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode())
    os.fsync(fd)
    recover_journal()
    tech_log.event(LOG, "process_lock.acquired", pid=os.getpid(), data_dir=str(DATA_DIR))

    import atexit
    def release():
        global _PROCESS_LOCK_FD
        if _PROCESS_LOCK_FD is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                os.lseek(_PROCESS_LOCK_FD, 0, os.SEEK_SET)
                msvcrt.locking(_PROCESS_LOCK_FD, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(_PROCESS_LOCK_FD, fcntl.LOCK_UN)
        finally:
            os.close(_PROCESS_LOCK_FD)
            _PROCESS_LOCK_FD = None
    atexit.register(release)


# ---------- الواجهة ----------

def load_data(days=ALL_DAYS):
    """لقطة قراءة مستقلة لـ`core.json` + الأيام اللي في `days` بس.

    `days`: قايمة أيام، أو دالة `(ScopeView) -> أيام`، أو `ALL_DAYS`.
    الافتراضي (الأرشيف كله) للأدوات والاستيراد والاختبارات بس — كل مسار
    HTTP بيعلن نطاقه صريح (`tests/test_scoped_storage.py` بيتأكد من ده).
    """
    with LOCK:
        recover_journal()
        return _read(days)


def save_data(data):
    """حفظ مباشر بقفل خاص بيه. لو بتعدّل بيانات محمّلة برّه with_data() فالمفروض
    تستخدم with_data() بدالها عشان تضمن إن حد تاني ما يقرأش/يكتبش في النص."""
    with LOCK:
        recover_journal()
        changeset = _write(data)
    _run_after_commit(changeset)


class AbortRequest(Exception):
    """يتقذف من جوه دالة with_data() للرجوع بخطأ من غير ما يتحفظ أي تعديل."""
    def __init__(self, response):
        self.response = response


def with_data(fn, days=ALL_DAYS):
    """يشغّل fn(data) تحت نفس القفل من التحميل للحفظ كوحدة واحدة ذرية — بيمنع
    فقد تعديل لو جه طلبين في نفس الوقت (كل الوقت السابق كان القفل بيحمي القراءة
    بس، فطلبين ممكن كل واحد يحمّل نسخة، يعدّل، والتاني يمسح تعديل الأول من غير
    قصد). fn بتعدّل data في مكانها وترجّع قيمة استجابة Flask؛ الحفظ بيحصل بس لو
    fn رجعت عادي — ارمي AbortRequest(response) من جواها للرجوع بخطأ من غير حفظ.

    `days` نطاق المعاملة (زي `load_data`): بتقرا وتقارن وتكتب الأيام دي بس."""
    with LOCK:
        recover_journal()
        data = _read(days)
        try:
            result = fn(data)
        except AbortRequest as exc:
            return exc.response
        changeset = _write(data)
        _log_audit()
    _run_after_commit(changeset)
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

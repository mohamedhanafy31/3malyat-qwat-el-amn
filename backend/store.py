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
import shutil
import threading
import time
import zlib
import zipfile
from collections import OrderedDict
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import NamedTuple
from urllib.parse import unquote

from flask import request

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
    # علامة مصدر اليوم المستورد؛ غيابها يعني أن اليوم أُنشئ داخل النظام.
    "day_import": "import",
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
_LOG_DIR = (DATA_DIR / "logs") if _ENV_DATA_DIR is not None else (ROOT / "logs")
_LOG_DIR.mkdir(parents=True, exist_ok=True)
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
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DataUnreadable(
            f"الملف «{path.name}» تالف وتعذّرت قراءته (السطر {exc.lineno}، العمود {exc.colno}). "
            f"لم تُكتب عليه أي بيانات — استعد أحدث نسخة سليمة من {BACKUP_DIR_NAME}/."
        ) from exc
    if not isinstance(data, dict):
        raise DataUnreadable(
            f"الملف «{path.name}» ليس بالشكل المتوقع (وُجد {type(data).__name__} بدلًا من كائن). "
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

def all_day_files():
    """كل ملفات الأيام مرتبة بالتاريخ."""
    if not days_dir().exists():
        return []
    return sorted(days_dir().glob("*/*/*.json"), key=lambda p: p.stem)


def day_names():
    """تواريخ ملفات الأيام الموجودة، مرتبة — من الفهرس، من غير قراءة محتواها."""
    return _ensure_index().days()


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
_index_state = {"dir": None, "entries": None}
INDEX_STATS = {"rebuilds": 0, "repairs": 0}


def _forget_index():
    with _STATE_LOCK:
        _index_state.update(dir=None, entries=None)


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
        files = {p.stem: p for p in all_day_files()}
        if entries is None:
            # البناء الكامل مايملاش الكاش — الأيام المستخدمة فعلًا هي اللي تستاهل الذاكرة
            entries = {day: _meta_from_file(path, cache=False)
                       for day, path in sorted(files.items())}
            _index_state.update(dir=root, entries=entries)
            INDEX_STATS["rebuilds"] += 1
            return DayIndex(entries)
        fresh = None
        for day in entries.keys() - files.keys():
            fresh = fresh if fresh is not None else dict(entries)
            fresh.pop(day, None)
        for day, path in files.items():
            meta = entries.get(day)
            if meta is not None and meta.sig == _file_sig(path):
                continue
            fresh = fresh if fresh is not None else dict(entries)
            fresh[day] = _meta_from_file(path)
        if fresh is not None:
            _index_state["entries"] = fresh
            INDEX_STATS["repairs"] += 1
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
        """ينسى كل اللي في الذاكرة — الكاش والفهرس."""
        with _STATE_LOCK:
            self.days.clear()
            self.core = None
            _forget_index()


_cache = _FileCache(DAY_CACHE_SIZE)


def _pack(value):
    return pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)


def _load_entry(path, core=False, cache=True):
    """-> (_Entry, كائن محلّل جديد أو None لو جه من الكاش). بيعيد القراءة
    بس لما الملف يتغيّر. `cache=False` بيقرا من غير ما يزحم كاش الأيام
    (النسخ الاحتياطي وبناء الفهرس)."""
    with _STATE_LOCK:
        stat = path.stat()
        sig = (stat.st_mtime_ns, stat.st_size)
        key = str(path)
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
    data.setdefault("service_tags", [])
    data.setdefault("courses", [])
    data.setdefault("course_terms", [])
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


def _read(days=ALL_DAYS):
    """قراءة `core.json` والأيام اللي في النطاق بس — من غير قفل، لاستخدامها
    جوه أي بلوك ماسك الـLOCK بالفعل.

    `days`: قايمة أيام، أو دالة `(ScopeView) -> أيام`، أو `ALL_DAYS`.
    الأقسام اليومية في النتيجة فيها أيام النطاق بس، ومحروسة ضد أي يوم
    برّاه (`_ScopedSection`).
    """
    if not core_file().exists():
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
        explode(json.loads(json.dumps(DEFAULT_DATA)))    # نسخة — explode بيعدّل

    core_entry, core = _load(core_file(), core=True)
    _check_schema(core.get("schema", 1))
    data = merge(core, {})
    _normalise(data)

    index = _ensure_index()
    scope = _resolve_scope(days, ScopeView(data, index))
    wanted = index.days() if scope is None else sorted(d for d in scope if d in index)

    originals, fingerprints = {}, {"core": core_entry.fingerprint}
    for day in wanted:
        entry, blob = _load(day_path(day))
        originals[day] = entry.packed
        fingerprints[day] = entry.fingerprint
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
                   "scope": scope, "index": index}
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

def _write(data):
    """بيكتب اللي اتغيّر بس. بيرجّع (الملفات المكتوبة، الملفات المشالة).

    الترتيب مقصود: بنحسب الفرق الأول، بعدين ناخد النسخة الاحتياطية
    (وهي بتقرا القرص، يعني بتلقط الحالة **قبل** التعديل)، وبعدين نكتب.
    لو الكتابة سبقت النسخة كانت النسخة هتبقى صورة من الوضع الجديد —
    يعني مفيش رجوع أصلًا.

    القراءة الجزئية بتقارن أيام نطاقها بس؛ يوم برّا النطاق ليه ملف على
    القرص مايتكتبش فوقه أبدًا (`OutOfScope`) قبل ما أي ملف يتلمس.
    """
    data["schema"] = SCHEMA_VERSION
    tracking = data.get("_fp") or {}
    # قراءة بصمات الشكل القديم تبقى ممكنة لكائن حمّله اختبار أو أداة.
    before = tracking.get("fingerprints", tracking)
    originals = tracking.get("originals", {})
    scope = tracking.get("scope")
    core, days = split(data)

    core_text = _dumps(core)
    core_stamp = _fingerprint(core_text)
    core_changed = core_stamp != before.get("core")
    change_log_text = _change_log_text(core.get("change_log"))

    new_fp = {"core": core_stamp}
    pending = {}
    for day, blob in days.items():
        if scope is not None and day not in scope and day_path(day).exists():
            raise OutOfScope(f"محاولة كتابة اليوم {day} من غير ما يكون في نطاق المعاملة.")
        if day in originals and _pack(blob) == originals[day]:
            new_fp[day] = before[day]
            continue
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
        operations = []
        if core_changed:
            operations.append({"action": "replace", "target": CORE_NAME, "text": core_text})
            operations.append({"action": "replace", "target": CHANGE_LOG_NAME, "text": change_log_text})
        operations.extend({"action": "replace", "target": str(day_path(day).relative_to(DATA_DIR)),
                           "text": text} for day, text in pending.items())
        operations.extend({"action": "delete", "target": str(day_path(day).relative_to(DATA_DIR))}
                           for day in gone)
        _write_journal(operations)
        _snapshot(core_changed=core_changed)

    new_originals = {day: originals[day] for day in days
                     if day in originals and day not in pending}
    try:
        if core_changed:
            _write_atomic(core_file(), core_text)
            _remember(core_file(), core_text, core=True)
            _write_atomic(DATA_DIR / CHANGE_LOG_NAME, change_log_text)
        for day, text in pending.items():
            path = day_path(day)
            _write_atomic(path, text)
            entry, blob = _remember(path, text)
            new_originals[day] = entry.packed
            _index_put(day, _day_meta(entry.sig, blob))
        for day in gone:
            path = day_path(day)
            path.unlink(missing_ok=True)
            with _STATE_LOCK:
                _cache.drop(str(path))
            _index_put(day, None)
    except BaseException:
        _forget_index()                  # كتابة وقعت في النص — يتبني من القرص تاني
        raise
    else:
        if written or removed:
            _clear_journal()

    index = _ensure_index() if scope is not None else tracking.get("index")
    data["_fp"] = {"fingerprints": new_fp, "originals": new_originals,
                   "scope": scope, "index": index}
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
        final = target / f"data-{stamp}.zip"
        part = final.with_suffix(".part")
        with zipfile.ZipFile(part, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            zf.writestr("data.json", _dumps(assemble()))
            uploads = DATA_DIR / "uploads"
            if uploads.exists():
                for source in uploads.rglob("*"):
                    if source.is_file():
                        zf.write(source, source.relative_to(DATA_DIR).as_posix())
        _replace(part, final)
        _fsync_dir(target)
        _prune_backups()
        return final
    except OSError:
        return None    # النسخ الاحتياطي أمان إضافي — فشله ما يمنعش الحفظ


def assemble():
    """كل البيانات في dict واحد — للنسخ الاحتياطية وأدوات الفحص."""
    # قراءة كاملة من غير ما تطرد أيام الشغل من الكاش
    return merge(_load(core_file(), core=True)[1],
                 {p.stem: _load(p, cache=False)[1] for p in all_day_files()})


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
        [p for p in target.glob("data-*") if p.suffix in (".json", ".gz", ".zip")],
        key=lambda p: p.name)


def _prune_backups():
    files = _backup_files()
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
    for path in files:
        if path not in keep:
            path.unlink(missing_ok=True)


def read_backup(path):
    """محتوى نسخة احتياطية كـdict — بيفهم المضغوط والعادي.

    بيرمي DataUnreadable لو الملف ناقص أو متقطع أو مش JSON، عشان
    الاستعادة ما تكتبش نسخة تالفة فوق البيانات الشغالة.
    """
    path = Path(path)
    try:
        if path.suffix == ".zip":
            with zipfile.ZipFile(path) as zf:
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
                if member.filename == "data.json" or member.is_dir():
                    continue
                if not member.filename.startswith("uploads/"):
                    raise DataUnreadable("الأرشيف يحتوي ملفًا خارج data.json أو uploads/.")
                target = (DATA_DIR / member.filename).resolve()
                if uploads_root not in target.parents:
                    raise DataUnreadable("الأرشيف يحتوي مسار مرفق غير آمن.")
                zip_members.append(member)
    with LOCK:
        snapshot_now()                    # لقطة للوضع الحالي قبل الاستبدال
        explode(data)
        if path.suffix == ".zip":
            with zipfile.ZipFile(path) as zf:
                for member in zip_members:
                    target = (DATA_DIR / member.filename).resolve()
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as source, open(target, "wb") as dest:
                        shutil.copyfileobj(source, dest)
    return data


# ---------- قفل العملية الواحدة ----------

LOCK_FILE_NAME = ".lock"
JOURNAL_NAME = ".transaction-journal.json"
CHANGE_LOG_NAME = "logs/change_log.jsonl"
_PROCESS_LOCK_FD = None


def _journal_path():
    return DATA_DIR / JOURNAL_NAME


def _fsync_parent(path):
    _fsync_dir(path.parent)


def _write_journal(operations):
    """Persist the complete intended transaction before touching targets."""
    path = _journal_path()
    payload = _dumps({"version": 1, "operations": operations})
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


def _change_log_text(entries):
    return "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in (entries or []))


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
            else:
                raise ValueError("unknown transaction operation")
        _clear_journal()
        return True
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
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
        raise SystemExit(
            "\n[X] النظام قيد التشغيل بالفعل من عملية أخرى على مجلد data/ نفسه.\n"
            "\n    أغلق النسخة الأخرى أولًا، ثم حاول مجددًا.\n"
        ) from exc
    _PROCESS_LOCK_FD = fd
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode())
    os.fsync(fd)
    recover_journal()

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
        _write(data)


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

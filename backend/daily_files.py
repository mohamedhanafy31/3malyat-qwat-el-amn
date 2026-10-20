"""إدارة مجلد الأرشيف اليومي والملفات الخمسة
التي يولدها النظام.

المجلد يحاكي أرشيف المشغّلين، بينما الملفات الخمسة تُبنى
من بيانات النظام.
"""

import json
import logging
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from . import store
from .settings import get_setting
from .store import ALL_CORE_KEYS

LOG = logging.getLogger(__name__)
KINDS = ("board", "duty", "afraad", "campaign", "counts")
_PATTERNS = {
    "board": re.compile(r"^\d+\.(?:docx|pdf)$"),
    "duty": re.compile(r"^\d+-\d+-\d{4}\.(?:docx|pdf)$"),
    "afraad": re.compile(r"^\d+-\d+-\d{4} افراد\.(?:docx|pdf)$"),
    "campaign": re.compile(r"^يومية الحملة"),
    "counts": re.compile(r"^اعداد الخدمات"),
}
_TEMP_NAMES = {"desktop.ini", "Thumbs.db"}
# أقسام اليوم اللي بتدل إن حد اشتغل على اليوم ده فعلًا. التهيئة التلقائية
# (راحات الأسبوع، الأهداف الافتراضية) بتعمل ملف يوم من غير ما يبقى فيه شغل،
# فوجود الملف لوحده مش دليل.
DATA_SECTIONS = ("day_assignments", "day_officers", "day_afraad", "day_campaign",
                 "service_counts", "day_confirm")


def has_data(day):
    """هل اليوم ده فيه بيانات شغل مسجّلة؟ اليوم الفاضي ملفاته مابتتولّدش."""
    index = store.day_index()
    return any(index.has(day, key) for key in DATA_SECTIONS)


@dataclass(frozen=True)
class DayFilesResult:
    """نتيجة توليد يوم واحد، من غير مفاتيح مختلطة
    مع نتائج الأنواع.

    ``files`` يحتوي نتائج الأنواع فقط، وبيانات النسخ في
    الحقول الأخرى.
    """

    day: str
    folder: str
    cloned_from: str | None
    warnings: tuple[str, ...] = ()
    files: dict = field(default_factory=dict)
    skipped: str = ""


def enabled():
    """هل نظام الملفات اليومية مفعّل؟"""
    setting = get_setting("daily_files_enabled", True)
    value = os.environ.get("DAILY_FILES_ENABLED", setting)
    return str(value).lower() not in {"0", "false", "no", "off"}


def managed_from():
    """أول يوم تديره التحديثات التلقائية."""
    return str(get_setting("daily_files_managed_from", "2026-09-30"))


def daily_files_root():
    """اسم عام متوافق مع أدوات الهجرة القديمة."""
    return root()


def root():
    """جذر أرشيف الملفات.

    متغير البيئة له أولوية إذا كان مسارًا مطلقًا.
    """
    raw = os.environ.get("DAILY_FILES_ROOT") or get_setting("daily_files_root")
    if raw and Path(raw).is_absolute():
        return Path(raw)
    return store.DATA_DIR / "daily_files"


def _date_parts(day):
    value = date.fromisoformat(day)
    return value, str(value.year), str(value.month), str(value.day)


def day_folder(day):
    """مسار اليوم بالعام/الشهر/اليوم بلا أصفار بادئة."""
    _value, year, month, number = _date_parts(day)
    return root() / year / month / number


def file_names(day):
    """الأسماء القانونية للأنواع الخمسة."""
    value, _year, month, number = _date_parts(day)
    year = str(value.year)
    return {
        "board": f"{number}.docx",
        "duty": f"{number}-{month}-{year}.docx",
        "afraad": f"{number}-{month}-{year} افراد.docx",
        "campaign": f"يومية الحملة عن يوم {number}-{month}-{year}.docx",
        "counts": f"اعداد الخدمات يوم {number}-{month}-{year}.xlsx",
    }


def is_daily_file(name):
    """هل الاسم ينتمي إلى أحد أنماط الملفات اليومية؟"""
    return any(pattern.match(str(name)) for pattern in _PATTERNS.values())


def _excluded(source, relative):
    """استثناء ملفات اليوم في المستوى الأعلى.

    ملفات القفل تستثنى في كل مستوى.
    """
    temporary = (
        source.name.startswith("~$")
        or source.name in _TEMP_NAMES
        or source.suffix.lower() == ".tmp"
    )
    return temporary or (
        relative.parent == Path(".") and is_daily_file(source.name)
    )


def _nearest_previous_folder(day):
    requested = date.fromisoformat(day)
    for offset in range(1, 401):
        candidate = day_folder((requested - timedelta(days=offset)).isoformat())
        if candidate.is_dir():
            return candidate
    return None


def _clone_into(source, target, *, only_missing=False):
    """ينسخ محتوى فولدر اليوم السابق ما عدا اليوميات الخمسة و`~$`/tmp.

    `only_missing`: مايكتبش فوق ملف موجود (دمج، للتهجير مرة واحدة).
    أخطاء الملفات الفردية بتتجمّع ومابتمنعش نسخ الباقي.
    """
    warnings, copied = [], 0
    for item in sorted(source.rglob("*")):
        relative = item.relative_to(source)
        destination = target / relative
        if item.is_file() and _excluded(item, relative):
            continue
        try:
            if item.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            elif only_missing and destination.exists():
                continue
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, destination)
                copied += 1
        except OSError as exc:
            warnings.append(f"{relative}: {exc}")
    return warnings, copied


def ensure_day_folder(day):
    """ينشئ مجلد اليوم من أقرب مجلد سابق.

    أخطاء الملفات الفردية تُجمع ولا تمنع نسخ بقية
    المجلد.
    """
    target = day_folder(day)
    if target.exists():
        return target, None, []

    target.mkdir(parents=True, exist_ok=True)
    source = _nearest_previous_folder(day)
    if source is None:
        return target, None, []
    warnings, _copied = _clone_into(source, target)
    return target, source, warnings


def sync_day_folder(day):
    """يكمّل فولدر يوم موجود بالملفات الناقصة من أقرب فولدر سابق (دمج).

    للتهجير الأول بس: فولدر اتعمل قبل ما الأرشيف يتنسخ كان فاضي، فلازم
    يكمّل من اليوم اللي قبله من غير ما يمسح أو يستبدل أي ملف موجود.
    -> (folder, source, copied, warnings)
    """
    target = day_folder(day)
    target.mkdir(parents=True, exist_ok=True)
    source = _nearest_previous_folder(day)
    if source is None:
        return target, None, 0, []
    warnings, copied = _clone_into(source, target, only_missing=True)
    return target, source, copied, warnings


def _manifest_path():
    return root() / ".manifest.json"


def _manifest():
    try:
        value = json.loads(_manifest_path().read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_manifest(value):
    path = _manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporary, path)


def _manifest_signature(signature):
    """JSON لا يحفظ tuple.

    نحول التوقيع إلى شكل ثابت قابل للمقارنة.
    """
    return list(signature) if signature is not None else None


def _write_one(path, data):
    """يكتب ملفًا ذريًا مع إعادة محاولة قفل Word على Windows."""
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        for attempt in range(3):
            try:
                temporary.write_bytes(data)
                os.replace(temporary, path)
                return
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(0.5)
    finally:
        temporary.unlink(missing_ok=True)


def write_day_files(day, kinds=None, *, require_data=False):
    """يولد الأنواع المطلوبة ويرجع نتيجة موحدة.

    العملية قابلة للتكرار الآمن. `require_data`: لو اليوم مالوش بيانات
    مسجّلة بيتعمل فولدره (نسخة من اللي قبله) من غير ما تتولّد اليوميات —
    المشغّل بيدخل بياناته وبعدين يضغط «تحديث الملفات». الطلب الصريح
    (الزرار) مابيستعملش الشرط ده.
    """
    folder, cloned, warnings = ensure_day_folder(day)
    if require_data and not has_data(day):
        return DayFilesResult(day=day, folder=str(folder),
                              cloned_from=str(cloned) if cloned else None,
                              warnings=tuple(warnings), files={}, skipped="no_data")
    selected = KINDS if kinds is None else [kind for kind in kinds if kind in KINDS]
    from . import day_exports

    names = file_names(day)
    files = {}
    for kind in selected:
        path = folder / names[kind]
        try:
            builder = getattr(day_exports, f"build_{kind}_bytes")
            data = builder(day)
            _write_one(path, data)
            for old in folder.iterdir():
                if (
                    old.name != path.name
                    and old.is_file()
                    and _PATTERNS[kind].match(old.name)
                    and old.suffix.lower() != ".pdf"
                ):
                    old.unlink(missing_ok=True)
            files[kind] = {
                "ok": True,
                "path": str(path),
                "bytes": len(data),
                "error": None,
            }
        except Exception as exc:
            LOG.exception("فشل توليد ملف %s لليوم %s", kind, day)
            files[kind] = {
                "ok": False,
                "path": str(path),
                "bytes": 0,
                "error": str(exc),
            }

    try:
        signature = store.day_index().signature(day)
        manifest = _manifest()
        manifest[day] = {
            "sig": _manifest_signature(signature),
            "at": datetime.now().isoformat(timespec="seconds"),
        }
        _write_manifest(manifest)
    except Exception:
        LOG.exception("فشل تحديث manifest للملفات اليومية")

    return DayFilesResult(
        day=day,
        folder=str(folder),
        cloned_from=str(cloned) if cloned else None,
        warnings=tuple(warnings),
        files=files,
    )


class DailyFilesWorker:
    """عامل واحد يدمج الأيام ويمهل حتى يستقر سيل الحفظ."""

    def __init__(self, debounce=3):
        self.debounce = max(0.01, float(debounce))
        self._pending = set()
        self._window_start = None
        self._deadline = None
        self._busy = False
        self._stop = False
        self._condition = threading.Condition()
        self._thread = threading.Thread(
            target=self._run, name="daily-files", daemon=True
        )
        self._thread.start()

    def enqueue(self, days):
        """يضيف الأيام ويمد نافذة debounce.

        الامتداد محدود بثلاثة أضعاف مدة debounce الأصلية.
        """
        now = time.monotonic()
        with self._condition:
            if self._deadline is None:
                self._window_start = now
                self._deadline = now + self.debounce
            else:
                ceiling = self._window_start + self.debounce * 3
                self._deadline = min(now + self.debounce, ceiling)
            self._pending.update(str(day) for day in days)
            self._condition.notify_all()

    def pending(self):
        with self._condition:
            return set(self._pending)

    def flush(self, timeout=10):
        """ينتظر pending والعمل الجاري معًا."""
        end = time.monotonic() + timeout
        with self._condition:
            while self._pending or self._busy:
                remaining = end - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
        return True

    def stop(self):
        with self._condition:
            self._stop = True
            self._condition.notify_all()
        self._thread.join(timeout=2)

    def _run(self):
        while True:
            with self._condition:
                while not self._pending and not self._stop:
                    self._condition.wait()
                if self._stop:
                    return
                remaining = self._deadline - time.monotonic()
                if remaining > 0:
                    self._condition.wait(remaining)
                    continue
                days = sorted(self._pending)
                self._pending.clear()
                self._window_start = None
                self._deadline = None
                self._busy = True

            today = date.today().isoformat()
            days.sort(key=lambda value: (value != today, value))
            for day in days:
                try:
                    write_day_files(day, require_data=True)
                except Exception:
                    LOG.exception("فشل عامل الملفات اليومية في %s", day)
            with self._condition:
                self._busy = False
                self._condition.notify_all()


_worker = None


def _hook(changeset):
    if not enabled() or _worker is None:
        return
    manifest = _manifest()
    today = date.today()
    days = set(changeset.days) | set(changeset.created_days)
    days = {day for day in days if day >= managed_from() or day in manifest}
    noisy = {"change_log", "id_seq", "schema", "inspection_seeded_days"}
    core_dirty = changeset.core_keys and (
        changeset.core_keys == ALL_CORE_KEYS
        or bool(changeset.core_keys - noisy)
    )
    if core_dirty:
        days.update({today.isoformat(), (today + timedelta(days=1)).isoformat()})
        try:
            data = store.load_data(())
            days.update(
                day for day, value in (data.get("day_status") or {}).items()
                if value.get("reopened_on") == today.isoformat()
            )
        except Exception:
            LOG.exception("تعذر فحص الأيام المفتوحة استثنائيًا")
    _worker.enqueue(days)


def start_worker():
    """يشغّل العامل ويسجل hook ويجمع الأيام المتأخرة."""
    global _worker
    if not enabled() or _worker is not None:
        return _worker

    _worker = DailyFilesWorker(get_setting("daily_files_debounce", 3))
    store.register_after_commit(_hook)
    manifest = _manifest()
    index = store.day_index()
    current = date.today()
    stale = {
        day for day in index.days()
        if day >= managed_from()
        and manifest.get(day, {}).get("sig")
        != _manifest_signature(index.signature(day))
    }
    stale.update(
        day for day in manifest
        if day >= managed_from() and day not in index.days()
    )
    stale.update({current.isoformat(), (current + timedelta(days=1)).isoformat()})
    _worker.enqueue(stale)
    return _worker


def request_refresh(days):
    """يطلب تحديث ملفات أيام بعد تغيير مش ظاهر في changeset اليوم نفسه
    (قايمة مرجعية مؤرّخة في core.json مثلًا). مابيعملش حاجة لو النظام متوقف."""
    if _worker is None or not enabled():
        return False
    _worker.enqueue([str(day) for day in days])
    return True


def worker():
    """يرجع العامل الحالي للاختبارات ونقاط الحالة."""
    return _worker

"""طباعة يوميات اليوم من ملفات الأرشيف نفسها عن طريق Word.

طابور واحد في الذاكرة بيطبع بالدور، فمجموعة كل ضابط تطلع ورقها ورا بعض. بعد
إعادة التشغيل الطابور بيبدأ فاضي ومافيش استكمال تلقائي عشان الورق مايتكررش؛
سجل النشاط فيه بداية ونهاية كل شغلانة. «تم» معناها إن Word سلّم الملف لويندوز،
مش إن الورق طلع فعلًا من الطابعة.
"""
import logging
import os
import threading
import time
from collections import deque
from uuid import uuid4

from . import daily_files, tech_log
from .export_preview import _LOCK as OFFICE_LOCK
from .print_collections import PRINT_KINDS

LOG = logging.getLogger(__name__)
DONE_VISIBLE_SECONDS = 5   # علامة «تم» بتفضل المدة دي وبعدين بتختفي
STUCK_AFTER_SECONDS = 120  # ملف بيتطبع أكتر من كده: غالبًا نافذة مخفية موقّفة Word
MAX_COPIES = 20
_KEEP_JOBS = 200
_WD_DO_NOT_SAVE = 0
_MSO_FORCE_DISABLE_MACROS = 3


class PrintUnavailable(RuntimeError):
    """الطباعة مش متاحة على الجهاز ده."""


class _WordSession:
    """نسخة Word مخفية واحدة للشغلانة كلها، بتتقفل في الآخر مهما حصل."""

    def __enter__(self):
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        try:
            self.app = win32com.client.DispatchEx("Word.Application")
            self.app.Visible = False
            self.app.DisplayAlerts = 0
            self.app.AutomationSecurity = _MSO_FORCE_DISABLE_MACROS
        except Exception:
            pythoncom.CoUninitialize()
            raise
        return self

    def print_file(self, path):
        document = self.app.Documents.Open(str(path), ConfirmConversions=False, ReadOnly=True,
                                           AddToRecentFiles=False, Visible=False)
        try:
            # Background=False: النداء مايرجعش غير لما Word يسلّم الملف لويندوز.
            document.PrintOut(Background=False, Copies=1)
        finally:
            document.Close(_WD_DO_NOT_SAVE)

    def __exit__(self, *_exc):
        import pythoncom

        try:
            self.app.Quit()
        finally:
            pythoncom.CoUninitialize()


class _FakeSession:
    """للتطوير على لينكس (`DAILY_PRINT_ENGINE=fake`): بيحاكي الوقت من غير طباعة."""

    def __enter__(self):
        return self

    def print_file(self, path):
        tech_log.event(LOG, "daily_print.fake", name=path.name)
        time.sleep(1.5)

    def __exit__(self, *_exc):
        return None


def _engine_name():
    return os.environ.get("DAILY_PRINT_ENGINE", "word").strip().lower()


def available():
    if _engine_name() == "fake":
        return True
    if os.name != "nt":
        return False
    try:
        import win32com.client  # noqa: F401  (pywin32)
        import win32print  # noqa: F401
    except ImportError:
        return False
    return True


def printer_name():
    if _engine_name() == "fake":
        return "طابعة تجريبية"
    if not available():
        return ""
    try:
        import win32print

        return win32print.GetDefaultPrinter()
    except Exception:
        LOG.warning("تعذر قراءة الطابعة الافتراضية", exc_info=True)
        return ""


def open_session():
    return _FakeSession() if _engine_name() == "fake" else _WordSession()


def document_path(day, kind):
    """المسار القانوني بس: العميل بيبعت النوع والسيرفر هو اللي يحدد الملف."""
    if kind not in PRINT_KINDS:
        raise ValueError(kind)
    name = daily_files.document_name(day, kind)
    folder = daily_files.day_folder(day).resolve()
    path = (folder / name).resolve()
    if path.parent != folder:
        raise ValueError(name)
    return path


def _prepare(day, kind):
    """-> مسار الملف جاهز للطباعة. الناقص بيتولّد لو اليوم فيه بيانات."""
    path = document_path(day, kind)
    if not path.is_file() and daily_files.has_data(day):
        daily_files.write_day_files(day, [kind])
    if not path.is_file():
        raise FileNotFoundError("الملف غير موجود في أرشيف اليوم.")
    return path


class PrintQueue:
    def __init__(self):
        self._condition = threading.Condition()
        self._waiting = deque()
        self._jobs = deque(maxlen=_KEEP_JOBS)
        self._thread = None
        self._running = False

    def submit(self, day, collections, copies, actor, skip_kinds=()):
        """شغلانة جديدة. المجموعة اللي لسه في الطابور بتتجاهل عشان ضغطة مكررة
        ماتطبعش مرتين. النسخ بتكرر المجموعة كاملة: A B C ثم A B C."""
        with self._condition:
            busy = self._active_ids(day)
            accepted = [item for item in collections if item["id"] not in busy]
            items = [{"collection_id": item["id"], "label": item["label"], "kind": kind,
                      "status": "queued", "error": None, "started": None, "finished": None}
                     for item in accepted
                     for _copy in range(copies)
                     for kind in item["kinds"] if kind not in skip_kinds]
            if not items:
                return None
            job = {"id": uuid4().hex[:12], "day": day, "items": items, "actor": actor}
            self._jobs.append(job)
            self._waiting.append(job)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="daily-print", daemon=True)
                self._thread.start()
            self._condition.notify_all()
        return job

    def _active_ids(self, day):
        return {item["collection_id"] for job in self._jobs if job["day"] == day
                for item in job["items"] if item["status"] in ("queued", "printing")}

    def snapshot(self, day):
        """{collection_id: حالة المجموعة وحالة كل ملف فيها} من آخر شغلانة ليها."""
        now = time.monotonic()
        out = {}
        with self._condition:
            for job in self._jobs:
                if job["day"] != day:
                    continue
                groups = {}
                for item in job["items"]:
                    groups.setdefault(item["collection_id"], []).append(item)
                for collection_id, items in groups.items():
                    out[collection_id] = _collection_status(items, now)
        return out

    def wait_idle(self, timeout=10):
        end = time.monotonic() + timeout
        with self._condition:
            while self._waiting or self._running:
                remaining = end - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
        return True

    def clear(self):
        with self._condition:
            self._waiting.clear()
            self._jobs.clear()

    def _run(self):
        while True:
            with self._condition:
                while not self._waiting:
                    self._condition.wait()
                job = self._waiting.popleft()
                self._running = True
            try:
                self._process(job)
            except Exception:
                LOG.exception("فشلت شغلانة الطباعة %s", job["id"])
                self._fail_rest(job, "تعذر تشغيل Microsoft Word للطباعة.")
            with self._condition:
                self._running = False
                self._condition.notify_all()
            _audit_finished(job)

    def _process(self, job):
        worker = daily_files.worker()
        if worker is not None:
            worker.flush(timeout=60)     # أي حفظ قريب يتكتب في الملفات الأول
        with open_session() as session:
            for item in job["items"]:
                self._print_item(session, job["day"], item)

    def _print_item(self, session, day, item):
        with self._condition:
            if item["status"] != "queued":
                return
            item.update(status="printing", started=time.monotonic())
        started = time.perf_counter()
        status, error = "done", None
        try:
            # القفل مابيخليش التحديث التلقائي يستبدل الملف وWord فاتحه.
            with daily_files.ARCHIVE_LOCK, OFFICE_LOCK:
                session.print_file(_prepare(day, item["kind"]))
        except FileNotFoundError as exc:
            status, error = "failed", str(exc)
        except Exception as exc:
            LOG.warning("فشلت طباعة %s ليوم %s", item["kind"], day, exc_info=True)
            status, error = "failed", f"تعذرت الطباعة: {exc}"
        with self._condition:
            item.update(status=status, error=error, finished=time.monotonic())
        tech_log.event(LOG, "daily_print.item", day=day, kind=item["kind"],
                       collection=item["collection_id"], status=status, error=error,
                       duration_ms=tech_log.ms_since(started),
                       level=logging.INFO if status == "done" else logging.WARNING)

    def _fail_rest(self, job, error):
        with self._condition:
            for item in job["items"]:
                if item["status"] in ("queued", "printing"):
                    item.update(status="failed", error=error, finished=time.monotonic())


def _overall(states):
    if "printing" in states:
        return "printing"
    if "queued" in states:
        return "queued"
    return "failed" if "failed" in states else "done"


def _collection_status(items, now):
    state = _overall({item["status"] for item in items})
    # كل مجموعة ليها وقتها: علامة «تم» بتختفي بعد آخر ملف فيها، حتى لو الطابور لسه شغال.
    if state == "done" and now - max(item["finished"] for item in items) > DONE_VISIBLE_SECONDS:
        state = "printed"
    docs = {}
    for kind in dict.fromkeys(item["kind"] for item in items):
        doc_state = _overall({item["status"] for item in items if item["kind"] == kind})
        docs[kind] = "printed" if state == "printed" else doc_state
    stuck = any(item["status"] == "printing" and now - item["started"] > STUCK_AFTER_SECONDS
                for item in items)
    errors = list(dict.fromkeys(f"{PRINT_KINDS[item['kind']]}: {item['error']}"
                                for item in items if item["error"]))
    return {"state": state, "docs": docs, "done": sum(i["status"] == "done" for i in items),
            "total": len(items), "errors": errors, "stuck": stuck}


def _audit_finished(job):
    from .auth.audit_log import emit

    failed = sum(item["status"] != "done" for item in job["items"])
    try:
        emit("daily_print_finished", job_id=job["id"], day=job["day"],
             total=len(job["items"]), failed=failed, requested_by=job["actor"])
    except Exception:
        LOG.warning("تعذر تسجيل نهاية الطباعة", exc_info=True)


QUEUE = PrintQueue()

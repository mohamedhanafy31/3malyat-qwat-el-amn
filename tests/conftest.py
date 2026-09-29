import json
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app as flask_app          # noqa: E402
from backend import day_status            # noqa: E402
from backend import store                 # noqa: E402

# أيام الاختبارات كلها في 2026، والأيام اللي فاتت بتتقفل تلقائيًا
# (backend/day_status.py). من غير تثبيت «النهاردة» كل اختبار بيكتب في يوم
# ثابت كان هيرجع 409 بمجرد ما التاريخ الحقيقي يعدّيه — يعني اختبارات
# بتنجح النهاردة وتقع بكرة. القفل التلقائي نفسه له اختباراته اللي
# بتحرّك اليوم ده صراحة في tests/test_day_close.py.
# القيمة أقدم من أي تاريخ بتلمسه الاختبارات، فكل الأيام «جاية» ومفتوحة.
FROZEN_TODAY = "2019-01-01"


FIXTURE_DATA = {
    # قايمة واحدة لكل فئة و`status` بيفرّق القوة عن الأرشيف (هجرة 008).
    # `store._read()` بيطبّع الشكل القديم برضه، بس الـfixture بيمثّل الشكل
    # الحالي عشان الاختبارات تفشل لو التطبيع اتكسر بدل ما تخبّيه.
    "officers": [
        {"id": "OFF-001", "name": "أحمد محمد", "role": "عقيد", "code": "1",
         "phone": "0100", "join_date": "2020-01-01", "post": "", "status": "active",
         "rest_system": "أسبوعية", "rest_day": "السبت"},
        {"id": "OFF-002", "name": "محمود علي", "role": "نقيب", "code": "2",
         "phone": "0101", "join_date": "2020-01-01", "post": "", "status": "active",
         "rest_system": "—", "rest_day": ""},
    ],
    "personnel": [],
    "leaves": [
        # مفيش `name` — الاسم بيتحلّ من `person_id` (هجرة 007)
        {"id": "LV-001", "person_id": "OFF-001", "type": "أسبوعية",
         "start": "2026-01-10", "end": "2026-01-10", "return_date": "2026-01-11",
         "note": "", "source": "من الأرشيف"},
    ],
    "duties": {},
    "day_services": {},
    "board_categories": ["الخدمات الأساسية", "الأهداف", "الخدمات الطارئة",
                          "أدوار بالإدارة", "المعسكر الفرعي"],
    "service_tags": [],
    "schema": store.SCHEMA_VERSION,
}


@pytest.fixture
def data_file(tmp_path, monkeypatch):
    """يحوّل تخزين البيانات لمجلد مؤقت معزول عن `data/` الحقيقي.

    بيرجّع كائن فيه `.read_text()` عشان الاختبارات اللي بتقرا الملف على
    القرص مباشرة تفضل تقرا **كل** البيانات مجمّعة زي ما كانت لما كان
    ملف واحد — التقسيم تفصيلة تخزين، والاختبار بيتكلم عن البيانات.
    """
    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "data")
    store._cache.clear()
    store.explode(json.loads(json.dumps(FIXTURE_DATA)))
    return _Assembled()


class _Assembled:
    """واجهة `Path`-شبه على البيانات المجمّعة من المجلد.

    الاختبارات القديمة كانت بتقرا وتكتب الملف مباشرة. بدل ما نعيد كتابتها
    كلها عشان تفصيلة تخزين، الكائن ده بيدّيها نفس الواجهة: القراءة بتجمّع
    كل الملفات، والكتابة بتفكّها تاني.
    """

    def read_text(self, encoding="utf-8"):
        return json.dumps(store.assemble(), ensure_ascii=False)

    def read_bytes(self):
        return self.read_text().encode("utf-8")

    def write_text(self, text, encoding="utf-8"):
        store.explode(json.loads(text))

    def exists(self):
        return store.core_file().exists()

    def size(self):
        """مجموع حجم كل ملفات المجلد على القرص."""
        return sum(p.stat().st_size for p in store.DATA_DIR.rglob("*.json"))

    @property
    def parent(self):
        return store.DATA_DIR.parent


@pytest.fixture(autouse=True)
def _isolate_audit_log(tmp_path, monkeypatch):
    """يمنع اختبارات السجل التدقيقي وأرشيف سجل التغييرات (`backend/
    changes.py::_archive_trimmed`) إنهم يكتبوا على `logs/` الحقيقي.

    `_audit_logger` مربوط بمساره وقت الاستيراد، فلازم نبدّل الـhandler
    نفسه؛ `_LOG_DIR` بالعكس بيتقرا من جديد كل نداء (`changes._archive_path`)،
    فتحويل المتغيّر كفاية من غيره."""
    monkeypatch.setattr(store, "_LOG_DIR", tmp_path)
    handler = logging.FileHandler(tmp_path / "audit.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    old_handlers = store._audit_logger.handlers
    store._audit_logger.handlers = [handler]
    yield
    store._audit_logger.handlers = old_handlers
    handler.close()


@pytest.fixture(autouse=True)
def frozen_today(monkeypatch):
    """يثبّت «النهاردة» لحد القفل التلقائي. بترجّع دالة التغيير عشان
    الاختبار اللي بيختبر القفل نفسه يحرّك اليوم زي ما يحب."""
    def set_today(value):
        monkeypatch.setattr(day_status, "today_iso", lambda: value)
    set_today(FROZEN_TODAY)
    return set_today


@pytest.fixture
def client(data_file):
    flask_app.config.update(TESTING=True)
    return flask_app.test_client()

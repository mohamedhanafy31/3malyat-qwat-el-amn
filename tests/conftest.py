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
    """يحوّل تخزين البيانات لملف مؤقت معزول عن data.json الحقيقي طول مدة الاختبار."""
    f = tmp_path / "data.json"
    f.write_text(json.dumps(FIXTURE_DATA, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(store, "DATA_FILE", f)
    return f


@pytest.fixture(autouse=True)
def _isolate_audit_log(tmp_path):
    """يمنع اختبارات السجل التدقيقي إنها تكتب على logs/audit.log الحقيقي."""
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

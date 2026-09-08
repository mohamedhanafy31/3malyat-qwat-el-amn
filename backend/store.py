"""تخزين البيانات — ملف JSON واحد، بقفل خيط وكتابة ذرية (tmp file replace)."""
import json
import threading
from pathlib import Path

from .constants import DEFAULT_DATA

DATA_FILE = Path(__file__).resolve().parent.parent / "data.json"
LOCK = threading.Lock()


def _read():
    """قراءة الملف وتطبيع بنيته — من غير قفل، لاستخدامها جوه أي بلوك ماسك الـ LOCK بالفعل."""
    if not DATA_FILE.exists():
        _write(DEFAULT_DATA)
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return json.loads(json.dumps(DEFAULT_DATA))
    for cat in ("officers", "personnel"):
        data.setdefault(cat, {"active": [], "archive": []})
        data[cat].setdefault("active", [])
        data[cat].setdefault("archive", [])
    data.setdefault("leaves", [])
    data.setdefault("services", [])
    data.setdefault("duties", {})
    data.setdefault("day_services", {})
    data.setdefault("board_categories", list(DEFAULT_DATA["board_categories"]))
    data.setdefault("service_tags", [])
    return data


def _write(data):
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
        return result


def next_id(items, prefix, width=3):
    nums = [int(x["id"].split("-")[-1]) for x in items
            if str(x.get("id", "")).startswith(prefix + "-") and x["id"].split("-")[-1].isdigit()]
    return f"{prefix}-{(max(nums) + 1) if nums else 1:0{width}d}"

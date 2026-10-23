"""أرشيف عيّنات قراءة صور يومية الأفراد — مادة بناء موديل OCR خاص بالنظام بعدين.

كل مرة تتقرا فيها صورة بيتحفظ جنب بيانات النظام:

    data/ocr_samples/<يوم>/<رقم العيّنة>/
        image.<png|jpg|webp>   الصورة اللي اتبعتت للقراءة (بعد القص)
        prediction.json        اللي استخرجه النظام: الخلايا والنص الخام والصفوف والمطابقات
        final.json             الصح بعد مراجعة المشغّل (بيتكتب لما يضغط «تسكين المختار»)

عيّنة من غير `final.json` معناها إن النتيجة اتقرت واتساب من غير تسكين (اتلغت).
في `final.json` كل صف مقروء ليه اختيار المشغّل الفعلي (الخدمة والفرد صباحًا وليلًا)
وعلامة `edited` لو غيّر حاجة عن اقتراح النظام — ده بالظبط الفرق اللي الموديل
هيتعلم منه. الحفظ دايمًا best-effort: أي فشل هنا ما يوقفش القراءة ولا التسكين.
الصور فيها بيانات أفراد، فالمجلد بره git وبيتحفظ على نفس الجهاز بس.
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
from datetime import datetime
from pathlib import Path

from .settings import get_setting

LOG = logging.getLogger(__name__)
_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")
_SUFFIXES = {"png", "jpg", "jpeg", "webp"}


def enabled():
    value = os.environ.get("OCR_SAMPLES_ENABLED", get_setting("ocr_samples_enabled", True))
    return str(value).lower() not in {"0", "false", "no", "off"}


def root():
    from . import store

    return store.DATA_DIR / "ocr_samples"


def _folder(day, sample_id):
    if not _ID.match(str(sample_id or "")):
        return None
    return root() / str(day) / sample_id


def _write_json(path, value):
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temporary, path)


def _actor():
    try:
        from .auth import current_actor

        actor = current_actor()
        return {key: actor.get(key) for key in ("user_id", "username", "role")}
    except Exception:  # خارج سياق طلب
        return {}


def save_prediction(raw, filename, day, payload, services=None):
    """يحفظ الصورة وناتج القراءة. -> رقم العيّنة أو None لو التسجيل متوقف/فشل."""
    if not enabled() or not raw:
        return None
    try:
        sample_id = f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"
        folder = _folder(day, sample_id)
        folder.mkdir(parents=True, exist_ok=True)
        suffix = str(filename or "").rsplit(".", 1)[-1].lower()
        suffix = suffix if suffix in _SUFFIXES else "png"
        (folder / f"image.{suffix}").write_bytes(raw)
        prediction = {key: value for key, value in (payload or {}).items() if key != "overlay_png"}
        _write_json(folder / "prediction.json", {
            "sample_id": sample_id, "day": day, "filename": filename,
            "at": datetime.now().isoformat(timespec="seconds"), "by": _actor(),
            "image": f"image.{suffix}", "bytes": len(raw),
            "services": [{"id": item.get("id"), "name": item.get("name")} for item in services or []],
            "prediction": prediction,
        })
        return sample_id
    except Exception:
        LOG.exception("تعذّر حفظ عيّنة OCR")
        return None


def _person_label(people, person_id):
    person = people.get(person_id) or {}
    return {"id": person_id, "name": person.get("name", ""), "role": person.get("role", "")} if person_id else None


def build_final(sample_id, day, review, services, personnel):
    """الصح بعد المراجعة، جاهز للكتابة. `review`: كل الصفوف المقروءة بما فيهم غير المحددين."""
    folder = _folder(day, sample_id)
    if folder is None or not (folder / "prediction.json").is_file() or not isinstance(review, list):
        return None
    try:
        predicted = json.loads((folder / "prediction.json").read_text(encoding="utf-8"))["prediction"].get("rows") or []
    except (OSError, ValueError, KeyError):
        return None
    names = {item["id"]: item.get("name", "") for item in services or []}
    people = {item["id"]: item for item in personnel or []}
    rows = []
    for item in review[:200]:
        if not isinstance(item, dict) or not isinstance(item.get("index"), int):
            continue
        index = item["index"]
        source = predicted[index] if 0 <= index < len(predicted) else {}
        service_id = str(item.get("service_id") or "")
        morning = str(item.get("morning_person_id") or "")
        night = str(item.get("night_person_id") or "")
        suggested = (source.get("service_id") or "", (source.get("morning_match") or {}).get("id") or "",
                     (source.get("night_match") or {}).get("id") or "")
        rows.append({
            "index": index, "selected": bool(item.get("selected")),
            "read": {"service": source.get("service"), "morning": source.get("morning"),
                     "evening": source.get("evening")},
            "service": {"id": service_id, "name": names.get(service_id, "")},
            "morning": _person_label(people, morning), "night": _person_label(people, night),
            "edited": (service_id, morning, night) != suggested,
        })
    return {"folder": folder, "final": {
        "sample_id": sample_id, "day": day, "at": datetime.now().isoformat(timespec="seconds"),
        "by": _actor(), "applied": True, "rows": rows}}


def save_final(built):
    if not built:
        return False
    try:
        _write_json(built["folder"] / "final.json", built["final"])
        return True
    except Exception:
        LOG.exception("تعذّر حفظ نتيجة مراجعة OCR")
        return False

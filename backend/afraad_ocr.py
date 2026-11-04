"""OCR import for the daily personnel roster.

The image pipeline deliberately stops at cells.  This module adds the domain
layer: it reconstructs rows, aligns them with the dated list of basic
services, suggests active personnel, and applies only the selections the user
confirmed in the preview.
"""
from __future__ import annotations

import base64
from collections import Counter
from difflib import SequenceMatcher
from io import BytesIO
import logging
import re
import time

from . import tech_log
from .afraad import set_basic_entry
from .dated import afraad_basic_on
from .repo import PeopleRepo
from .text import norm, norm_name

LOG = logging.getLogger(__name__)

ALLOWED_IMAGE_SUFFIXES = {"png", "jpg", "jpeg", "webp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_PHONE = re.compile(r"(?:\+?20)?0?1[0125][\d\s\-]{7,12}")
_NON_NAME = re.compile(r"[^\u0600-\u06ff\w]+")
_RANK_TOKENS = {
    "ا", "ش", "اش", "م", "مش", "معاون", "امين", "مساعد", "رقيب",
    "مندوب", "عريف", "شرطي", "مراقب", "اول", "ثان", "ثالث", "ممتاز",
    "ع", "ن", "ص", "ملازم", "نقيب", "رايد", "مقدم", "عقيد", "عميد",
}


def _normalized(value):
    return norm(str(value or "").translate(_DIGITS))


def _number_tokens(value):
    return set(re.findall(r"\d+", _normalized(value)))


def _service_score(observed, expected):
    left, right = _normalized(observed), _normalized(expected)
    if not left or not right:
        return 0.0
    seq = SequenceMatcher(None, left, right).ratio()
    a, b = set(left.split()), set(right.split())
    overlap = len(a & b)
    token_f1 = (2 * overlap / (len(a) + len(b))) if a and b else 0.0
    score = max(seq, token_f1)
    left_numbers, right_numbers = _number_tokens(left), _number_tokens(right)
    if left_numbers and right_numbers and left_numbers != right_numbers:
        score = min(score, 0.55)
    return score


def _service_rankings(text, services):
    ranked = sorted(
        ((_service_score(text, item["name"]), index, item) for index, item in enumerate(services)),
        key=lambda value: value[0], reverse=True,
    )
    return ranked


def _person_tokens(value):
    value = _PHONE.sub(" ", str(value or ""))
    value = _NON_NAME.sub(" ", value)
    return [token for token in norm_name(value).split()
            if len(token) > 1 and token not in _RANK_TOKENS and not token.isdigit()]


def _token_similarity(left, right):
    """تشابه كلمتين؛ أقل من 0.8 غالبًا اسمين مختلفين (عبدالحفيظ/عبدالرؤوف)
    مش غلطة قراءة حرف (عبدالحفيظ/عبدالحفبظ)، فبيتحسب صفر. والتشابه غير
    التام بيتخصم منه عشان الكلمة المطابقة حرفيًا تكسب (عبدالحي ≠ عبدالحفيظ)."""
    if left == right:
        return 1.0
    ratio = SequenceMatcher(None, left, right).ratio()
    return ratio * 0.85 if ratio >= 0.8 else 0.0


def _ordered_similarity(wanted, actual):
    """أفضل محاذاة لكلمات المقروء على كلمات الاسم المسجّل بنفس الترتيب
    (ممكن نتخطى كلمات من المسجّل). «السيد علي السيد» تتحاذى كاملة على
    «السيد علي السيد علي محمد» لكن مش على «محمد اشرف فتوح علي السيد»."""
    rows, cols = len(wanted), len(actual)
    table = [[0.0] * (cols + 1) for _ in range(rows + 1)]
    for i in range(1, rows + 1):
        for j in range(1, cols + 1):
            similarity = _token_similarity(wanted[i - 1], actual[j - 1])
            table[i][j] = max(table[i - 1][j], table[i][j - 1],
                              table[i - 1][j - 1] + similarity)
    return table[rows][cols] / rows


def _person_score(observed, person):
    """الاسم في الكشف بيتكتب بنفس ترتيب الاسم المسجّل (الاسم ثم الأب ثم
    الجد) وغالبًا أول كلمتين أو تلاتة منه. فالترتيب جزء من المطابقة: مقارنة
    الكلمات كـ«شنطة» بدون ترتيب كانت بتدّي 100% لتلات أشخاص مختلفين."""
    phone = re.sub(r"\D", "", str(person.get("phone") or ""))
    observed_digits = re.sub(r"\D", "", str(observed or ""))
    if len(phone) >= 8 and phone in observed_digits:
        return 1.0, "phone"
    wanted = _person_tokens(observed)
    actual = _person_tokens(person.get("name"))
    if not wanted or not actual:
        return 0.0, "name"
    prefix = sum(_token_similarity(token, candidate)
                 for token, candidate in zip(wanted, actual)) / len(wanted)
    ordered = _ordered_similarity(wanted, actual)
    exact = sum(1 for token in wanted if token in actual) / len(wanted)
    length_bonus = min(1.0, len(wanted) / 3)
    score = 0.30 * prefix + 0.35 * ordered + 0.25 * exact + 0.10 * length_bonus
    return score, "name"


# أقل درجة نقترح عندها أقرب اسم بدل ما نسيب الخانة فاضية — المستخدم بيراجع.
SUGGEST_MIN = 0.50


def _person_match(text, personnel):
    """بيختار دايمًا أقرب اسم (لو فوق SUGGEST_MIN) عشان المستخدم يراجع
    بدل ما يدوّر بنفسه؛ و`confident` بتقول لو الاختيار واضح ومش محتاج نظرة."""
    empty = {"text": str(text or "").strip(), "matched": False, "confident": False, "candidates": []}
    if not _person_tokens(text):
        return empty
    ranked = sorted(
        ((*_person_score(text, person), index, person) for index, person in enumerate(personnel)),
        key=lambda value: (-value[0], value[2]),
    )
    if not ranked:
        return empty
    candidates = [{"id": person["id"], "name": person.get("name", ""),
                   "role": person.get("role", ""), "score": round(score, 3)}
                  for score, _reason, _index, person in ranked[:3]]
    score, reason, _index, person = ranked[0]
    runner = ranked[1][0] if len(ranked) > 1 else 0.0
    confident = reason == "phone" or (score >= 0.80 and score - runner >= 0.06) \
        or (score >= 0.92 and score - runner >= 0.03)
    matched = confident or score >= SUGGEST_MIN
    return {
        "text": str(text or "").strip(), "matched": matched, "confident": confident,
        "id": person["id"] if matched else "", "name": person.get("name", "") if matched else "",
        "score": round(score, 3), "reason": reason, "candidates": candidates,
    }


def _rows_from_cells(cells):
    rows = {}
    for cell in cells or []:
        semantic = cell.get("semantic")
        if semantic not in {"schedule", "evening", "morning", "service", "code"}:
            continue
        row = rows.setdefault(int(cell.get("row", 0)), {"grid_row": int(cell.get("row", 0))})
        row[semantic] = str(cell.get("text") or "").strip()
        row[f"{semantic}_confidence"] = float(cell.get("confidence") or 0)
    return [rows[key] for key in sorted(rows)]


def _align_services(rows, services):
    """Use strong textual anchors to infer the fixed service-row offset.

    The source form has a stable 22-row basic section.  Order inference can
    recover a badly recognized service cell, but only after at least four
    unambiguous anchors agree on the same offset.
    """
    anchors = []
    rankings = {}
    for row in rows:
        ranked = _service_rankings(row.get("service", ""), services)
        rankings[row["grid_row"]] = ranked
        if not ranked:
            continue
        top = ranked[0]
        runner = ranked[1][0] if len(ranked) > 1 else 0.0
        if top[0] >= 0.72 and top[0] - runner >= 0.07:
            anchors.append(row["grid_row"] - top[1])
    offset = None
    if anchors:
        value, count = Counter(anchors).most_common(1)[0]
        if count >= 4:
            offset = value

    aligned = []
    used = set()
    for row in rows:
        ranked = rankings[row["grid_row"]]
        top = ranked[0] if ranked else (0.0, -1, None)
        service_index = row["grid_row"] - offset if offset is not None else top[1]
        inferred = offset is not None
        if not (0 <= service_index < len(services)):
            continue
        item = services[service_index]
        score = _service_score(row.get("service", ""), item["name"])
        if not inferred:
            runner = ranked[1][0] if len(ranked) > 1 else 0.0
            if score < 0.62 or score - runner < 0.06:
                continue
        if item["id"] in used:
            continue
        used.add(item["id"])
        aligned.append({**row, "service_id": item["id"], "service_name": item["name"],
                        "service_score": round(score, 3), "service_inferred_by_order": inferred})
    return aligned, offset


_WARNING_CODES = (
    ("perspective", "منظور"), ("raw_fallback", "OCR الخام"), ("indra_unavailable", "Indra OCR"),
    ("paddle_raw", "PaddleOCR"), ("cells_failed", "تعذر OCR للخلايا"),
)


def _warning_code(text):
    """كود ثابت للتحذير — نص التحذير نفسه ممكن يشمل رسالة محرك، فمش بنسجّله."""
    text = str(text or "")
    for code, needle in _WARNING_CODES:
        if needle in text:
            return code
    return "grid" if text else "other"


def _score_stats(matches):
    scores = [m["score"] for m in matches if m.get("score") is not None]
    return (round(min(scores), 3), round(sum(scores) / len(scores), 3)) if scores else (None, None)


def _log_matching(output, aligned_count, detected, offset, inferred, align_ms, match_ms):
    slots = [m for row in output for m in (row["morning_match"], row["night_match"]) if m.get("text")]
    matched = [m for m in slots if m.get("matched")]
    confident = [m for m in slots if m.get("confident")]
    low, avg = _score_stats(matched)
    tech_log.ocr_event(
        "ocr.align", detected_rows=detected, aligned_rows=aligned_count,
        row_offset=offset, inferred_by_order=inferred, duration_ms=align_ms)
    tech_log.ocr_event(
        "ocr.match", slots_read=len(slots), matched=len(matched), confident=len(confident),
        suggested_only=len(matched) - len(confident), unmatched=len(slots) - len(matched),
        score_min=low, score_avg=avg, rows_ready=sum(1 for r in output if r["confident"]),
        duration_ms=match_ms)
    if logging.getLogger(tech_log.OCR_LOGGER).isEnabledFor(logging.DEBUG):
        for row in output:       # معرّفات فقط
            for slot, key in (("morning", "morning_match"), ("night", "night_match")):
                match = row[key]
                if match.get("text"):
                    tech_log.ocr_event(
                        "ocr.match_row", level=logging.DEBUG, service_id=row.get("service_id"),
                        slot=slot, person_id=match.get("id") or None, score=match.get("score"),
                        confident=match.get("confident"))


def analyze_image(raw, filename, data, day, pipeline=None):
    if not raw:
        raise ValueError("اختر صورة أولاً.")
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("حجم الصورة أكبر من 10 ميجابايت.")
    suffix = str(filename or "").rsplit(".", 1)[-1].lower()
    if suffix not in ALLOWED_IMAGE_SUFFIXES:
        raise ValueError("الصيغة غير مدعومة. استخدم PNG أو JPG أو JPEG أو WEBP.")
    tech_log.ocr_stage("decode")
    decode_started = time.perf_counter()
    try:
        from PIL import Image, UnidentifiedImageError
        import cv2
        import numpy as np
        with Image.open(BytesIO(raw)) as image:
            image.verify()
        with Image.open(BytesIO(raw)) as image:
            image = image.convert("RGB")
            if image.width * image.height > 20_000_000:
                raise ValueError("أبعاد الصورة أكبر من الحد المسموح.")
            bgr = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
    except ImportError as exc:
        raise RuntimeError("مكونات OCR غير مثبتة. شغّل تجهيز حزم OCR أولاً.") from exc
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValueError("الملف ليس صورة صالحة.") from exc

    tech_log.ocr_event("ocr.decode", bytes=len(raw), ext=suffix, width=int(bgr.shape[1]),
                       height=int(bgr.shape[0]), duration_ms=tech_log.ms_since(decode_started))
    if pipeline is None:
        from .afraad_ocr_pipeline import TableOCRPipeline
        pipeline = TableOCRPipeline()
    tech_log.ocr_stage("pipeline")
    started = time.perf_counter()
    result = pipeline.run(bgr)
    engines = {}
    for cell in result.cells or []:
        engines[cell.get("engine")] = engines.get(cell.get("engine"), 0) + 1
    tech_log.ocr_event("ocr.analyze", day=day, mode=result.mode, grid_ok=result.ok,
                   cells=len(result.cells or []), fallback_cells=sum(
                       1 for c in result.cells or [] if c.get("fallback")),
                   engines=",".join(f"{k}:{v}" for k, v in sorted(engines.items(), key=str)) or None,
                   raw_engine=getattr(result.raw_ocr, "engine", None),
                   warnings=len(result.warnings or []),
                   image_bytes=len(raw), duration_ms=tech_log.ms_since(started))
    if result.warnings:
        tech_log.ocr_event("ocr.warnings", level=logging.WARNING, count=len(result.warnings),
                           codes=",".join(sorted({_warning_code(w) for w in result.warnings})))
    tech_log.ocr_stage("matching")
    payload = result.as_dict()
    payload["overlay_png"] = ("data:image/png;base64," +
                              base64.b64encode(result.grid.overlay_png).decode("ascii")) \
        if result.grid.overlay_png else None
    services = afraad_basic_on(data, day)
    personnel = [person.as_dict() for person in PeopleRepo(data).on_force(day, "personnel")]
    align_started = time.perf_counter()
    detected_rows = _rows_from_cells(result.cells)
    aligned, offset = _align_services(detected_rows, services)
    align_ms = tech_log.ms_since(align_started)
    match_started = time.perf_counter()
    output = []
    for row in aligned:
        morning = _person_match(row.get("morning", ""), personnel)
        night = _person_match(row.get("evening", ""), personnel)
        slots = [match for match in (morning, night) if match.get("text")]
        output.append({**row, "morning_match": morning, "night_match": night,
                       "auto_selected": bool(row.get("service_id") and
                                             (morning.get("matched") or night.get("matched"))),
                       # جاهز من غير مراجعة: كل خانة مقروءة اتطابقت بثقة.
                       "confident": bool(row.get("service_id") and slots and
                                         all(match.get("confident") for match in slots))})
    _log_matching(output, len(aligned), len(detected_rows), offset,
                  sum(1 for r in aligned if r.get("service_inferred_by_order")),
                  align_ms, tech_log.ms_since(match_started))
    payload.update(rows=output, row_offset=offset,
                   summary={"detected_rows": len(_rows_from_cells(result.cells)),
                            "matched_services": len(output),
                            "matched_people": sum(bool(r["morning_match"].get("matched")) +
                                                  bool(r["night_match"].get("matched")) for r in output)})
    return payload


def apply_rows(data, day, rows):
    if not isinstance(rows, list) or len(rows) > 22:
        return None, "قائمة نتائج OCR غير صالحة."
    services = {item["id"] for item in afraad_basic_on(data, day)}
    active = {person.id for person in PeopleRepo(data).on_force(day, "personnel")}
    seen, applied = set(), 0
    for row in rows:
        if not isinstance(row, dict):
            return None, "أحد صفوف OCR غير صالح."
        service_id = str(row.get("service_id") or "").strip()
        if service_id not in services or service_id in seen:
            return None, "الخدمة المختارة غير صالحة أو مكررة."
        seen.add(service_id)
        payload = {}
        for source, target in (("morning_person_id", "morning_person_id"),
                               ("night_person_id", "night_person_id")):
            person_id = str(row.get(source) or "").strip()
            if not person_id:
                continue
            if person_id not in active:
                return None, "أحد الأفراد المختارين ليس على القوة في هذا اليوم."
            payload[target] = person_id
        if not payload:
            continue
        _entry, error, _status = set_basic_entry(data, day, service_id, payload)
        if error:
            return None, error
        applied += len(payload)
    if not applied:
        return None, "لم تختر أي فرد لتسكينه."
    return applied, None

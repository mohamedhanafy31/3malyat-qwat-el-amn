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
import re

from .afraad import set_basic_entry
from .dated import afraad_basic_on
from .repo import PeopleRepo
from .text import norm, norm_name


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


def _person_score(observed, person):
    phone = re.sub(r"\D", "", str(person.get("phone") or ""))
    observed_digits = re.sub(r"\D", "", str(observed or ""))
    if len(phone) >= 8 and phone in observed_digits:
        return 1.0, "phone"
    wanted = _person_tokens(observed)
    actual = _person_tokens(person.get("name"))
    if not wanted or not actual:
        return 0.0, "name"
    best = [max(SequenceMatcher(None, token, candidate).ratio() for candidate in actual)
            for token in wanted]
    exact = sum(1 for token in wanted if token in actual) / len(wanted)
    length_bonus = min(1.0, len(wanted) / 3)
    return 0.55 * (sum(best) / len(best)) + 0.25 * exact + 0.20 * length_bonus, "name"


def _person_match(text, personnel):
    if not _person_tokens(text):
        return {"text": str(text or "").strip(), "matched": False, "candidates": []}
    ranked = sorted(
        ((*_person_score(text, person), person) for person in personnel),
        key=lambda value: value[0], reverse=True,
    )
    candidates = [{"id": person["id"], "name": person.get("name", ""),
                   "role": person.get("role", ""), "score": round(score, 3)}
                  for score, _reason, person in ranked[:3]]
    if not ranked:
        return {"text": str(text or "").strip(), "matched": False, "candidates": []}
    score, reason, person = ranked[0]
    runner = ranked[1][0] if len(ranked) > 1 else 0.0
    matched = reason == "phone" or (score >= 0.70 and score - runner >= 0.06) \
        or (score >= 0.86 and score - runner >= 0.03)
    return {
        "text": str(text or "").strip(), "matched": matched,
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


def analyze_image(raw, filename, data, day, pipeline=None):
    if not raw:
        raise ValueError("اختر صورة أولاً.")
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("حجم الصورة أكبر من 10 ميجابايت.")
    suffix = str(filename or "").rsplit(".", 1)[-1].lower()
    if suffix not in ALLOWED_IMAGE_SUFFIXES:
        raise ValueError("الصيغة غير مدعومة. استخدم PNG أو JPG أو JPEG أو WEBP.")
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

    if pipeline is None:
        from .afraad_ocr_pipeline import TableOCRPipeline
        pipeline = TableOCRPipeline()
    result = pipeline.run(bgr)
    payload = result.as_dict()
    payload["overlay_png"] = ("data:image/png;base64," +
                              base64.b64encode(result.grid.overlay_png).decode("ascii")) \
        if result.grid.overlay_png else None
    services = afraad_basic_on(data, day)
    personnel = [person.as_dict() for person in PeopleRepo(data).on_force(day, "personnel")]
    aligned, offset = _align_services(_rows_from_cells(result.cells), services)
    output = []
    for row in aligned:
        morning = _person_match(row.get("morning", ""), personnel)
        night = _person_match(row.get("evening", ""), personnel)
        output.append({**row, "morning_match": morning, "night_match": night,
                       "auto_selected": bool(row.get("service_id") and
                                             (morning.get("matched") or night.get("matched")))})
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

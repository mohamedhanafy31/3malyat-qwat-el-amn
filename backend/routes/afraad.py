"""يومية الأفراد — API القراءة اليومية وتعديل القائم بها/التليفون/
الانتظام على خدمة أساسية واحدة ليوم بعينه."""
import logging
import time

from flask import Blueprint, g, jsonify, request, send_file

from .. import day_status
from ..dated import afraad_basic_on
from ..afraad import (add_basic_service, build_afraad, remove_basic_service,
                       set_basic_entry, update_basic_service)
from .. import ocr_client_log, ocr_samples, tech_log
from ..afraad_ocr import analyze_image, apply_rows
from ..afraad_export import build_docx
from ..repo import PeopleRepo
from ..store import AbortRequest, load_data, revision, stale_revision, with_data
from ..utils import canonical_day, json_payload

bp = Blueprint("afraad", __name__)


def _payload(data, day):
    value = build_afraad(data, day)
    value["revision"] = revision(data, [day])
    return value


def _afraad_scope(day):
    """Current day plus the latest earlier day that can supply stable columns."""
    def scope(view):
        previous = [value for value in view.index.days_with("day_afraad", end=day)
                    if value < day]
        return {day, *(previous[-1:] if previous else [])}
    return scope


@bp.get("/api/afraad/<day>")
def get_afraad(day):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    return jsonify(_payload(load_data(_afraad_scope(day)), day))


@bp.get("/api/afraad/<day>/export.docx")
def export_afraad_docx(day):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    afraad = build_afraad(load_data(_afraad_scope(day)), day)
    buf = build_docx(afraad)
    return send_file(buf, as_attachment=True, download_name=f"يومية الأفراد {day}.docx",
                     mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@bp.put("/api/afraad/<day>/basic/<entry_id>")
def put_afraad_basic(day, entry_id):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    payload = json_payload()

    def mutate(data):
        ok, err = day_status.check_open(data, day)
        if not ok:
            raise AbortRequest((jsonify({"error": err}), 409))
        _ov, error, status = set_basic_entry(data, day, entry_id, payload)
        if error:
            raise AbortRequest((jsonify({"error": error}), status))
        return jsonify(_payload(data, day))

    return with_data(mutate, _afraad_scope(day))


def _refresh_basic_days(day):
    from .. import daily_files
    from ..store import day_index
    managed = daily_files.managed_from()
    days = {day}
    days.update(value for value in day_index().days()
                if value >= day and value >= managed)
    daily_files.request_refresh(sorted(days))


def _write_basic_list(day, body, fn):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400

    def mutate(data):
        ok, err = day_status.check_open(data, day)
        if not ok:
            raise AbortRequest((jsonify({"error": err}), 409))
        stale = stale_revision(data, body.get("revision"), [day])
        if stale:
            raise AbortRequest((jsonify({"error": "تغيّرت اليومية؛ حدّث الصفحة.",
                                         "code": "stale_revision", "revision": stale}), 409))
        _ident, error, status = fn(data)
        if error:
            raise AbortRequest((jsonify({"error": error}), status))
        return jsonify(_payload(data, day))

    response = with_data(mutate, _afraad_scope(day))
    status_code = response.status_code if hasattr(response, "status_code") else response[1]
    if status_code == 200:
        _refresh_basic_days(day)
    return response


@bp.post("/api/afraad/<day>/basic-services")
def add_afraad_basic_service(day):
    body = json_payload()
    return _write_basic_list(day, body, lambda data: add_basic_service(
        data, canonical_day(day), body.get("name")))


@bp.put("/api/afraad/<day>/basic-services/<entry_id>")
def put_afraad_basic_definition(day, entry_id):
    body = json_payload()
    return _write_basic_list(day, body, lambda data: update_basic_service(
        data, canonical_day(day), entry_id, body))


@bp.delete("/api/afraad/<day>/basic-services/<entry_id>")
def delete_afraad_basic_service(day, entry_id):
    body = json_payload()
    return _write_basic_list(day, body, lambda data: remove_basic_service(
        data, canonical_day(day), entry_id))


def _begin_ocr(day, supplied):
    """يثبّت ocr_session واليوم على الطلب الحالي (سيشن العميل لو سليم، وإلا يتولّد)."""
    g.ocr_session = ocr_client_log.clean_session(supplied) or ocr_client_log.new_session()
    g.ocr_day = day
    g.ocr_stage = "request"


@bp.post("/api/afraad/<day>/ocr/client-log")
def log_afraad_ocr_client(day):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    if (request.content_length or 0) > ocr_client_log.MAX_BODY_BYTES:
        return jsonify({"error": "الطلب كبير.", "code": "too_large"}), 413
    body = request.get_json(silent=True)
    events = body.get("events") if isinstance(body, dict) else None
    if not isinstance(events, list) or len(events) > ocr_client_log.MAX_EVENTS:
        return jsonify({"error": "قائمة الأحداث غير صالحة.", "code": "invalid"}), 400
    _begin_ocr(day, body.get("ocr_session"))
    clean = ocr_client_log.sanitize(events)
    ocr_client_log.log_events(clean)
    return jsonify({"logged": len(clean)})


@bp.post("/api/afraad/<day>/ocr/preview")
def preview_afraad_ocr(day):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    _begin_ocr(day, request.form.get("ocr_session"))
    upload = request.files.get("image")
    if upload is None or not upload.filename:
        tech_log.ocr_event("ocr.preview_rejected", level=logging.WARNING, reason="no_file")
        return jsonify({"error": "اختر صورة أولاً."}), 400
    started = time.perf_counter()
    data = load_data(_afraad_scope(day))
    raw = upload.read()
    source = request.form.get("source") if request.form.get("source") in ("image", "pdf") else None
    page = request.form.get("page", "")
    tech_log.ocr_event(
        "ocr.preview_received", bytes=len(raw), content_type=upload.mimetype,
        ext=str(upload.filename).rsplit(".", 1)[-1].lower()[:5], source=source,
        page=int(page) if page.isdigit() and len(page) < 5 else None,
        client_supplied=bool(ocr_client_log.clean_session(request.form.get("ocr_session"))))
    try:
        result = analyze_image(raw, upload.filename, data, day)
    except ValueError as exc:
        tech_log.ocr_event("ocr.preview_rejected", level=logging.WARNING, reason="invalid_input",
                           stage=g.get("ocr_stage"), duration_ms=tech_log.ms_since(started))
        return jsonify({"error": str(exc)}), 400
    except RuntimeError as exc:
        tech_log.ocr_event("ocr.preview_failed", level=logging.ERROR, exc_info=True,
                           stage=g.get("ocr_stage"), status=503, duration_ms=tech_log.ms_since(started))
        return jsonify({"error": str(exc)}), 503
    except Exception:
        tech_log.ocr_event("ocr.preview_failed", level=logging.ERROR, exc_info=True,
                           stage=g.get("ocr_stage"), status=500, duration_ms=tech_log.ms_since(started))
        raise
    result["revision"] = revision(data, [day])
    # الصورة وناتج القراءة بيتحفظوا لبناء موديل OCR خاص بالنظام بعدين
    result["sample_id"] = ocr_samples.save_prediction(
        raw, upload.filename, day, result, afraad_basic_on(data, day))
    summary = result.get("summary") or {}
    tech_log.ocr_event(
        "ocr.preview_done", rows=len(result.get("rows") or []),
        matched_services=summary.get("matched_services"), matched_people=summary.get("matched_people"),
        sample_id=result["sample_id"], duration_ms=tech_log.ms_since(started))
    return jsonify(result)


@bp.post("/api/afraad/<day>/ocr/apply")
def apply_afraad_ocr(day):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    body = json_payload()
    _begin_ocr(day, body.get("ocr_session"))
    started = time.perf_counter()
    rows = body.get("rows")
    tech_log.ocr_event("ocr.apply_received", rows=len(rows) if isinstance(rows, list) else None,
                       sample_id=body.get("sample_id") if isinstance(body.get("sample_id"), str) else None)

    def mutate(data):
        ok, error = day_status.check_open(data, day)
        if not ok:
            tech_log.ocr_event("ocr.apply_rejected", level=logging.WARNING, reason="day_closed")
            raise AbortRequest((jsonify({"error": error}), 409))
        stale = stale_revision(data, body.get("revision"), [day])
        if stale:
            tech_log.ocr_event("ocr.apply_rejected", level=logging.WARNING, reason="stale_revision")
            raise AbortRequest((jsonify({
                "error": "تغيّرت اليومية بعد قراءة الصورة. حدّث الصفحة وأعد المراجعة.",
                "code": "stale_revision", "revision": stale,
            }), 409))
        applied, error = apply_rows(data, day, body.get("rows"))
        if error:
            tech_log.ocr_event("ocr.apply_rejected", level=logging.WARNING, reason="invalid_rows")
            raise AbortRequest((jsonify({"error": error}), 400))
        built.append(ocr_samples.build_final(
            body.get("sample_id"), day, body.get("review"), afraad_basic_on(data, day),
            [person.as_dict() for person in PeopleRepo(data).on_force(day, "personnel")]))
        per_row = [(str(r.get("service_id") or ""), bool(r.get("morning_person_id")),
                    bool(r.get("night_person_id"))) for r in rows if isinstance(r, dict)]
        tech_log.ocr_event(
            "ocr.apply_done", applied=applied, rows=len(per_row),
            rows_changed=sum(1 for _s, m, n in per_row if m or n),
            morning_set=sum(1 for _s, m, _n in per_row if m),
            night_set=sum(1 for _s, _m, n in per_row if n),
            duration_ms=tech_log.ms_since(started))
        if logging.getLogger(tech_log.OCR_LOGGER).isEnabledFor(logging.DEBUG):
            for service_id, morning, night in per_row:
                tech_log.ocr_event("ocr.apply_row", level=logging.DEBUG, service_id=service_id,
                                   morning=morning, night=night)
        return jsonify({"applied": applied, "data": _payload(data, day)})

    built = []
    response = with_data(mutate, _afraad_scope(day))
    if built and getattr(response, "status_code", 200) == 200:
        ocr_samples.save_final(built[0])        # الصح بعد مراجعة المشغّل
    return response

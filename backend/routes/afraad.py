"""يومية الأفراد — API القراءة اليومية وتعديل القائم بها/التليفون/
الانتظام على خدمة أساسية واحدة ليوم بعينه."""
from flask import Blueprint, jsonify, request, send_file

from .. import day_status
from ..dated import afraad_basic_on
from ..afraad import (add_basic_service, build_afraad, remove_basic_service,
                       set_basic_entry, update_basic_service)
from .. import ocr_samples
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


@bp.post("/api/afraad/<day>/ocr/preview")
def preview_afraad_ocr(day):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    upload = request.files.get("image")
    if upload is None or not upload.filename:
        return jsonify({"error": "اختر صورة أولاً."}), 400
    data = load_data(_afraad_scope(day))
    raw = upload.read()
    try:
        result = analyze_image(raw, upload.filename, data, day)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 503
    result["revision"] = revision(data, [day])
    # الصورة وناتج القراءة بيتحفظوا لبناء موديل OCR خاص بالنظام بعدين
    result["sample_id"] = ocr_samples.save_prediction(
        raw, upload.filename, day, result, afraad_basic_on(data, day))
    return jsonify(result)


@bp.post("/api/afraad/<day>/ocr/apply")
def apply_afraad_ocr(day):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    body = json_payload()

    def mutate(data):
        ok, error = day_status.check_open(data, day)
        if not ok:
            raise AbortRequest((jsonify({"error": error}), 409))
        stale = stale_revision(data, body.get("revision"), [day])
        if stale:
            raise AbortRequest((jsonify({
                "error": "تغيّرت اليومية بعد قراءة الصورة. حدّث الصفحة وأعد المراجعة.",
                "code": "stale_revision", "revision": stale,
            }), 409))
        applied, error = apply_rows(data, day, body.get("rows"))
        if error:
            raise AbortRequest((jsonify({"error": error}), 400))
        built.append(ocr_samples.build_final(
            body.get("sample_id"), day, body.get("review"), afraad_basic_on(data, day),
            [person.as_dict() for person in PeopleRepo(data).on_force(day, "personnel")]))
        return jsonify({"applied": applied, "data": _payload(data, day)})

    built = []
    response = with_data(mutate, _afraad_scope(day))
    if built and getattr(response, "status_code", 200) == 200:
        ocr_samples.save_final(built[0])        # الصح بعد مراجعة المشغّل
    return response

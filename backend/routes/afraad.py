"""يومية الأفراد — API القراءة اليومية وتعديل القائم بها/التليفون/
الانتظام على خدمة أساسية واحدة ليوم بعينه."""
from flask import Blueprint, jsonify, send_file

from .. import day_status
from ..afraad import build_afraad, set_basic_entry
from ..afraad_export import build_docx
from ..store import AbortRequest, load_data, with_data
from ..utils import canonical_day, json_payload

bp = Blueprint("afraad", __name__)


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
    return jsonify(build_afraad(load_data(_afraad_scope(day)), day))


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
        return jsonify(build_afraad(data, day))

    return with_data(mutate, _afraad_scope(day))

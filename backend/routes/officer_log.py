"""سجل خدمات الضابط — API للقراءة بس، مفيش كتابة فمفيش قفل."""
from flask import Blueprint, jsonify, request

from .. import officer_log as officer_log_lib
from ..store import load_data

bp = Blueprint("officer_log", __name__)


@bp.get("/api/officer-log/<officer_id>")
def get_officer_log(officer_id):
    data = load_data()
    filters = {
        "date_from": request.args.get("date_from", "").strip(),
        "date_to": request.args.get("date_to", "").strip(),
    }
    result = officer_log_lib.build(data, officer_id, filters)
    if result is None:
        return jsonify({"error": "الضابط غير موجود."}), 404
    return jsonify(result)

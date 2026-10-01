"""سجل خدمات الضابط — API للقراءة بس، مفيش كتابة فمفيش قفل."""
from flask import Blueprint, jsonify, request

from .. import officer_log as officer_log_lib
from ..store import load_data
from ..utils import range_filters, recorded_range_scope

bp = Blueprint("officer_log", __name__)


@bp.get("/api/officer-log/<officer_id>")
def get_officer_log(officer_id):
    filters, error = range_filters(request.args)
    if error:
        return jsonify({"error": error}), 400
    # الأيام المسجّلة فعلًا جوّه المدى بس (الافتراضي آخر 30 يوم مسجّل)
    data = load_data(recorded_range_scope(filters))
    result = officer_log_lib.build(data, officer_id, filters)
    if result is None:
        return jsonify({"error": "الضابط غير موجود."}), 404
    return jsonify(result)

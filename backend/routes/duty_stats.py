"""إحصائيات تشغيل الضباط — API للقراءة بس، مفيش كتابة فمفيش قفل."""
from flask import Blueprint, jsonify, request

from .. import duty_stats as duty_stats_lib
from ..store import load_data
from ..utils import range_filters, recorded_range_scope

bp = Blueprint("duty_stats", __name__)


@bp.get("/api/duty/stats")
def get_duty_stats():
    filters, error = range_filters(request.args)
    if error:
        return jsonify({"error": error}), 400
    # الأيام المسجّلة فعلًا جوّه المدى بس (الافتراضي آخر 30 يوم مسجّل)
    data = load_data(recorded_range_scope(filters))
    return jsonify(duty_stats_lib.stats(data, filters))

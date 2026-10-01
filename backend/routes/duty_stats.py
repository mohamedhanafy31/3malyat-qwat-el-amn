"""إحصائيات تشغيل الضباط — API للقراءة بس، مفيش كتابة فمفيش قفل."""
from flask import Blueprint, jsonify, request

from .. import duty_stats as duty_stats_lib
from ..store import day_names, load_data
from ..utils import range_filters, recorded_between

bp = Blueprint("duty_stats", __name__)


@bp.get("/api/duty/stats")
def get_duty_stats():
    filters, error = range_filters(request.args)
    if error:
        return jsonify({"error": error}), 400
    scoped = None
    if filters["date_from"] and filters["date_to"]:
        # أسماء ملفات الأيام الموجودة بس — مش كل يوم في التقويم بين الحدين
        scoped = recorded_between(day_names(), filters["date_from"], filters["date_to"])
    data = load_data(days=scoped)
    return jsonify(duty_stats_lib.stats(data, filters))

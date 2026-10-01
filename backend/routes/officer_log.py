"""سجل خدمات الضابط — API للقراءة بس، مفيش كتابة فمفيش قفل."""
from flask import Blueprint, jsonify, request

from .. import officer_log as officer_log_lib
from ..store import day_names, load_data
from ..utils import range_filters, recorded_between

bp = Blueprint("officer_log", __name__)


@bp.get("/api/officer-log/<officer_id>")
def get_officer_log(officer_id):
    filters, error = range_filters(request.args)
    if error:
        return jsonify({"error": error}), 400
    scoped = None
    if filters["date_from"] and filters["date_to"]:
        # أسماء ملفات الأيام الموجودة بس — مش كل يوم في التقويم بين الحدين
        scoped = recorded_between(day_names(), filters["date_from"], filters["date_to"])
    data = load_data(days=scoped)
    result = officer_log_lib.build(data, officer_id, filters)
    if result is None:
        return jsonify({"error": "الضابط غير موجود."}), 404
    return jsonify(result)

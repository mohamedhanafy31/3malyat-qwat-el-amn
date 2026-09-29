"""إحصائيات تشغيل الضباط — API للقراءة بس، مفيش كتابة فمفيش قفل."""
from flask import Blueprint, jsonify, request

from .. import duty_stats as duty_stats_lib
from ..store import load_data

bp = Blueprint("duty_stats", __name__)


@bp.get("/api/duty/stats")
def get_duty_stats():
    data = load_data()
    filters = {
        "date_from": request.args.get("date_from", "").strip(),
        "date_to": request.args.get("date_to", "").strip(),
    }
    return jsonify(duty_stats_lib.stats(data, filters))

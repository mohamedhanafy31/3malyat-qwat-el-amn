"""إحصائيات تشغيل الضباط — API للقراءة بس، مفيش كتابة فمفيش قفل."""
from datetime import date

from flask import Blueprint, jsonify, request

from .. import duty_stats as duty_stats_lib
from ..store import load_data
from ..utils import days_between

bp = Blueprint("duty_stats", __name__)


@bp.get("/api/duty/stats")
def get_duty_stats():
    filters = {
        "date_from": request.args.get("date_from", "").strip(),
        "date_to": request.args.get("date_to", "").strip(),
    }
    scoped = None
    try:
        if filters["date_from"] and filters["date_to"]:
            scoped = days_between(date.fromisoformat(filters["date_from"]),
                                  date.fromisoformat(filters["date_to"]))
    except ValueError:
        pass
    data = load_data(days=scoped)
    return jsonify(duty_stats_lib.stats(data, filters))

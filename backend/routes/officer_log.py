"""سجل خدمات الضابط — API للقراءة بس، مفيش كتابة فمفيش قفل."""
from datetime import date

from flask import Blueprint, jsonify, request

from .. import officer_log as officer_log_lib
from ..store import load_data
from ..utils import days_between

bp = Blueprint("officer_log", __name__)


@bp.get("/api/officer-log/<officer_id>")
def get_officer_log(officer_id):
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
    result = officer_log_lib.build(data, officer_id, filters)
    if result is None:
        return jsonify({"error": "الضابط غير موجود."}), 404
    return jsonify(result)

"""جدول تفتيشات زيارات الأهالي الأسبوعي — إدارة (من دليل الخدمات) بس.
التفتيشات نفسها بتتحط على اليومية التفصيلية تلقائيًا (`inspection_schedule.
seed_board_day`، بتتنادى من `GET /api/board/<day>`)، مش من هنا."""
from flask import Blueprint, jsonify

from .. import inspection_schedule as sched_lib
from ..constants import WEEKDAYS
from ..store import AbortRequest, load_data, with_data
from ..utils import json_payload

bp = Blueprint("inspection_schedule", __name__)


@bp.get("/api/inspection-schedule")
def get_schedule():
    data = load_data()
    return jsonify({"weekdays": WEEKDAYS, "schedule": sched_lib.schedule(data)})


@bp.post("/api/inspection-schedule/<weekday>")
def add_entry(weekday):
    payload = json_payload()

    def mutate(data):
        entry, err = sched_lib.add_entry(data, weekday, payload)
        if err:
            raise AbortRequest((jsonify({"error": err}), 400))
        return jsonify(entry), 201

    return with_data(mutate)


@bp.patch("/api/inspection-schedule/<weekday>/<entry_id>")
def edit_entry(weekday, entry_id):
    payload = json_payload()

    def mutate(data):
        entry, err = sched_lib.edit_entry(data, weekday, entry_id, payload)
        if err:
            status = 404 if err == "التفتيش ده مش موجود." else 400
            raise AbortRequest((jsonify({"error": err}), status))
        return jsonify(entry)

    return with_data(mutate)


@bp.delete("/api/inspection-schedule/<weekday>/<entry_id>")
def delete_entry(weekday, entry_id):
    def mutate(data):
        if not sched_lib.delete_entry(data, weekday, entry_id):
            raise AbortRequest((jsonify({"error": "التفتيش ده مش موجود."}), 404))
        return jsonify({"ok": True})

    return with_data(mutate)

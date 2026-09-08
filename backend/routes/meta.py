"""الصفحة الرئيسية وتحميل البيانات الكاملة عند فتح السيستم."""
from datetime import date

from flask import Blueprint, jsonify, render_template

from ..constants import (
    COMMAND_ROLES, LEAVE_TYPES, MEDICAL_BADGE, REST_DURATIONS, REST_SYSTEMS,
    SERVICE_KINDS, SHIFTS, TAQSEERA_NOTICE_DAYS, WEEKDAYS,
)
from ..store import load_data

bp = Blueprint("meta", __name__)


@bp.route("/")
def index():
    return render_template("index.html")


@bp.get("/api/data")
def get_data():
    data = load_data()
    # التشغيل اليومي بيتجاب ليوم واحد من /api/duty/<day> و/api/board/<day> — كبير على الحمل الأول
    duty_days = sorted(data.pop("duties", {}))
    board_days = sorted(data.pop("day_services", {}))
    data["duty_days"] = duty_days
    data["board_days"] = board_days
    data["meta"] = {
        "service_kinds": SERVICE_KINDS,
        "shifts": SHIFTS,
        "rest_systems": REST_SYSTEMS,
        "weekdays": WEEKDAYS,
        "leave_types": LEAVE_TYPES,
        "rest_durations": REST_DURATIONS,
        "taqseera_notice_days": TAQSEERA_NOTICE_DAYS,
        "board_categories": data["board_categories"],
        "service_tags": data["service_tags"],
        "command_roles": COMMAND_ROLES,
        "medical_badge": MEDICAL_BADGE,
        "today": date.today().isoformat(),
    }
    return jsonify(data)

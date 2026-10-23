"""فحص الجاهزية العام — بيقول «ده سيستم شؤون الأفراد وبياناته بتتقري» وبس.

عام عن قصد (من غير تسجيل دخول) عشان START_SYSTEM.bat وINSTALL_AUTOSTART.bat
يتأكدوا إن اللي ماسك المنفذ هو السيستم ده فعلًا مش برنامج تاني. الرد ثابت
وصغير: مفيش أسماء ولا أعداد ولا مسارات ولا نص خطأ — تفاصيل العطل في سجل
السيرفر بس. المعرّف والحالة مكرّرين في tools/deploy_check.py وفي اختبار بيقارنهم.
"""
import logging

from flask import Blueprint, jsonify

from .. import store

bp = Blueprint("health", __name__)

SERVICE_ID = "personnel-system"
READY_PATH = "/api/health/ready"


@bp.get(READY_PATH)
def ready():
    try:
        info = store.validate_data(full=False)
    except Exception:
        logging.getLogger("personnel-system").exception("Readiness check failed")
        body, status = {"service": SERVICE_ID, "status": "unavailable"}, 503
    else:
        body, status = {"service": SERVICE_ID, "status": "ready", "schema": info["schema"]}, 200
    response = jsonify(body)
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    return response

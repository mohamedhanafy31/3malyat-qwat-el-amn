"""تحميل البيانات — كل صفحة بتطلب شريحتها بس، مش الداتا كلها.

قبل كده كان في نداء واحد `/api/data` بيرجّع 225 كيلوبايت (كل الضباط
والأفراد والراحات) في كل تحميل صفحة وكل ريفرش — حتى لو الصفحة محتاجة
حاجة صغيرة منهم. دلوقتي كل صفحة ليها bootstrap مخصوص.
"""
from datetime import date

from flask import Blueprint, jsonify

from ..constants import (
    COMMAND_ROLES, LEAVE_TYPES, MEDICAL_BADGE, REST_DURATIONS, REST_SYSTEMS,
    SERVICE_KINDS, SHIFTS, TAQSEERA_NOTICE_DAYS, WEEKDAYS,
)
from ..rest_status import officer_status, taqseera_alerts
from ..store import load_data

bp = Blueprint("meta", __name__)


def _meta(data):
    return {
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
        "command": data["command"],
        "medical_badge": MEDICAL_BADGE,
        "today": date.today().isoformat(),
    }


def _slim(people, rest=False):
    """أقل حاجة لازمة لعرض اسم شخص أو اختياره من قايمة. rest=True بتضيف
    نظام الراحة كمان — نموذج تسجيل الراحة بيستخدمه عشان يملا اليوم
    والمدة القياسية تلقائيًا."""
    out = []
    for p in people:
        slim = {"id": p["id"], "name": p.get("name", ""), "role": p.get("role", "")}
        if rest:
            slim["rest_system"] = p.get("rest_system", "")
            slim["rest_day"] = p.get("rest_day", "")
        out.append(slim)
    return out


def _officers_with_status(data, today):
    return [{**o, "status_today": officer_status(data, o, today)}
            for o in data["officers"]["active"]]


@bp.get("/api/bootstrap/<page>")
def bootstrap(page):
    """بيرجّع بالظبط اللي الصفحة دي محتاجاه، ولا حاجة زيادة."""
    data = load_data()
    today = date.today()
    meta = _meta(data)

    if page == "dashboard":
        officers, personnel = data["officers"]["active"], data["personnel"]["active"]
        on_rest = sum(1 for o in officers
                      if officer_status(data, o, today)["state"] == "resting")
        alerts = taqseera_alerts(data, today)
        return jsonify({"meta": meta, "alerts": alerts, "counts": {
            "officers": len(officers), "personnel": len(personnel),
            "on_rest": on_rest, "taqseera": len(alerts),
            "leaves": len(data["leaves"]), "services": len(data["services"]),
        }})

    if page == "officers":
        return jsonify({
            "meta": meta,
            "officers": {"active": _officers_with_status(data, today),
                          "archive": data["officers"]["archive"]},
            "command": data["command"],
            "medical_officers": data["medical_officers"],
            "alerts": taqseera_alerts(data, today),
            "counts": {"personnel": len(data["personnel"]["active"]),
                        "leaves": len(data["leaves"]),
                        "services": len(data["services"])},
        })

    if page == "personnel":
        return jsonify({"meta": meta, "personnel": data["personnel"],
                        "counts": {"officers": len(data["officers"]["active"]),
                                    "leaves": len(data["leaves"]),
                                    "services": len(data["services"])}})

    if page in ("duty", "board"):
        return jsonify({
            "meta": meta,
            "officer_index": _slim(data["officers"]["active"]),
            "services": data["services"],
            "duty_days": sorted(data["duties"]),
            "board_days": sorted(data["day_services"]),
            "counts": {"officers": len(data["officers"]["active"]),
                        "personnel": len(data["personnel"]["active"]),
                        "leaves": len(data["leaves"]),
                        "services": len(data["services"])},
        })

    if page == "catalog":
        return jsonify({"meta": meta, "services": data["services"],
                        "counts": {"officers": len(data["officers"]["active"]),
                                    "personnel": len(data["personnel"]["active"]),
                                    "leaves": len(data["leaves"]),
                                    "services": len(data["services"])}})

    if page == "leaves":
        people = _slim(data["officers"]["active"] + data["personnel"]["active"], rest=True)
        known = {p["id"] for p in people}
        # أي شخص متأرشف لسه ليه سجل راحة لازم اسمه يبان في القايمة
        people += _slim([p for b in ("officers", "personnel") for p in data[b]["archive"]
                         if p["id"] not in known
                         and any(l["person_id"] == p["id"] for l in data["leaves"])])
        return jsonify({"meta": meta, "leaves": data["leaves"], "people": people,
                        "officer_ids": [o["id"] for o in data["officers"]["active"]],
                        "counts": {"officers": len(data["officers"]["active"]),
                                    "personnel": len(data["personnel"]["active"]),
                                    "leaves": len(data["leaves"]),
                                    "services": len(data["services"])}})

    return jsonify({"error": "صفحة غير معروفة."}), 404


@bp.get("/api/data")
def get_data():
    """النداء الشامل القديم — متسيب للتوافق وللسكربتات، والصفحات بقت
    بتستخدم /api/bootstrap/<page> بدله."""
    data = load_data()
    duty_days = sorted(data.pop("duties", {}))
    board_days = sorted(data.pop("day_services", {}))
    data["duty_days"] = duty_days
    data["board_days"] = board_days
    data["meta"] = _meta(data)
    return jsonify(data)

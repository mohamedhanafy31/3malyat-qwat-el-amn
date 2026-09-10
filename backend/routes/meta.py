"""تحميل البيانات — كل صفحة بتطلب شريحتها بس، مش الداتا كلها.

قبل كده كان في نداء واحد `/api/data` بيرجّع 225 كيلوبايت (كل الضباط
والأفراد والراحات) في كل تحميل صفحة وكل ريفرش — حتى لو الصفحة محتاجة
حاجة صغيرة منهم. دلوقتي كل صفحة ليها bootstrap مخصوص.
"""
from datetime import date

from flask import Blueprint, jsonify

from ..assignments import OFFICER_STATUSES
from ..board import BOARD_ORDER
from ..constants import (
    COMMAND_ROLES, LEAVE_TYPES, MEDICAL_BADGE, OFFICER_SECTIONS, REST_DURATIONS,
    REST_SYSTEMS, SERVICE_DOCUMENTS, SERVICE_KINDS, SERVICE_SECTIONS, SHIFTS,
    TAQSEERA_NOTICE_DAYS, WEEKDAYS,
)
from ..leaves import monthly_roster
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
        "board_sections": BOARD_ORDER,
        "service_sections": SERVICE_SECTIONS,
        "service_documents": SERVICE_DOCUMENTS,
        "officer_statuses": OFFICER_STATUSES,
        "officer_sections": OFFICER_SECTIONS,
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


def _slim_services(services):
    """أقل حاجة لازمة لعرض/فلترة خدمة في اللوحة (اختيار من قايمة، تحديد
    الفترة والقسم) — مش كل حقول الكتالوج، اللي بتوصل كاملة لصفحة catalog
    بس لأنها الوحيدة اللي فعلًا بتعدّل الخدمة بكل حقولها."""
    return [{"id": s["id"], "name": s.get("name", ""), "sub": s.get("sub", ""),
             "kind": s.get("kind", ""), "section": s.get("section", ""),
             "shifts": s.get("shifts", []), "appears_in": s.get("appears_in", [])}
            for s in services]


def _counts(data):
    return {
        "officers": len(data["officers"]["active"]),
        "personnel": len(data["personnel"]["active"]),
        "leaves": len(data["leaves"]),
        "services": len(data["services"]),
        "courses": len(data.get("courses", [])),
    }


def _days_payload(data, meta):
    """أساس مشترك لصفحات التشغيل اليومي: الأيام المتاحة + الأعداد بس —
    بلا مؤشر ضباط/أفراد ولا كتالوج خدمات لو الصفحة مش فعلًا محتاجاهم."""
    return {"meta": meta, "days": sorted(data["day_assignments"]), "counts": _counts(data)}


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
            **_counts(data),
            "on_rest": on_rest,
            "taqseera": len(alerts),
        }})

    if page == "officers":
        return jsonify({
            "meta": meta,
            "officers": {"active": _officers_with_status(data, today),
                          "archive": data["officers"]["archive"]},
            "command": data["command"],
            "medical_officers": data["medical_officers"],
            "alerts": taqseera_alerts(data, today),
            "counts": _counts(data),
        })

    if page == "personnel":
        return jsonify({"meta": meta, "personnel": data["personnel"],
                        "counts": _counts(data)})

    if page in ("duty", "register"):
        # الاتنين محتاجين قايمة الأيام بس (لتحديد آخر يوم افتراضي) — لا
        # كتالوج خدمات ولا مؤشر ضباط/أفراد، بيوصلهم كل حاجة جاهزة من
        # /api/duty و/api/register نفسهم.
        return jsonify(_days_payload(data, meta))

    if page == "courses":
        payload = _days_payload(data, meta)
        # كل اللي كانوا على القوة في أي وقت — عشان الضابط المتأرشف يبان
        # في قايمة الالتحاق لو ليه فرقة مسجّلة قبل كده
        payload["officer_index"] = _slim(data["officers"]["active"] + data["officers"]["archive"])
        return jsonify(payload)

    if page == "board":
        payload = _days_payload(data, meta)
        payload["officer_index"] = _slim(data["officers"]["active"] + data["officers"]["archive"])
        payload["personnel_index"] = _slim(data["personnel"]["active"])
        payload["services"] = _slim_services(data["services"])
        return jsonify(payload)

    if page == "catalog":
        return jsonify({"meta": meta, "services": data["services"], "counts": _counts(data)})

    if page == "leaves":
        people = _slim(data["officers"]["active"] + data["personnel"]["active"], rest=True)
        known = {p["id"] for p in people}
        # أي شخص متأرشف لسه ليه سجل راحة لازم اسمه يبان في القايمة
        people += _slim([p for b in ("officers", "personnel") for p in data[b]["archive"]
                         if p["id"] not in known
                         and any(l["person_id"] == p["id"] for l in data["leaves"])])
        return jsonify({"meta": meta, "leaves": data["leaves"], "people": people,
                        "officer_ids": [o["id"] for o in data["officers"]["active"]],
                        "counts": _counts(data)})

    if page == "leaves_stats":
        # صفحة الإحصائيات محتاجة meta + counts فقط — الداتا بتيجي من /api/leaves/stats
        return jsonify({"meta": meta, "counts": _counts(data)})

    if page == "leaves_monthly":
        # الاسم "roster" مقصود مش "officers" — core.js's paintNavCounts()
        # بتفترض إن أي مفتاح "officers" شكله {active, archive} زي صفحة
        # الضباط، ومش قايمة مسطّحة زي الكشف ده.
        return jsonify({"meta": meta, "roster": monthly_roster(data, today),
                        "counts": _counts(data)})

    return jsonify({"error": "صفحة غير معروفة."}), 404



@bp.get("/api/data")
def get_data():
    """النداء الشامل القديم — متسيب للتوافق وللسكربتات، والصفحات بقت
    بتستخدم /api/bootstrap/<page> بدله."""
    data = load_data()
    data["days"] = sorted(data.pop("day_assignments", {}))
    data.pop("day_officers", None)
    data["meta"] = _meta(data)
    return jsonify(data)

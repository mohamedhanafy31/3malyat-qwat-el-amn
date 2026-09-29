"""تحميل البيانات — كل صفحة بتطلب شريحتها بس، مش الداتا كلها.

قبل كده كان في نداء واحد `/api/data` بيرجّع 225 كيلوبايت (كل الضباط
والأفراد والراحات) في كل تحميل صفحة وكل ريفرش — حتى لو الصفحة محتاجة
حاجة صغيرة منهم. دلوقتي كل صفحة ليها bootstrap مخصوص.
"""
from datetime import date

from flask import Blueprint, jsonify

from .. import clock, day_status, rest_suspension
from ..assignments import OFFICER_STATUSES
from ..board import BOARD_ORDER
from ..constants import (
    COMMAND_ROLES, GROUP_ROLES, LEAVE_TYPES, OFFICER_SECTIONS, REST_DURATIONS,
    REST_SYSTEMS, SERVICE_DOCUMENTS, SERVICE_KINDS, SERVICE_SECTIONS, SHIFTS,
    TAQSEERA_NOTICE_DAYS, WEEKDAYS,
)
from ..leaves import monthly_roster, weekly_roster
from ..rest_status import officer_status, taqseera_alerts
from ..repo import Repos
from ..store import load_data
from ..upcoming import build as build_upcoming

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
        "command_roles": COMMAND_ROLES,
        "command": Repos(data).config.command(),
        "group_roles": GROUP_ROLES,
        "command_groups": Repos(data).config.groups(),
        "rest_suspension": rest_suspension.summary(data),
        "today": date.today().isoformat(),
    }


def _slim(people, rest=False):
    """أقل حاجة لازمة لعرض اسم شخص أو اختياره من قايمة. rest=True بتضيف
    نظام الراحة كمان — نموذج تسجيل الراحة بيستخدمه عشان يملا اليوم
    والمدة القياسية تلقائيًا."""
    out = []
    for p in people:
        slim = {"id": p.id, "name": p.name, "role": p.role}
        if rest:
            slim["rest_system"] = getattr(p, "rest_system", "")
            slim["rest_day"] = getattr(p, "rest_day", "")
        out.append(slim)
    return out


def _officers_with_status(data, today):
    return [{**o.as_dict(), "status_today": officer_status(data, o.as_dict(), today)}
            for o in Repos(data).people.active("officers")]


def _counts(data):
    repos = Repos(data)
    return {
        "officers": len(repos.people.bucket("officers", "active")),
        "personnel": len(repos.people.bucket("personnel", "active")),
        "leaves": repos.leaves.count(),
        "courses": repos.courses.count(),
    }


def _days_payload(data, meta):
    """أساس مشترك لصفحات التشغيل اليومي: الأيام المتاحة + الأعداد بس —
    بلا مؤشر ضباط/أفراد ولا كتالوج خدمات لو الصفحة مش فعلًا محتاجاهم."""
    return {"meta": meta, "days": Repos(data).days.assignment_dates(),
            "counts": _counts(data)}


@bp.get("/api/bootstrap/<page>")
def bootstrap(page):
    """بيرجّع بالظبط اللي الصفحة دي محتاجاه، ولا حاجة زيادة."""
    data = load_data()
    today = date.today()
    meta = _meta(data)

    if page == "dashboard":
        officers = Repos(data).people.active("officers")
        on_rest = sum(1 for o in officers
                      if officer_status(data, o.as_dict(), today)["state"] == "resting")
        alerts = taqseera_alerts(data, today)
        return jsonify({"meta": meta, "alerts": alerts, "upcoming": build_upcoming(data, today),
                        "clock_warning": clock.check(today),
                        "counts": {
                            **_counts(data),
                            "on_rest": on_rest,
                            "taqseera": len(alerts),
                        }})

    if page == "officers":
        return jsonify({
            "meta": meta,
            "officers": {"active": _officers_with_status(data, today),
                          "archive": Repos(data).people.bucket("officers", "archive")},
            "command": Repos(data).config.command(),
            "command_groups": Repos(data).config.groups(),
            "alerts": taqseera_alerts(data, today),
            "counts": _counts(data),
        })

    if page == "personnel":
        repos = Repos(data)
        return jsonify({"meta": meta,
                        "personnel": {
                            "active": repos.people.bucket("personnel", "active"),
                            "archive": repos.people.bucket("personnel", "archive")},
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
        payload["officer_index"] = _slim(Repos(data).people.all("officers"))
        return jsonify(payload)

    if page == "board":
        # مفيش officer_index/personnel_index هنا — مين ينفع يتكلّف في خانة
        # بيتحدد **لليوم المفتوح بالظبط**، فقايمة الاختيار بتيجي من
        # `build_board()` نفسها (`roster`) مش من بيانات ثابتة هنا.
        return jsonify(_days_payload(data, meta))

    if page == "counts":
        return jsonify(_days_payload(data, meta))

    if page == "afraad":
        return jsonify(_days_payload(data, meta))

    if page == "changes":
        return jsonify({"meta": meta, "counts": _counts(data)})

    if page == "missions":
        payload = {"meta": meta, "counts": _counts(data)}
        payload["officer_index"] = _slim(Repos(data).people.all("officers"))
        return jsonify(payload)

    if page == "leaves":
        repos = Repos(data)
        people = _slim(repos.people.active("officers")
                       + repos.people.active("personnel"), rest=True)
        known = {p["id"] for p in people}
        # أي شخص متأرشف لسه ليه سجل راحة لازم اسمه يبان في القايمة
        people += _slim([p for cat in ("officers", "personnel")
                         for p in repos.people.archived(cat)
                         if p.id not in known and repos.leaves.of_person(p.id)])
        # الضباط المتأرشفين لازم يكونوا في القايمة دي: 73 من الـ280 راحة
        # بتاعة ضباط خرجوا من القوة، وفلتر «ضباط/أفراد» في الصفحة بيتقاس
        # عليها — من غيرهم كانوا بيتحسبوا أفراد وهم ضباط.
        officer_ids = [o.id for o in repos.people.all("officers")]
        return jsonify({"meta": meta, "leaves": repos.leaves.rows_with_names(), "people": people,
                        "officer_ids": officer_ids,
                        "counts": _counts(data)})

    if page == "leaves_stats":
        # صفحة الإحصائيات محتاجة meta + counts فقط — الداتا بتيجي من /api/leaves/stats
        return jsonify({"meta": meta, "counts": _counts(data)})

    if page == "duty_stats":
        # زي leaves_stats بالظبط — الداتا بتيجي من /api/duty/stats
        return jsonify({"meta": meta, "counts": _counts(data)})

    if page == "service_catalog":
        # زي leaves_stats بالظبط — الداتا بتيجي من /api/service-catalog
        return jsonify({"meta": meta, "counts": _counts(data)})

    if page == "officer_log":
        # قايمة الضباط لاختيار مين تعرض سجله — الضباط الحاليين بس (على
        # عكس courses/missions اللي محتاجين المتأرشفين كمان لسجل قديم
        # ليهم)، عشان القايمة ما تتزحلقش بأسماء خرجوا من القوة من زمان.
        payload = {"meta": meta, "counts": _counts(data)}
        payload["officer_index"] = _slim(Repos(data).people.active("officers"))
        return jsonify(payload)

    if page == "rest_suspension":
        # الأوامر نفسها بتيجي من /api/rest-suspensions — هنا meta بس
        return jsonify({"meta": meta, "counts": _counts(data)})

    if page == "leaves_monthly":
        # الاسم "roster" مقصود مش "officers" — core.js's paintNavCounts()
        # بتفترض إن أي مفتاح "officers" شكله {active, archive} زي صفحة
        # الضباط، ومش قايمة مسطّحة زي الكشف ده.
        weekly_today = date.fromisoformat(day_status.today_iso())
        return jsonify({"meta": meta, "roster": monthly_roster(data, today),
                        "weekly_roster": weekly_roster(data, weekly_today),
                        "counts": _counts(data)})

    return jsonify({"error": "صفحة غير معروفة."}), 404



@bp.get("/api/data")
def get_data():
    """النداء الشامل القديم — متسيب للتوافق وللسكربتات، والصفحات بقت
    بتستخدم /api/bootstrap/<page> بدله."""
    data = load_data()
    repos = Repos(data)
    # نسخة جديدة بدل ما يعدّل اللقطة المحمّلة في مكانها. اليوميات بتتشال
    # وبيتحط مكانها قايمة التواريخ بس — ده كان الغرض من النداء ده أصلًا.
    payload = repos.snapshot(exclude=("day_assignments", "day_officers"))
    payload["days"] = repos.days.assignment_dates()
    # القوة بترجع بالشكل المتداخل القديم (`{active, archive}`) رغم إنها
    # بقت متخزّنة قايمة واحدة. ده **مش** تناقض: النداء ده متسيب صراحةً
    # للتوافق مع السكربتات، وعقد الواجهة مالوش علاقة بشكل التخزين.
    for cat in ("officers", "personnel"):
        payload[cat] = {"active": repos.people.bucket(cat, "active"),
                        "archive": repos.people.bucket(cat, "archive")}
    payload["meta"] = _meta(data)
    return jsonify(payload)

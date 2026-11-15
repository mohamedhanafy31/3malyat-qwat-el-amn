"""وقف الراحات — أوامر الوقف العام (إنشاء/مرشّحين/فتح/عرض).
إيقاف راحة واحدة بعينها في `routes/leaves.py` (`POST /api/leaves/<id>/stop`)."""
from flask import Blueprint, jsonify, request, send_file
from io import BytesIO

from .. import day_status
from .. import rest_suspension as lib
from .. import retro
from ..constants import LEAVE_TYPES
from ..store import load_data, with_data
from ..utils import canonical_day, json_payload
from ..register_export import build_register_docx, register_file_name
from datetime import date

_AR_MONTHS = ("", "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر")


def _display_day(value):
    try:
        parsed = date.fromisoformat(value)
        return f"{parsed.day} {_AR_MONTHS[parsed.month]} {parsed.year}"
    except (TypeError, ValueError):
        return value or "—"

bp = Blueprint("rest_suspension", __name__)


@bp.get("/api/rest-suspensions")
def list_suspensions():
    out = lib.listing(load_data(()))
    today = day_status.today_iso()
    for o in out["active"]:
        o["can_restore"] = lib.can_restore(o, today)
    return jsonify(out)


@bp.get("/api/rest-suspensions/export.docx")
def export_suspensions():
    out = lib.listing(load_data(()))
    rows = []
    for order in out["active"]:
        rows.append(["ساري", " + ".join(order.get("types", [])), _display_day(order.get("started_on", "")), "—", order.get("reason", ""),
                     "\n".join(f"{x.get('name','')} — أُوقفت: {_display_day(x.get('stopped_on',''))} (كانت حتى {_display_day(x.get('original_end',''))})" for x in order.get("stopped_leaves", [])) or "—"])
    for order in out["history"]:
        rows.append(["مفتوح", " + ".join(order.get("types", [])), _display_day(order.get("started_on", "")), _display_day(order.get("lifted_on", "")),
                     order.get("reason", "") + (("\nسبب الفتح: " + order.get("lift_reason", "")) if order.get("lift_reason") else ""),
                     f"أُوقفت: {len(order.get('stopped_leaves', []))} — أُلغيت: {len(order.get('cancelled_leaves', []))}"])
    content = build_register_docx("سجل أوامر وقف الراحات", [("الحالة",.8),("الأنواع",1.5),("من",1),("فُتح",1),("السبب",2),("الراحات المتأثرة",2)], rows,
                                  subtitle="الأوامر السارية وسجل الأوامر المفتوحة")
    return send_file(BytesIO(content), as_attachment=True, download_name=register_file_name("سجل أوامر وقف الراحات"), mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@bp.get("/api/rest-suspensions/candidates")
def list_candidates():
    types = [t for t in request.args.getlist("type") if t in LEAVE_TYPES]
    today = day_status.today_iso()
    return jsonify({"today": today, "rows": lib.candidates(load_data(()), types, today)})


@bp.get("/api/rest-suspensions/day/<day>")
def day_summary(day):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    return jsonify(lib.on_day(load_data(()), day))


@bp.post("/api/rest-suspensions")
def create_suspension():
    payload = json_payload()

    def mutate(data):
        order, report = lib.create(data, payload, day_status.today_iso())
        return jsonify({"suspension": order, **report}), 201

    return with_data(mutate, retro.status_scope)


@bp.post("/api/rest-suspensions/<order_id>/lift")
def lift_suspension(order_id):
    payload = json_payload()

    def mutate(data):
        return jsonify(lib.lift(data, order_id, payload, day_status.today_iso()))

    return with_data(mutate, ())

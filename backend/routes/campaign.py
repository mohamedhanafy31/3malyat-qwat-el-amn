from flask import Blueprint, jsonify, request, send_file

from .. import campaign, day_status, retro
from ..campaign_export import build_docx
from ..store import AbortRequest, load_data, revision, stale_revision, with_data
from ..utils import canonical_day, json_payload

bp = Blueprint("campaign", __name__)


def _scope(day):
    def scope(view):
        return {day, *campaign.inheritance_days(view.index.days_with("day_campaign", end=day), day)}
    return scope


def _payload(data, day, days=None):
    value = campaign.build_campaign(data, day)
    # البيانات المحمّلة بالفعل محصورة في اليوم وأيام نافذة الوراثة السابقة ذات الحملة.
    value["revision"] = revision(data, days)
    return value


def _day(day):
    return canonical_day(day)


@bp.get("/api/campaign/<day>")
def get_campaign(day):
    day = _day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    return jsonify(_payload(load_data(_scope(day)), day))


def _write(day, fn):
    day = _day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    body = json_payload()

    def mutate(data):
        ok, err = day_status.check_open(data, day)
        if not ok:
            raise AbortRequest((jsonify({"error": err}), 409))
        stale = stale_revision(data, body.get("revision"))
        if stale:
            raise AbortRequest((jsonify({"error": "تغيّرت اليومية؛ حدّث الصفحة.",
                                         "code": "stale_revision", "revision": stale}), 409))
        error, status = fn(data, body)
        if error:
            raise AbortRequest((jsonify({"error": error}), status))
        return jsonify(_payload(data, day))
    return with_data(mutate, _scope(day))


@bp.put("/api/campaign/<day>/lorry/<lorry_id>")
def put_lorry(day, lorry_id):
    return _write(day, lambda data, body: campaign.set_lorry(
        data, _day(day), lorry_id, body))


@bp.put("/api/campaign/<day>/service/<assignment_id>")
def put_service(day, assignment_id):
    return _write(day, lambda data, body: campaign.set_service(
        data, _day(day), assignment_id, body))


@bp.put("/api/campaign/<day>/daily/<row_id>")
def put_daily(day, row_id):
    return _write(day, lambda data, body: campaign.set_daily(
        data, _day(day), row_id, body))


@bp.put("/api/campaign/<day>/post/<post_id>")
def put_post(day, post_id):
    return _write(day, lambda data, body: campaign.set_post(data, _day(day), post_id, body))


@bp.post("/api/campaign/<day>/lorry/<lorry_id>/service")
def post_attach(day, lorry_id):
    return _write(day, lambda data, body: campaign.attach_service(
        data, _day(day), lorry_id, body))


@bp.delete("/api/campaign/<day>/lorry/<lorry_id>/service")
def delete_attach(day, lorry_id):
    body = json_payload()
    body.update({key: request.args.get(key) for key in ("assignment_id", "name")
                 if request.args.get(key)})
    return _write_with_body(day, body, lambda d, b: campaign.detach_service(d, _day(day), lorry_id, b))


def _write_with_body(day, body, fn):
    day = _day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400

    def mutate(data):
        ok, err = day_status.check_open(data, day)
        if not ok:
            raise AbortRequest((jsonify({"error": err}), 409))
        stale = stale_revision(data, body.get("revision"))
        if stale:
            raise AbortRequest((jsonify({"error": "تغيّرت اليومية؛ حدّث الصفحة.",
                                         "code": "stale_revision", "revision": stale}), 409))
        error, status = fn(data, body)
        if error:
            raise AbortRequest((jsonify({"error": error}), status))
        return jsonify(_payload(data, day))
    return with_data(mutate, _scope(day))


@bp.post("/api/campaign/<day>/daily-rows")
def add_daily(day):
    return _write(day, lambda d, b: _add(d, _day(day), b))


def _add(data, day, body):
    ident, error, status = campaign.add_daily_row(data, day, body.get("name"), body.get("basic_entry_id"))
    return error, status


@bp.post("/api/campaign/<day>/posts")
def add_post(day):
    return _write(day, lambda d, b: _add_post(d, _day(day), b))


def _add_post(data, day, body):
    _, error, status = campaign.add_post(
        data, day, body.get("name"), body.get("number"), body.get("driver_text"))
    return error, status


@bp.patch("/api/campaign/<day>/posts/<post_id>")
def patch_post(day, post_id):
    return _write(day, lambda data, body: campaign.update_post(
        data, _day(day), post_id, body.get("name"), body.get("number")))


@bp.delete("/api/campaign/<day>/posts/<post_id>")
def delete_post(day, post_id):
    return _write(day, lambda data, body: campaign.remove_post(data, _day(day), post_id))


@bp.put("/api/campaign/<day>/plates")
def put_plates(day):
    return _write(day, lambda data, body: campaign.set_plates(data, _day(day), body.get("rows")))


@bp.delete("/api/campaign/<day>/daily-rows/<row_id>")
def delete_daily(day, row_id):
    return _write(day, lambda data, body: campaign.remove_daily_row(
        data, _day(day), row_id))


@bp.get("/api/campaign/<day>/export.docx")
def export_campaign(day):
    day = _day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    buf = build_docx(campaign.build_campaign(load_data(_scope(day)), day))
    return send_file(buf, as_attachment=True, download_name=f"يومية الحملة {day}.docx", mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


def _group_scope(day):
    base = _scope(day)
    return lambda view: {*base(view), *retro.status_scope(view)}


def _write_group(day, group_id, action, fn, out=None):
    """تجميع الخدمات: اليوم المقفول بيقبل التعديل بسبب مكتوب (X-Retro-Reason) ويتسجّل بأثر رجعي."""
    day = _day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    body = json_payload()

    def mutate(data):
        closed = [day] if day_status.is_closed(data, day) else []
        reason = retro.require_reason(closed)
        days = campaign.scope_days(data, day)
        stale = stale_revision(data, body.get("revision"), days)
        if stale:
            raise AbortRequest((jsonify({"error": "تغيّرت اليومية؛ حدّث الصفحة.",
                                         "code": "stale_revision", "revision": stale}), 409))
        error, status = fn(data, body)
        if error:
            raise AbortRequest((jsonify({"error": error}), status))
        if closed:
            ident = group_id or (out or {}).get("group_id", "")
            retro.log_retro(data, "campaign_group", ident, closed, reason,
                            text=f"تعديل مجموعات الحملة ({action}) بأثر رجعي على يوم مغلق {day}"
                                 + (f" — السبب: {reason}" if reason else ""))
        value = _payload(data, day, campaign.scope_days(data, day))
        if out:
            value.update(out)
        return jsonify(value)
    return with_data(mutate, _group_scope(day))


@bp.post("/api/campaign/<day>/groups")
def post_group(day):
    out = {}
    return _write_group(day, "", "create", lambda data, body: campaign.create_group(
        data, _day(day), body.get("title"), body.get("members"), out), out)


@bp.patch("/api/campaign/<day>/groups/<group_id>")
def patch_group(day, group_id):
    return _write_group(day, group_id, "update", lambda data, body: campaign.update_group(
        data, _day(day), group_id, body))


@bp.put("/api/campaign/<day>/group/<group_id>")
def put_group(day, group_id):
    return _write_group(day, group_id, "assign", lambda data, body: campaign.set_group(
        data, _day(day), group_id, body))


@bp.delete("/api/campaign/<day>/groups/<group_id>")
def delete_group(day, group_id):
    return _write_group(day, group_id, "ungroup", lambda data, body: campaign.ungroup(
        data, _day(day), group_id))

"""API لوحة تشغيل الخدمات."""
from datetime import date, timedelta

from flask import Blueprint, jsonify

from .. import day_status, ops_board
from ..auth import current_actor
from ..store import AbortRequest, load_data, revision, stale_revision, with_data
from ..utils import canonical_day, json_payload

bp = Blueprint("ops", __name__)


def _scope(day):
    value = date.fromisoformat(day)
    return [(value - timedelta(days=i)).isoformat() for i in range(4)]


def _day(raw):
    return canonical_day(raw)


@bp.get("/api/ops/<day>")
def get_ops(day):
    day = _day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    data = load_data(_scope(day))
    result = ops_board.build_ops(data, day)
    result["revision"] = revision(data, _scope(day))
    return jsonify(result)


def _mutate(day, body, fn, *, check_revision=True):
    scope = _scope(day)
    actor = current_actor()["display_name"]

    def mutate(data):
        if check_revision:
            stale = stale_revision(data, body.get("revision"), scope)
            if stale:
                raise AbortRequest((jsonify({"code": "stale_revision", "revision": stale,
                                             "error": "البيانات تغيّرت؛ أعد تحميل لوحة التشغيل."}), 409))
        try:
            fn(data, actor)
        except ValueError as exc:
            raise AbortRequest((jsonify({"error": str(exc)}), 409))
        result = ops_board.build_ops(data, day)
        result["revision"] = revision(data, scope)
        return jsonify(result)
    return with_data(mutate, scope)


@bp.post("/api/ops/<day>/depart")
def depart(day):
    day = _day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    body = json_payload()
    keys = body.get("keys")
    if not isinstance(keys, list) or not keys:
        return jsonify({"error": "اختر خدمة واحدة على الأقل."}), 400
    return _mutate(day, body, lambda data, actor: ops_board.depart(
        data, day, keys, actor, body.get("now")))


@bp.post("/api/ops/<day>/return")
def return_service(day):
    day = _day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    body = json_payload()
    keys = body.get("keys")
    if not isinstance(keys, list) or not keys:
        return jsonify({"error": "اختر خدمة واحدة على الأقل."}), 400
    return _mutate(day, body, lambda data, actor: ops_board.return_(
        data, day, keys, actor, body.get("now")))


@bp.post("/api/ops/<day>/undo")
def undo(day):
    day = _day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    body = json_payload()
    key = body.get("ref") or body.get("key")
    return _mutate(day, body, lambda data, actor: ops_board.undo(
        data, day, key, actor, body.get("now")), check_revision=False)


@bp.patch("/api/ops/<day>/time")
def edit_time(day):
    day = _day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    body = json_payload()
    return _mutate(day, body, lambda data, actor: ops_board.set_time(
        data, day, body.get("key", ""), str(body.get("time", "")),
        body.get("scope", "day"), actor))

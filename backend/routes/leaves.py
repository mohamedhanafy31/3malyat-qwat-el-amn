"""نقاط الراحات والإجازات."""
from datetime import timedelta

from flask import Blueprint, jsonify, request

from .. import changes
from ..constants import REST_DURATIONS
from ..leaves import MONTHLY_REST_SYSTEMS, build_leave, overlapping
from ..leaves import stats as leaves_stats_data
from ..models import Leave
from ..repo import Repos
from ..store import AbortRequest, load_data, with_data
from ..utils import json_payload, parse_date

bp = Blueprint("leaves", __name__)


@bp.post("/api/leaves")
def add_leave():
    payload = json_payload()

    def mutate(data):
        leaves = Repos(data).leaves
        leave, err = build_leave(payload, data, leaves.new_id())
        if err:
            raise AbortRequest((jsonify({"error": err}), 400))
        clash = overlapping(data, leave)
        if clash:
            raise AbortRequest((jsonify({"error": f"يوجد راحة متداخلة لنفس الشخص ({clash['start']} → {clash['end']})."}), 409))

        added = leaves.add(Leave.from_dict(leave))
        changes.record(data, "leave", leave["id"], "create", after=dict(leave))
        return jsonify(leaves.named(added)), 201

    return with_data(mutate)


@bp.patch("/api/leaves/<leave_id>")
def edit_leave(leave_id):
    payload = json_payload()

    def mutate(data):
        leaves = Repos(data).leaves
        found = leaves.find(leave_id)
        if not found:
            raise AbortRequest((jsonify({"error": "سجل الراحة غير موجود."}), 404))

        current = found.as_dict()
        leave, err = build_leave({**current, **payload}, data, leave_id)
        if err:
            raise AbortRequest((jsonify({"error": err}), 400))
        clash = overlapping(data, leave, ignore_id=leave_id)
        if clash:
            raise AbortRequest((jsonify({"error": f"يوجد راحة متداخلة لنفس الشخص ({clash['start']} → {clash['end']})."}), 409))

        updated = Leave.from_dict(leave)
        leaves.replace(updated)
        changes.record(data, "leave", leave_id, "update", before=current, after=dict(leave))
        return jsonify(leaves.named(updated))

    return with_data(mutate)


@bp.delete("/api/leaves/<leave_id>")
def delete_leave(leave_id):
    def mutate(data):
        leaves = Repos(data).leaves
        removed = leaves.find(leave_id)
        if not removed:
            raise AbortRequest((jsonify({"error": "سجل الراحة غير موجود."}), 404))
        leaves.remove(leave_id)
        changes.record(data, "leave", leave_id, "delete", before=removed.as_dict())
        return jsonify({"ok": True})

    return with_data(mutate)


@bp.post("/api/leaves/monthly")
def add_monthly_roster():
    """كشف الراحات الشهرية/النصف شهرية — تاريخ بداية واحد لكل ضابط، والنوع
    والمدة معروفين مسبقًا من نظام راحته. كل صف بيتبني بنفس build_leave()/
    overlapping() المستخدمين في أي إضافة راحة عادية، وصف واحد فاشل
    (تعارض مثلاً) مايوقفش تسجيل باقي الكشف."""
    payload = json_payload()
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return jsonify({"error": "entries لازم تكون قايمة."}), 400

    def mutate(data):
        repos = Repos(data)
        created, errors = [], []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            officer_id = str(entry.get("officer_id", "")).strip()
            start = str(entry.get("start", "")).strip()

            person = repos.people.find_in(officer_id, "officers")
            if not person:
                errors.append({"officer_id": officer_id, "error": "ضابط غير موجود."})
                continue
            system = person.rest_system
            if system not in MONTHLY_REST_SYSTEMS:
                errors.append({"officer_id": officer_id,
                               "error": "نظام راحة الضابط مش شهري ولا نصف شهري."})
                continue
            start_date = parse_date(start)
            if not start_date:
                errors.append({"officer_id": officer_id, "error": "تاريخ غير صحيح."})
                continue
            end = (start_date + timedelta(days=REST_DURATIONS[system] - 1)).isoformat()

            leave, err = build_leave({"person_id": officer_id, "type": system,
                                       "start": start, "end": end},
                                      data, repos.leaves.new_id())
            if err:
                errors.append({"officer_id": officer_id, "error": err})
                continue
            clash = overlapping(data, leave)
            if clash:
                errors.append({"officer_id": officer_id, "error":
                               f"يوجد راحة متداخلة لنفس الضابط ({clash['start']} → {clash['end']})."})
                continue
            created.append(repos.leaves.named(repos.leaves.add(Leave.from_dict(leave))))

        return jsonify({"created": created, "errors": errors})

    return with_data(mutate)


@bp.get("/api/leaves/stats")
def leaves_stats():
    data = load_data()
    filters = {
        "month_from": request.args.get("month_from", "").strip(),
        "month_to": request.args.get("month_to", "").strip(),
        "type": request.args.get("type", "").strip(),
        "status": request.args.get("status", "").strip(),
    }
    return jsonify(leaves_stats_data(data, filters))


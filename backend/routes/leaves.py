"""نقاط الراحات والإجازات."""
from datetime import timedelta

from flask import Blueprint, jsonify, request

from ..constants import REST_DURATIONS
from ..leaves import MONTHLY_REST_SYSTEMS, build_leave, overlapping
from ..leaves import stats as leaves_stats_data
from ..people import find_person
from ..store import AbortRequest, load_data, reserve_id, with_data
from ..utils import json_payload, parse_date

bp = Blueprint("leaves", __name__)


@bp.post("/api/leaves")
def add_leave():
    payload = json_payload()

    def mutate(data):
        leave_id = reserve_id(data, "LV", data["leaves"])
        leave, err = build_leave(payload, data, leave_id)
        if err:
            raise AbortRequest((jsonify({"error": err}), 400))
        clash = overlapping(data, leave)
        if clash:
            raise AbortRequest((jsonify({"error": f"يوجد راحة متداخلة لنفس الشخص ({clash['start']} → {clash['end']})."}), 409))

        data["leaves"].append(leave)
        data["leaves"].sort(key=lambda l: (l["start"], l.get("name", "")))
        return jsonify(leave), 201

    return with_data(mutate)


@bp.patch("/api/leaves/<leave_id>")
def edit_leave(leave_id):
    payload = json_payload()

    def mutate(data):
        current = next((l for l in data["leaves"] if l.get("id") == leave_id), None)
        if not current:
            raise AbortRequest((jsonify({"error": "سجل الراحة غير موجود."}), 404))

        merged = {**current, **payload}
        leave, err = build_leave(merged, data, leave_id)
        if err:
            raise AbortRequest((jsonify({"error": err}), 400))
        clash = overlapping(data, leave, ignore_id=leave_id)
        if clash:
            raise AbortRequest((jsonify({"error": f"يوجد راحة متداخلة لنفس الشخص ({clash['start']} → {clash['end']})."}), 409))

        data["leaves"] = [leave if l.get("id") == leave_id else l for l in data["leaves"]]
        data["leaves"].sort(key=lambda l: (l["start"], l.get("name", "")))
        return jsonify(leave)

    return with_data(mutate)


@bp.delete("/api/leaves/<leave_id>")
def delete_leave(leave_id):
    def mutate(data):
        before = len(data["leaves"])
        data["leaves"] = [l for l in data["leaves"] if l.get("id") != leave_id]
        if len(data["leaves"]) == before:
            raise AbortRequest((jsonify({"error": "سجل الراحة غير موجود."}), 404))
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
        created, errors = [], []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            officer_id = str(entry.get("officer_id", "")).strip()
            start = str(entry.get("start", "")).strip()

            person, category, _ = find_person(data, officer_id)
            if not person or category != "officers":
                errors.append({"officer_id": officer_id, "error": "ضابط غير موجود."})
                continue
            system = person.get("rest_system", "")
            if system not in MONTHLY_REST_SYSTEMS:
                errors.append({"officer_id": officer_id,
                               "error": "نظام راحة الضابط مش شهري ولا نصف شهري."})
                continue
            start_date = parse_date(start)
            if not start_date:
                errors.append({"officer_id": officer_id, "error": "تاريخ غير صحيح."})
                continue
            end = (start_date + timedelta(days=REST_DURATIONS[system] - 1)).isoformat()

            leave_id = reserve_id(data, "LV", data["leaves"])
            leave, err = build_leave({"person_id": officer_id, "type": system,
                                       "start": start, "end": end}, data, leave_id)
            if err:
                errors.append({"officer_id": officer_id, "error": err})
                continue
            clash = overlapping(data, leave)
            if clash:
                errors.append({"officer_id": officer_id, "error":
                               f"يوجد راحة متداخلة لنفس الضابط ({clash['start']} → {clash['end']})."})
                continue
            data["leaves"].append(leave)
            created.append(leave)

        if created:
            data["leaves"].sort(key=lambda l: (l["start"], l.get("name", "")))
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


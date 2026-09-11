"""اليومية التفصيلية (اللوحة) وتكليفات اليوم.

نقطة واحدة للتعديل: `/api/assignments/<day>` — واللوحة ويومية الضباط
الاتنين عرضين على نفس البيانات، فمفيش مزامنة ولا احتمال اختلاف بينهم.
"""
from flask import Blueprint, jsonify, request

from ..assignments import (
    apply_assignment, blank, clean_shift, for_day, guard_duplicate, new_id, peek_day,
    services_by_id,
)
from ..board import ASSIGNMENT_SECTIONS, build_board
from ..constants import SECTION_OCCASIONAL
from ..duty import summarise
from ..store import AbortRequest, load_data, with_data
from ..utils import canonical_day, json_payload

bp = Blueprint("board", __name__)


@bp.get("/api/board/<day>")
def get_board(day):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    return jsonify(build_board(load_data(), day))


@bp.post("/api/assignments/<day>")
def add_assignment(day):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    payload = json_payload()
    service_id = str(payload.get("service_id", "")).strip()
    if not service_id:
        return jsonify({"error": "لازم تختار خدمة من الكتالوج."}), 400

    def mutate(data):
        svc = services_by_id(data).get(service_id)
        if not svc:
            raise AbortRequest((jsonify({"error": "الخدمة غير موجودة في الكتالوج."}), 404))
        entries = for_day(data, day)
        row = blank(new_id(entries), svc["id"],
                    svc.get("section") or SECTION_OCCASIONAL)
        row, err, status = apply_assignment(data, day, row, payload, svc)
        if err:
            raise AbortRequest((jsonify({"error": err}), status))
        if "shift" not in payload:
            row["shift"] = clean_shift((svc.get("shifts") or [""])[0], svc)
        clash = guard_duplicate(data, day, row, ignore_id=None)
        if clash:
            raise AbortRequest((jsonify({"error": clash}), 409))
        entries.append(row)
        return jsonify(row), 201

    return with_data(mutate)


@bp.patch("/api/assignments/<day>/<assignment_id>")
def edit_assignment(day, assignment_id):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    payload = json_payload()

    def mutate(data):
        entries = for_day(data, day)
        row = next((e for e in entries if e["id"] == assignment_id), None)
        if not row:
            raise AbortRequest((jsonify({"error": "التكليف غير موجود."}), 404))
        services = services_by_id(data)
        if "service_id" in payload:
            svc = services.get(str(payload["service_id"]).strip())
            if not svc:
                raise AbortRequest((jsonify({"error": "الخدمة غير موجودة في الكتالوج."}), 404))
            row["service_id"] = svc["id"]
            row["shift"] = clean_shift(row.get("shift"), svc)
        svc = services.get(row["service_id"])
        row, err, status = apply_assignment(data, day, row, payload, svc)
        if err:
            raise AbortRequest((jsonify({"error": err}), status))
        clash = guard_duplicate(data, day, row, ignore_id=row["id"])
        if clash:
            raise AbortRequest((jsonify({"error": clash}), 409))
        return jsonify(row)

    return with_data(mutate)


@bp.delete("/api/assignments/<day>/<assignment_id>")
def delete_assignment(day, assignment_id):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400

    def mutate(data):
        entries = for_day(data, day)
        if not any(e["id"] == assignment_id for e in entries):
            raise AbortRequest((jsonify({"error": "التكليف غير موجود."}), 404))
        data["day_assignments"][day] = [e for e in entries if e["id"] != assignment_id]
        if not data["day_assignments"][day]:
            data["day_assignments"].pop(day, None)
        return jsonify({"ok": True})

    return with_data(mutate)


@bp.get("/api/assignments/<day>")
def list_assignments(day):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    data = load_data()
    return jsonify({"date": day, "assignments": peek_day(data, day),
                    "sections": ASSIGNMENT_SECTIONS,
                    "summary": summarise(data, day)["summary"]})


@bp.delete("/api/assignments/<day>")
def clear_day(day):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    clear_states = request.args.get("clear_states") == "1"

    def mutate(data):
        count = len(data.get("day_assignments", {}).get(day, []))
        if day in data.get("day_assignments", {}):
            data["day_assignments"].pop(day, None)
        if clear_states and day in data.get("day_officers", {}):
            data["day_officers"].pop(day, None)
        return jsonify({"ok": True, "deleted": count, "states_cleared": clear_states})

    return with_data(mutate)


"""اليومية التفصيلية (اللوحة) وتكليفات اليوم.

نقطة واحدة للتعديل: `/api/assignments/<day>` — واللوحة ويومية الضباط
الاتنين عرضين على نفس البيانات، فمفيش مزامنة ولا احتمال اختلاف بينهم.
"""
from flask import Blueprint, jsonify

from ..assignments import (
    blank, clean_conscripts, clean_shift, for_day, new_id, peek_day, services_by_id,
)
from ..board import ASSIGNMENT_SECTIONS, build_board
from ..checks import duplicate_of
from ..constants import SECTION_OCCASIONAL
from ..duty import summarise
from ..people import find_person, officers_on
from ..store import AbortRequest, load_data, with_data
from ..utils import json_payload, parse_date

bp = Blueprint("board", __name__)


def _day_or_400(day):
    if not parse_date(day):
        raise AbortRequest((jsonify({"error": "تاريخ غير صحيح."}), 400))


@bp.get("/api/board/<day>")
def get_board(day):
    if not parse_date(day):
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    return jsonify(build_board(load_data(), day))


def _clean_people(data, day, ids, want):
    """يتحقق إن كل شخص موجود وإنه من النوع الصح وإنه كان على القوة يومها.

    الضابط المتأرشف ينفع يتكلّف في يوم كان فيه بالقوة — ده مطلوب عشان
    تعديل الأيام القديمة يشتغل. قبل كده اللوحة كانت بتعرض النشطين بس
    بينما يومية التشغيل بتقبل الاتنين، فالصفحتين مكانوش شايفين نفس القايمة.
    """
    out = []
    on_force = {o["id"] for o in officers_on(data, day)} if want == "officers" else None
    for pid in ids or []:
        pid = str(pid).strip()
        if not pid or pid in out:
            continue
        person, category, _ = find_person(data, pid)
        if not person or category != want:
            raise AbortRequest((jsonify({
                "error": "ضابط غير موجود." if want == "officers" else "فرد غير موجود."}), 404))
        if on_force is not None and pid not in on_force:
            raise AbortRequest((jsonify({
                "error": f"«{person.get('name', '')}» لم يكن على القوة في هذا اليوم."}), 400))
        out.append(pid)
    return out


def _guard_duplicate(data, day, row, ignore_id):
    """التكرار الحرفي بس هو الممنوع: نفس الشخص على نفس الخدمة ونفس الفترة
    مرتين. باقي «التعارضات» بتتعرض كتنبيهات — الأرشيف فيه ضباط على
    خدمتين في نفس الفترة فعلًا (20/8: تبة ضرب النار + كنترول الازهر ليل)."""
    people = (row.get("officer_ids") or []) + (row.get("personnel_ids") or [])
    if not people:
        return
    clash = duplicate_of(data, day, row["service_id"], row.get("shift"),
                         people, ignore_id=ignore_id)
    if clash:
        raise AbortRequest((jsonify({
            "error": "الشخص ده متكلّف بنفس الخدمة ونفس الفترة في خانة تانية."}), 409))


def _apply(data, day, row, payload, svc):
    if "shift" in payload:
        row["shift"] = clean_shift(payload["shift"], svc)
    if "section" in payload:
        section = str(payload["section"]).strip()
        row["section"] = section or (svc or {}).get("section") or SECTION_OCCASIONAL
    if "officer_ids" in payload:
        row["officer_ids"] = _clean_people(data, day, payload["officer_ids"], "officers")
    if "personnel_ids" in payload:
        row["personnel_ids"] = _clean_people(data, day, payload["personnel_ids"], "personnel")
    if "conscripts" in payload:
        row["conscripts"] = clean_conscripts(payload["conscripts"])
    if "tags" in payload:
        row["tags"] = [str(t).strip() for t in payload["tags"] if str(t).strip()]
        for tag in row["tags"]:
            if tag not in data["service_tags"]:
                data["service_tags"].append(tag)
    for key in ("weapon", "time", "party", "label_override", "note"):
        if key in payload:
            row[key] = str(payload[key]).strip()
    return row


@bp.post("/api/assignments/<day>")
def add_assignment(day):
    if not parse_date(day):
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
        _apply(data, day, row, payload, svc)
        if "shift" not in payload:
            row["shift"] = clean_shift((svc.get("shifts") or [""])[0], svc)
        _guard_duplicate(data, day, row, ignore_id=None)
        entries.append(row)
        return jsonify(row), 201

    return with_data(mutate)


@bp.patch("/api/assignments/<day>/<assignment_id>")
def edit_assignment(day, assignment_id):
    if not parse_date(day):
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
        _apply(data, day, row, payload, svc)
        _guard_duplicate(data, day, row, ignore_id=row["id"])
        return jsonify(row)

    return with_data(mutate)


@bp.delete("/api/assignments/<day>/<assignment_id>")
def delete_assignment(day, assignment_id):
    if not parse_date(day):
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
    if not parse_date(day):
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    data = load_data()
    return jsonify({"date": day, "assignments": peek_day(data, day),
                    "sections": ASSIGNMENT_SECTIONS,
                    "summary": summarise(data, day)["summary"]})

"""اليومية التفصيلية (اللوحة) وتكليفات اليوم.

نقطة واحدة للتعديل: `/api/assignments/<day>` — واللوحة ويومية الضباط
الاتنين عرضين على نفس البيانات، فمفيش مزامنة ولا احتمال اختلاف بينهم.

اسم الخدمة حر بيكتبه المشغّل على الخانة نفسها — مفيش كتالوج منفصل
يتحقق منه الاسم أو يفرض تصنيفها.

الحفظ هنا **مابيسجّلش** في سجل التغييرات — التسجيل بيحصل وقت تأكيد
اليومية بس (`backend/confirm.py`)، عشان السجل يبقى فيه القرارات
المعتمدة مش المسوّدات.
"""
from flask import Blueprint, jsonify, request

from .. import changes
from .. import confirm as confirm_lib
from .. import day_status
from ..assignments import apply_assignment, blank, for_day, guard_duplicate, new_id, peek_day
from ..board import ASSIGNMENT_SECTIONS, build_board
from ..constants import SECTION_OCCASIONAL, SERVICE_KINDS
from ..duty import summarise
from ..repo import Repos
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
    name = str(payload.get("name", "")).strip()
    if not name:
        return jsonify({"error": "اسم الخدمة مطلوب."}), 400
    kind = str(payload.get("kind", "")).strip()
    if kind not in SERVICE_KINDS:
        return jsonify({"error": "تصنيف الخدمة غير صحيح."}), 400

    def mutate(data):
        ok, err = day_status.check_open(data, day)
        if not ok:
            raise AbortRequest((jsonify({"error": err}), 409))
        entries = for_day(data, day)
        section = str(payload.get("section", "")).strip() or SECTION_OCCASIONAL
        row = blank(new_id(entries), name, section, kind=kind)
        row, err, status = apply_assignment(data, day, row, payload)
        if err:
            raise AbortRequest((jsonify({"error": err}), status))
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
        ok, lock_err = day_status.check_open(data, day)
        if not ok:
            raise AbortRequest((jsonify({"error": lock_err}), 409))
        entries = for_day(data, day)
        row = next((e for e in entries if e["id"] == assignment_id), None)
        if not row:
            raise AbortRequest((jsonify({"error": "التكليف غير موجود."}), 404))
        row, err, status = apply_assignment(data, day, row, payload)
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
        ok, lock_err = day_status.check_open(data, day)
        if not ok:
            raise AbortRequest((jsonify({"error": lock_err}), 409))
        if not Repos(data).days.remove_assignment(day, assignment_id):
            raise AbortRequest((jsonify({"error": "التكليف غير موجود."}), 404))
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


@bp.get("/api/board/<day>/confirm")
def get_confirm(day):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    return jsonify(confirm_lib.state_of(load_data(), day))


@bp.post("/api/board/<day>/confirm")
def confirm_day(day):
    """تأكيد اليومية — بيعتمد الحالي وبيسجّل الفرق عن آخر تأكيد.

    مسموح يتعمل أكتر من مرة في اليوم؛ التأكيد اللي مالوش فرق بيتسجّل
    كـ«إعادة تأكيد» عشان يفضل واضح إن حد راجع اليومية الساعة دي.
    """
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    payload = json_payload()
    by = str(payload.get("confirmed_by", "")).strip()

    def mutate(data):
        ok, err = day_status.check_open(data, day)
        if not ok:
            raise AbortRequest((jsonify({"error": err}), 409))
        summary, events = confirm_lib.confirm_day(data, day, by)
        for ev in events:
            changes.record(data, ev["entity"], ev["entity_id"], ev["action"],
                           before=ev["before"], after=ev["after"], text=ev["text"],
                           day=day, ts=summary["at"])
        if summary["first"]:
            note = f"تأكيد أول ليومية {day} — {summary['count']} خدمة"
        elif not summary["changes"]:
            note = f"إعادة تأكيد ليومية {day} — من غير أي تغيير"
        else:
            note = f"تأكيد يومية {day} — {summary['changes']} تغيير"
        changes.record(data, "day_confirm", day, "confirm", after=dict(summary),
                       text=note, day=day, ts=summary["at"])
        return jsonify(summary), 201

    return with_data(mutate)


@bp.delete("/api/assignments/<day>")
def clear_day(day):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    clear_states = request.args.get("clear_states") == "1"

    def mutate(data):
        ok, lock_err = day_status.check_open(data, day)
        if not ok:
            raise AbortRequest((jsonify({"error": lock_err}), 409))
        days = Repos(data).days
        loaded = days.get(day)
        count = len(loaded.assignments)
        loaded.assignments = []
        if clear_states:
            loaded.officer_states = {}
        days.save(loaded)
        return jsonify({"ok": True, "deleted": count, "states_cleared": clear_states})

    return with_data(mutate)

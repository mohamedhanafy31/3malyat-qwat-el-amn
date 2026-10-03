"""اليومية التفصيلية (اللوحة) وتكليفات اليوم.

نقطة واحدة للتعديل: `/api/assignments/<day>` — واللوحة ويومية الضباط
الاتنين عرضين على نفس البيانات، فمفيش مزامنة ولا احتمال اختلاف بينهم.

اسم الخدمة حر بيكتبه المشغّل على الخانة نفسها — مفيش كتالوج منفصل
يتحقق منه الاسم أو يفرض تصنيفها.

الحفظ هنا **مابيسجّلش** في سجل التغييرات — التسجيل بيحصل وقت تأكيد
اليومية بس (`backend/confirm.py`)، عشان السجل يبقى فيه القرارات
المعتمدة مش المسوّدات.
"""
from copy import deepcopy
from flask import Blueprint, jsonify, request, send_file

from .. import changes
from .. import confirm as confirm_lib
from .. import day_status
from .. import target_defaults
from ..assignments import (
    apply_assignment, blank, for_day, guard_duplicate, new_id, peek_day, vacant_twin,
)
from ..board import (
    ASSIGNMENT_SECTIONS, build_board, canonical_section_name, copy_section_rows, section_history, section_source,
    move_assignment, place_assignment_after, set_slot_officers, set_target_officers,
)
from ..board_export import build_docx
from ..constants import SECTION_OCCASIONAL, SERVICE_KINDS
from ..duty import summarise
from ..daily_view import build as build_daily_view
from ..day_open import needs_prepare, prepare
from ..repo import Repos
from ..store import ALL_DAYS, AbortRequest, load_data, revision, stale_revision, with_data
from ..utils import around, canonical_day, json_payload, too_long

bp = Blueprint("board", __name__)


@bp.get("/api/board/<day>")
def get_board(day):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400

    scope = around(day, -1, 0)
    data = load_data(scope)
    pending = needs_prepare(data, day, include_inspections=True)
    preview = deepcopy(data)
    if pending:
        prepare(preview, day, include_inspections=True)
    payload = build_board(preview, day)
    payload.update(revision=revision(data, [day]), preparation_pending=pending)
    return jsonify(payload)


@bp.get("/api/board/<day>/section-history")
def get_section_history(day):
    """آخر تعريفات خدمات لقسم حر في يوم آخر، من غير الأشخاص المكلّفين."""
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    section = canonical_section_name(request.args.get("section", "").strip())
    if not section:
        return jsonify({"error": "اسم القسم مطلوب."}), 400
    length_error = too_long({"section": section}, "section")
    if length_error:
        return jsonify({"error": length_error}), 400
    # اليوم ده + يوم المصدر اللي فهرس أقسام اللوحة بيشاور عليه
    def scope(view):
        return [day, *filter(None, [section_source(view.index.board_sections(), day, section)])]

    return jsonify(section_history(load_data(scope), day, section))


@bp.post("/api/board/<day>/section-copy")
def copy_section(day):
    """ينسخ قوالب خدمات مختارة للقسم نفسه، ويترك التسكين البشري فاضيًا."""
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    payload = json_payload()
    section = canonical_section_name(payload.get("section", "").strip())
    source_day = canonical_day(payload.get("source_day"))
    if not source_day:
        return jsonify({"error": "تاريخ يوم المصدر غير صحيح."}), 400
    length_error = too_long({"section": section}, "section")
    if length_error:
        return jsonify({"error": length_error}), 400

    def mutate(data):
        prepare(data, day, include_inspections=True)
        stale = stale_revision(data, payload.get("revision"), [day])
        if stale:
            raise AbortRequest((jsonify({"code": "stale_revision", "revision": stale,
                                         "error": "البيانات تغيّرت؛ أعد تحميل اليوم."}), 409))
        ok, err = day_status.check_open(data, day)
        if not ok:
            raise AbortRequest((jsonify({"error": err}), 409))
        result, error, status = copy_section_rows(
            data, day, section, source_day, payload.get("ids"))
        if error:
            raise AbortRequest((jsonify({"error": error}), status))
        return jsonify(result), 201

    return with_data(mutate, [day, source_day])


@bp.get("/api/board/<day>/export.docx")
def export_board_docx(day):
    """اليومية التفصيلية كملف Word حقيقي — نفس البيانات اللي `/api/board`
    بيرجّعها، مبنية بنفس شكل الورقة الرسمية (`backend/board_export.py`)
    بدل الاعتماد على طباعة المتصفح."""
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    board = build_board(load_data(around(day, -1, 0)), day)
    buf = build_docx(board)
    return send_file(buf, as_attachment=True, download_name=f"اليومية التفصيلية {day}.docx",
                     mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


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
        stale = stale_revision(data, payload.get("revision"), [day])
        if stale:
            raise AbortRequest((jsonify({"code": "stale_revision", "revision": stale,
                                         "error": "البيانات تغيّرت؛ أعد تحميل اليوم."}), 409))
        prepare(data, day, include_inspections=True)
        ok, err = day_status.check_open(data, day)
        if not ok:
            raise AbortRequest((jsonify({"error": err}), 409))
        entries = for_day(data, day)
        section = canonical_section_name(payload.get("section", "").strip()) or SECTION_OCCASIONAL
        row = blank(new_id(data, day, entries), name, section, kind=kind)
        row, err, status = apply_assignment(data, day, row, payload)
        if err:
            raise AbortRequest((jsonify({"error": err}), status))
        clash = guard_duplicate(data, day, row, ignore_id=None)
        if clash:
            raise AbortRequest((jsonify({"error": clash}), 409))
        twin = None if payload.get("allow_duplicate") is True else vacant_twin(data, day, row)
        if twin:
            raise AbortRequest((jsonify({
                "error": "توجد خانة شاغرة بنفس الاسم والقسم والتصنيف والفترة في هذا اليوم.",
                "code": "possible_duplicate", "existing_id": twin}), 409))
        entries.append(row)
        place_assignment_after(data, day, row["id"], payload.get("after_id"))
        result = dict(row)
        result["daily"] = build_daily_view(data, day)
        result["revision"] = result["daily"]["revision"]
        return jsonify(result), 201

    return with_data(mutate, around(day, -1, 0))


@bp.patch("/api/assignments/<day>/<assignment_id>")
def edit_assignment(day, assignment_id):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    payload = json_payload()

    def mutate(data):
        prepare(data, day, include_inspections=True)
        stale = stale_revision(data, payload.get("revision"), [day])
        if stale:
            raise AbortRequest((jsonify({"code": "stale_revision", "revision": stale,
                                         "error": "البيانات تغيّرت؛ أعد تحميل اليوم."}), 409))
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
        result = dict(row)
        result["daily"] = build_daily_view(data, day)
        result["revision"] = result["daily"]["revision"]
        return jsonify(result)

    return with_data(mutate, [day])


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
        result = {"ok": True, "daily": build_daily_view(data, day)}
        result["revision"] = result["daily"]["revision"]
        return jsonify(result)

    return with_data(mutate, [day])


@bp.post("/api/assignments/<day>/<assignment_id>/move")
def move_assignment_row(day, assignment_id):
    """يغيّر ترتيب العرض فقط؛ ترتيب سجل التكليفات التشغيلي يفضل ثابت."""
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    direction = str(json_payload().get("direction", "")).strip()
    if direction not in ("up", "down"):
        return jsonify({"error": "يجب أن يكون اتجاه النقل إلى أعلى أو إلى أسفل."}), 400

    def mutate(data):
        ok, lock_err = day_status.check_open(data, day)
        if not ok:
            raise AbortRequest((jsonify({"error": lock_err}), 409))
        error, status = move_assignment(data, day, assignment_id, direction)
        if error:
            raise AbortRequest((jsonify({"error": error}), status))
        return jsonify(build_board(data, day))

    return with_data(mutate, around(day, -1, 0))


@bp.get("/api/assignments/<day>")
def list_assignments(day):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    data = load_data([day])
    return jsonify({"date": day, "assignments": peek_day(data, day),
                    "sections": ASSIGNMENT_SECTIONS,
                    "summary": summarise(data, day)["summary"]})


@bp.put("/api/board/<day>/target/<name>")
def set_target(day, name):
    """تعيين (أو شيل) الضابط المعيّن بهدف من الأهداف الثابتة الثمانية.

    الأهداف قايمة مغلقة (`board.target_row_names`) — الاسم والتصنيف
    ثابتين، فمفيش داعي لمودال الخانة العام هنا. قائد الهدف خانة محسوبة
    من منصب الضابط، بتتغيّر من صفحة بيانات الضابط مش من هنا.
    """
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    payload = json_payload()

    def mutate(data):
        ok, err = day_status.check_open(data, day)
        if not ok:
            raise AbortRequest((jsonify({"error": err}), 409))
        _row, error, status = set_target_officers(data, day, name, payload.get("officer_ids"))
        if error:
            raise AbortRequest((jsonify({"error": error}), status))
        return jsonify(build_board(data, day))

    return with_data(mutate, around(day, -1, 0))


@bp.put("/api/board/<day>/slot/<section>/<shift>")
def set_slot(day, section, shift):
    """تعيين (أو شيل) الضابط في فترة من كتلة ثابتة (ضابط عظيم الإدارة/
    الأمن/المعسكر الفرعي) — نفس فكرة `set_target` بالظبط، بس المفتاح
    (قسم، فترة) مش اسم لأن اسم الكتلة ثابت وواحد على صفّيها الاتنين.
    """
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    payload = json_payload()

    def mutate(data):
        ok, err = day_status.check_open(data, day)
        if not ok:
            raise AbortRequest((jsonify({"error": err}), 409))
        _row, error, status = set_slot_officers(data, day, section, shift,
                                                payload.get("officer_ids"))
        if error:
            raise AbortRequest((jsonify({"error": error}), status))
        return jsonify(build_board(data, day))

    return with_data(mutate, around(day, -1, 0))


@bp.get("/api/board/<day>/confirm")
def get_confirm(day):
    day = canonical_day(day)
    if not day:
        return jsonify({"error": "تاريخ غير صحيح."}), 400
    return jsonify(confirm_lib.state_of(load_data([day]), day))


@bp.get("/api/board/unconfirmed")
def unconfirmed_days():
    """List recorded daily rosters that have not been confirmed yet."""
    data = load_data(ALL_DAYS)
    days = []
    for day in Repos(data).days.assignment_dates():
        state = confirm_lib.state_of(data, day)
        if not state.get("confirmed") or state.get("pending"):
            days.append({"day": day, **state})
    return jsonify({"days": days, "count": len(days)})


@bp.post("/api/board/confirm-unconfirmed")
def confirm_unconfirmed_days():
    """Confirm every requested recorded roster that is still unconfirmed.

    This explicit archive operation may include historical days that are
    auto-closed; confirmation records an audit snapshot without changing the
    roster itself.
    """
    payload = json_payload()
    by = str(payload.get("confirmed_by", "")).strip()
    requested = payload.get("days")
    if requested is not None and not isinstance(requested, list):
        return jsonify({"error": "قائمة الأيام يجب أن تكون قائمة."}), 400

    def mutate(data):
        available = set(Repos(data).days.assignment_dates())
        candidates = sorted(available if requested is None else
                            {str(day).strip() for day in requested if str(day).strip()})
        summaries = []
        for day in candidates:
            if day not in available:
                continue
            state = confirm_lib.state_of(data, day)
            if state.get("confirmed") and not state.get("pending"):
                continue
            summary, events = confirm_lib.confirm_day(data, day, by)
            target_defaults.refresh_after_confirmation(data, day)
            for ev in events:
                changes.record(data, ev["entity"], ev["entity_id"], ev["action"],
                               before=ev["before"], after=ev["after"], text=ev["text"],
                               day=day, ts=summary["at"])
            changes.record(data, "day_confirm", day, "confirm", after=dict(summary),
                           text=f"تأكيد جماعي ليومية {day}", day=day, ts=summary["at"])
            summaries.append(summary)
        return jsonify({"confirmed": summaries, "count": len(summaries)})

    return with_data(mutate, ALL_DAYS)


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
        # البذر والتحديث التلقائي مسودة صامتة؛ سجل التغييرات يفضل خاص
        # باليومية التي أكدها المشغّل فقط.
        target_defaults.refresh_after_confirmation(data, day)
        for ev in events:
            changes.record(data, ev["entity"], ev["entity_id"], ev["action"],
                           before=ev["before"], after=ev["after"], text=ev["text"],
                           day=day, ts=summary["at"])
        if summary["first"]:
            note = f"تأكيد أول ليومية {day} — عدد الخدمات: {summary['count']}"
        elif not summary["changes"]:
            note = f"إعادة تأكيد ليومية {day} — بلا أي تغيير"
        else:
            note = f"تأكيد يومية {day} — عدد التغييرات: {summary['changes']}"
        changes.record(data, "day_confirm", day, "confirm", after=dict(summary),
                       text=note, day=day, ts=summary["at"])
        return jsonify(summary), 201

    # اليوم، واليوم التالي (بذر أهدافه من التأكيد ده)، واللقطات القديمة
    # اللي هتتشال من `day_confirm`
    def scope(view):
        return [*around(day, 1), *confirm_lib.snapshot_scope(view.index, day)]

    return with_data(mutate, scope)


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

    return with_data(mutate, [day])

"""نقاط الراحات والإجازات."""
from datetime import timedelta

from flask import Blueprint, jsonify, request, send_file

from .. import changes, day_status, rest_suspension, retro
from ..constants import REST_DURATIONS
from ..leaves import MONTHLY_REST_SYSTEMS, build_leave, overlapping, validate_weekly_extra
from ..leaves import stats as leaves_stats_data
from ..leaves_export import build_monthly_docx, build_weekly_docx
from ..models import Leave
from ..people import effective
from ..repo import Repos
from ..store import AbortRequest, load_data, with_data
from ..utils import json_payload, parse_date

bp = Blueprint("leaves", __name__)


def _monthly_duration(entry, system):
    """مدة صف الكشف: الافتراضي القياسي، وقابلة للتعديل من 1 إلى 120 يومًا."""
    raw = entry.get("days", REST_DURATIONS[system])
    if isinstance(raw, bool):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if 1 <= value <= 120 else None


def _leave_span(lv):
    return f"{lv.get('type', '')} {lv.get('start', '')} ← {lv.get('end', '')}"


def _leave_text(data, action, before=None, after=None):
    """جملة السجل لتغيير راحة — نفس صيغة إلغاء/إيقاف الراحة في rest_suspension."""
    lv = after or before
    name = Repos(data).leaves.name_of(lv.get("person_id", ""))
    if action == "create":
        return f"تسجيل راحة {name} ({_leave_span(after)})"
    if action == "delete":
        return f"حذف راحة {name} ({_leave_span(before)})"
    if _leave_span(before) == _leave_span(after):
        return f"تعديل بيانات راحة {name} ({_leave_span(after)})"
    return f"تعديل راحة {name}: ({_leave_span(before)}) ← ({_leave_span(after)})"


@bp.post("/api/leaves")
def add_leave():
    payload = json_payload()

    def mutate(data):
        leaves = Repos(data).leaves
        leave, err = build_leave(payload, data, leaves.new_id())
        if err:
            raise AbortRequest((jsonify({"error": err}), 400))
        extra_err = validate_weekly_extra(data, leave, day_status.today_iso())
        if extra_err:
            raise AbortRequest((jsonify({"error": extra_err}), 400))
        blocked = rest_suspension.blocking(data, leave)
        if blocked:
            raise AbortRequest((jsonify({"error": blocked, "suspended": True}), 409))
        clash = overlapping(data, leave)
        if clash:
            raise AbortRequest((jsonify({"error": f"توجد راحة متداخلة للشخص نفسه ({clash['start']} → {clash['end']})."}), 409))

        # الراحة دي بتمس يوم/أيام مقفولة (فاتت بالفعل)؟ مسموح، بس محتاج
        # سبب مكتوب — وإلا أصل القوة وحالة الضابط في اليوم ده بتتغيّر من
        # غير أي علم لحد راجع أو أكّد اليومية بالفعل.
        closed = retro.closed_days_in(data, leave["start"], leave["end"])
        reason = retro.require_reason(closed)

        added = leaves.add(Leave.from_dict(leave))
        changes.record(data, "leave", leave["id"], "create", after=dict(leave),
                       text=_leave_text(data, "create", after=leave))
        if closed:
            retro.log_retro(data, "leave", leave["id"], closed, reason, after=dict(leave))
        return jsonify(leaves.named(added)), 201

    return with_data(mutate, retro.status_scope)


@bp.patch("/api/leaves/<leave_id>")
def edit_leave(leave_id):
    payload = json_payload()

    def mutate(data):
        leaves = Repos(data).leaves
        found = leaves.find(leave_id)
        if not found:
            raise AbortRequest((jsonify({"error": "سجل الراحة غير موجود."}), 404))

        current = found.as_dict()
        leave, err = build_leave({**current, **payload}, data, leave_id,
                                 current_type=current.get("type"))
        if err:
            raise AbortRequest((jsonify({"error": err}), 400))
        rest_suspension.edit_guard(current, leave)
        blocked = rest_suspension.blocking(data, leave, current=current)
        if blocked:
            raise AbortRequest((jsonify({"error": blocked, "suspended": True}), 409))
        clash = overlapping(data, leave, ignore_id=leave_id)
        if clash:
            raise AbortRequest((jsonify({"error": f"توجد راحة متداخلة للشخص نفسه ({clash['start']} → {clash['end']})."}), 409))

        # المدى القديم والجديد الاتنين — تعديل بيقصّر راحة كانت بتغطي يوم
        # مقفول برضو تعديل بأثر رجعي عليه، مش بس المدى الجديد.
        closed = sorted(set(retro.closed_days_in(data, current.get("start", ""), current.get("end", ""))
                            + retro.closed_days_in(data, leave["start"], leave["end"])))
        reason = retro.require_reason(closed)

        updated = Leave.from_dict(leave)
        leaves.replace(updated)
        changes.record(data, "leave", leave_id, "update", before=current, after=dict(leave),
                       text=_leave_text(data, "update", before=current, after=leave))
        if closed:
            retro.log_retro(data, "leave", leave_id, closed, reason, before=current, after=dict(leave))
        return jsonify(leaves.named(updated))

    return with_data(mutate, retro.status_scope)


@bp.delete("/api/leaves/<leave_id>")
def delete_leave(leave_id):
    def mutate(data):
        leaves = Repos(data).leaves
        removed = leaves.find(leave_id)
        if not removed:
            raise AbortRequest((jsonify({"error": "سجل الراحة غير موجود."}), 404))

        closed = retro.closed_days_in(data, removed.start, removed.end)
        reason = retro.require_reason(closed)

        leaves.remove(leave_id)
        changes.record(data, "leave", leave_id, "delete", before=removed.as_dict(),
                       text=_leave_text(data, "delete", before=removed.as_dict()))
        if closed:
            retro.log_retro(data, "leave", leave_id, closed, reason, before=removed.as_dict())
        return jsonify({"ok": True})

    return with_data(mutate, retro.status_scope)


@bp.post("/api/leaves/<leave_id>/stop")
def stop_leave(leave_id):
    """إيقاف راحة ضابط قبل نهايتها — `on` أول يوم رجوع (الافتراضي النهاردة)،
    والسبب إجباري. راحة لسه ما بدأتش بتتلغي بالكامل."""
    payload = json_payload()

    def mutate(data):
        result = rest_suspension.stop_leave(data, leave_id, payload.get("reason", ""),
                                            on=payload.get("on") or None,
                                            today=day_status.today_iso())
        return jsonify(result)

    return with_data(mutate, retro.status_scope)


@bp.post("/api/leaves/monthly")
def add_monthly_roster():
    """كشف الراحات الشهرية/النصف شهرية — تاريخ بداية واحد لكل ضابط، والنوع
    والمدة معروفين مسبقًا من نظام راحته. كل صف بيتبني بنفس build_leave()/
    overlapping() المستخدمين في أي إضافة راحة عادية، وصف واحد فاشل
    (تعارض مثلاً) مايوقفش تسجيل باقي الكشف."""
    payload = json_payload()
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return jsonify({"error": "يجب أن تكون المدخلات قائمة."}), 400

    def mutate(data):
        repos = Repos(data)
        created, errors = [], []

        # مرور أول بس يحسب المدى (من غير أي كتابة) عشان نجمع كل الأيام
        # المقفولة اللي الكشف كله هيمسّها، ونسأل سبب واحد للكشف كله —
        # مش سبب لكل صف لوحده.
        ranges = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            officer_id = str(entry.get("officer_id", "")).strip()
            start = str(entry.get("start", "")).strip()
            person = repos.people.find_in(officer_id, "officers")
            system = effective(person.as_dict(), start).get("rest_system") if person else ""
            if not person or system not in MONTHLY_REST_SYSTEMS:
                continue
            start_date = parse_date(start)
            if not start_date:
                continue
            duration = _monthly_duration(entry, system)
            if duration is None:
                continue
            end = (start_date + timedelta(days=duration - 1)).isoformat()
            # صف هيترفض بسبب وقف الراحات مايستاهلش يطلب سبب تعديل بأثر رجعي
            if rest_suspension.blocking(data, {"person_id": officer_id, "type": system,
                                               "start": start, "end": end}):
                continue
            ranges.append((start, end))
            leave_id = str(entry.get("leave_id", "") or "").strip()
            if leave_id:
                found = repos.leaves.find(leave_id)
                if found:
                    ranges.append((found.start, found.end))

        closed = sorted({d for s, e in ranges for d in retro.closed_days_in(data, s, e)})
        reason = retro.require_reason(closed)

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            officer_id = str(entry.get("officer_id", "")).strip()
            start = str(entry.get("start", "")).strip()
            leave_id = str(entry.get("leave_id", "") or "").strip()

            person = repos.people.find_in(officer_id, "officers")
            if not person:
                errors.append({"officer_id": officer_id, "error": "ضابط غير موجود."})
                continue
            system = effective(person.as_dict(), start).get("rest_system")
            if system not in MONTHLY_REST_SYSTEMS:
                errors.append({"officer_id": officer_id,
                               "error": "نظام راحة الضابط ليس شهريًا ولا نصف شهري."})
                continue
            start_date = parse_date(start)
            if not start_date:
                errors.append({"officer_id": officer_id, "error": "تاريخ غير صحيح."})
                continue
            duration = _monthly_duration(entry, system)
            if duration is None:
                errors.append({"officer_id": officer_id,
                               "error": "المدة يجب أن تكون من يوم واحد إلى 120 يومًا."})
                continue
            end = (start_date + timedelta(days=duration - 1)).isoformat()

            current_obj = repos.leaves.find(leave_id) if leave_id else None
            if leave_id and (not current_obj or current_obj.person_id != officer_id
                             or current_obj.type != system):
                errors.append({"officer_id": officer_id,
                               "error": "سجل الراحة المطلوب تعديله غير صحيح."})
                continue
            current = current_obj.as_dict() if current_obj else {}
            leave, err = build_leave({**current, "person_id": officer_id, "type": system,
                                       "start": start, "end": end},
                                      data, leave_id or repos.leaves.new_id())
            if err:
                errors.append({"officer_id": officer_id, "error": err})
                continue
            blocked = rest_suspension.blocking(data, leave)
            if blocked:
                errors.append({"officer_id": officer_id, "error": blocked})
                continue
            if current_obj:
                rest_suspension.edit_guard(current, leave)
            clash = overlapping(data, leave, ignore_id=leave_id or None)
            if clash:
                errors.append({"officer_id": officer_id, "error":
                    f"توجد راحة متداخلة للضابط نفسه ({clash['start']} → {clash['end']})."})
                continue
            saved = Leave.from_dict(leave)
            if current_obj:
                repos.leaves.replace(saved)
                changes.record(data, "leave", leave["id"], "update", before=current,
                               after=dict(leave), text=_leave_text(
                                   data, "update", before=current, after=leave))
            else:
                repos.leaves.add(saved)
                changes.record(data, "leave", leave["id"], "create", after=dict(leave),
                               text=_leave_text(data, "create", after=leave))
            row_closed = sorted(set(
                retro.closed_days_in(data, leave["start"], leave["end"])
                + (retro.closed_days_in(data, current.get("start", ""), current.get("end", ""))
                   if current_obj else [])
            ))
            if row_closed:
                retro.log_retro(data, "leave", leave["id"], row_closed, reason,
                                before=current or None, after=dict(leave))
            created.append(repos.leaves.named(saved))

        return jsonify({"created": created, "errors": errors})

    return with_data(mutate, retro.status_scope)


@bp.get("/api/leaves/stats")
def leaves_stats():
    data = load_data(())
    filters = {
        "month_from": request.args.get("month_from", "").strip(),
        "month_to": request.args.get("month_to", "").strip(),
        "type": request.args.get("type", "").strip(),
        "status": request.args.get("status", "").strip(),
    }
    return jsonify(leaves_stats_data(data, filters))


def _export_day():
    raw = request.args.get("on", "").strip() or day_status.today_iso()
    return parse_date(raw)


@bp.get("/api/leaves/monthly/export.docx")
def export_monthly_roster():
    on = _export_day()
    if not on:
        return jsonify({"error": "تاريخ الكشف غير صحيح."}), 400
    output = build_monthly_docx(load_data(()), on)
    return send_file(output, as_attachment=True,
                     download_name=f"كشف الراحات الشهرية {on.isoformat()}.docx",
                     mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@bp.get("/api/leaves/weekly/export.docx")
def export_weekly_roster():
    on = _export_day()
    if not on:
        return jsonify({"error": "تاريخ الكشف غير صحيح."}), 400
    output = build_weekly_docx(load_data(()), on)
    return send_file(output, as_attachment=True,
                     download_name=f"كشف الراحات الاسبوعية {on.isoformat()}.docx",
                     mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

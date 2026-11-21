"""فرق الضباط — الفرقة نفسها والتحاق الضباط بيها."""
from flask import Blueprint, jsonify, request, send_file
from io import BytesIO

from .. import retro
from ..courses import (
    build_course, build_term, by_id, by_officer, courses, new_course_id,
    new_term_id, overlapping, summary, terms,
)
from ..repo import PeopleRepo, Repos
from ..store import AbortRequest, load_data, with_data
from ..labels import RANK_SHORT
from ..utils import command_priority_map, json_payload, rank_key
from ..register_export import build_register_docx, register_file_name

bp = Blueprint("courses", __name__)


@bp.get("/api/courses")
def list_courses():
    """العرضين مع بعض: تجميع بالفرقة وتجميع بالضابط — نفس البيانات
    بمدخلين مختلفين، فنداء واحد يكفي والتبديل بينهم من غير تحميل."""
    data = load_data(())
    return jsonify({"courses": summary(data), "officers": by_officer(data)})


def _term_line(term):
    who = f"{_export_rank(term.get('officer_role'))}/ {term['officer_name']}"
    period = _term_period(term)
    return f"{who} ({period})" if period else who


def _export_rank(role):
    role = str(role or "").strip()
    if role == "ملازم أول":
        return "م.أول"
    return RANK_SHORT.get(role, role)


def _term_period(term):
    start, end = _short_date(term.get("start")), _short_date(term.get("end"))
    if start and end:
        return f"{start} – {end}"
    return start or end


def _numbered_entries(terms, label):
    return [{"label": f"{index}- {label(term)}", "period": _term_period(term)}
            for index, term in enumerate(terms, 1)]


def _short_date(value):
    """2026-09-05 → 5/9/26 عشان سطر الالتحاق ما يلفش."""
    try:
        year, month, day = str(value or "").split("-")
        return f"{int(day)}/{int(month)}/{year[2:]}"
    except ValueError:
        return str(value or "")


@bp.get("/api/courses/export.docx")
def export_courses():
    data = load_data(())
    view = request.args.get("view", "course")
    q = request.args.get("q", "").strip()
    if view == "officer":
        records = by_officer(data)
        if q:
            records = [o for o in records if q in o["name"] or
                       any(q in c["course_name"] for c in o["courses"])]
        rows = [[o["name"], _export_rank(o["role"]), o["post"] or "—", str(o["count"]),
                 str(o["days"]), {"grid": _numbered_entries(
                     o["courses"], lambda term: term["course_name"])} if o["courses"] else "—"]
                for o in records]
        title = "كشف الفرق والدورات حسب الضابط"
        columns = [("الضابط", 2.2), ("الرتبة", .7), ("العمل المسند إليه", 2.4),
                   ("عدد الفرق", .8), ("إجمالي الأيام", .9), ("الفرق التي التحق بها", 6.2)]
    else:
        records = summary(data)
        if q:
            records = [c for c in records if q in c["name"] or q in c.get("place", "")
                       or any(q in t["officer_name"] for t in c["terms"])]
        people = {person["id"]: person for person in PeopleRepo(data).raw_all("officers")}
        priority = command_priority_map(data)
        rows = []
        for course in records:
            def seniority(term):
                person = people.get(term.get("officer_id"), {})
                ranked = {**person, "role": term.get("officer_role", person.get("role", ""))}
                return rank_key(ranked, priority)

            ordered = sorted(course["terms"], key=seniority)
            rows.append([course["name"], course.get("place") or "—",
                         {"grid": _numbered_entries(
                             ordered, lambda term: f"{_export_rank(term.get('officer_role'))}/ "
                                                    f"{term.get('officer_name', '')}")}
                         if ordered else "لا توجد التحاقات مسجّلة بعد"])
        title = "كشف الفِرق والدورات حسب الفرقة"
        columns = [("اسم الفرقة", 3.5), ("المكان", 2.5), ("الضباط والالتحاقات", 12.8)]
    content = build_register_docx(title, columns, rows,
                                  subtitle="تاريخ التصدير: " + __import__("datetime").date.today().isoformat(),
                                  font_pt=7 if view == "officer" else 8, compact=True, serial_weight=1.0)
    return send_file(BytesIO(content), as_attachment=True,
                     download_name=register_file_name("سجل الفرق والدورات"),
                     mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@bp.post("/api/courses")
def add_course():
    payload = json_payload()

    def mutate(data):
        course, error = build_course(payload, new_course_id(data))
        if error:
            raise AbortRequest((jsonify({"error": error}), 400))
        if any(c["name"] == course["name"] for c in courses(data)):
            raise AbortRequest((jsonify({"error": "الفرقة موجودة بالفعل."}), 409))
        courses(data).append(course)
        return jsonify(course), 201

    return with_data(mutate, ())


@bp.patch("/api/courses/<course_id>")
def edit_course(course_id):
    payload = json_payload()

    def mutate(data):
        current = by_id(data).get(course_id)
        if not current:
            raise AbortRequest((jsonify({"error": "الفرقة غير موجودة."}), 404))
        merged, error = build_course({**current, **payload}, course_id)
        if error:
            raise AbortRequest((jsonify({"error": error}), 400))
        clash = any(c["name"] == merged["name"] and c["id"] != course_id
                    for c in courses(data))
        if clash:
            raise AbortRequest((jsonify({"error": "توجد فرقة أخرى بالاسم نفسه."}), 409))
        current.pop("kind", None)
        current.update(merged)
        return jsonify(current)

    return with_data(mutate, ())


@bp.delete("/api/courses/<course_id>")
def delete_course(course_id):
    def mutate(data):
        repos = Repos(data)
        used = len(repos.terms.of_course(course_id))
        if used:
            raise AbortRequest((jsonify({
                "error": f"عدد الالتحاقات المسجّلة للفرقة: {used}. احذف الالتحاقات أولًا."}), 409))
        if not repos.courses.remove(course_id):
            raise AbortRequest((jsonify({"error": "الفرقة غير موجودة."}), 404))
        return jsonify({"ok": True})

    return with_data(mutate, ())


# ---------- التحاق ضابط بفرقة ----------

@bp.post("/api/course-terms")
def add_term():
    payload = json_payload()

    def mutate(data):
        # التحقق من الضابط جوّه build_term عشان التعديل يعدّي عليه هو كمان
        term, error = build_term(payload, data, new_term_id(data))
        if error:
            raise AbortRequest((jsonify({"error": error}), 400))
        clash = overlapping(data, term)
        if clash:
            raise AbortRequest((jsonify({
                "error": f"الضابط ملتحق بفرقة أخرى من {clash['start']} إلى {clash['end']}."}), 409))

        closed = retro.closed_days_in(data, term.get("start", ""), term.get("end", ""))
        reason = retro.require_reason(closed)

        terms(data).append(term)
        if closed:
            retro.log_retro(data, "course_term", term["id"], closed, reason, after=dict(term))
        return jsonify(term), 201

    return with_data(mutate, retro.status_scope)


@bp.patch("/api/course-terms/<term_id>")
def edit_term(term_id):
    payload = json_payload()

    def mutate(data):
        current = next((t for t in terms(data) if t["id"] == term_id), None)
        if not current:
            raise AbortRequest((jsonify({"error": "الالتحاق غير موجود."}), 404))
        term, error = build_term({**current, **payload}, data, term_id)
        if error:
            raise AbortRequest((jsonify({"error": error}), 400))
        clash = overlapping(data, term, ignore_id=term_id)
        if clash:
            raise AbortRequest((jsonify({
                "error": f"الضابط ملتحق بفرقة أخرى من {clash['start']} إلى {clash['end']}."}), 409))

        closed = sorted(set(retro.closed_days_in(data, current.get("start", ""), current.get("end", ""))
                            + retro.closed_days_in(data, term.get("start", ""), term.get("end", ""))))
        reason = retro.require_reason(closed)

        before = dict(current)
        current.update(term)
        if closed:
            retro.log_retro(data, "course_term", term_id, closed, reason,
                           before=before, after=dict(current))
        return jsonify(current)

    return with_data(mutate, retro.status_scope)


@bp.delete("/api/course-terms/<term_id>")
def delete_term(term_id):
    def mutate(data):
        found = Repos(data).terms.find(term_id)
        if not found:
            raise AbortRequest((jsonify({"error": "الالتحاق غير موجود."}), 404))

        closed = retro.closed_days_in(data, found.start, found.end)
        reason = retro.require_reason(closed)

        Repos(data).terms.remove(term_id)
        if closed:
            retro.log_retro(data, "course_term", term_id, closed, reason, before=found.as_dict())
        return jsonify({"ok": True})

    return with_data(mutate, retro.status_scope)

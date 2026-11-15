"""فرق الضباط — الفرقة نفسها والتحاق الضباط بيها."""
from flask import Blueprint, jsonify, request, send_file
from io import BytesIO

from .. import retro
from ..courses import (
    build_course, build_term, by_id, by_officer, courses, new_course_id,
    new_term_id, overlapping, summary, terms,
)
from ..repo import Repos
from ..store import AbortRequest, load_data, with_data
from ..utils import json_payload
from ..register_export import build_register_docx, register_file_name

bp = Blueprint("courses", __name__)


@bp.get("/api/courses")
def list_courses():
    """العرضين مع بعض: تجميع بالفرقة وتجميع بالضابط — نفس البيانات
    بمدخلين مختلفين، فنداء واحد يكفي والتبديل بينهم من غير تحميل."""
    data = load_data(())
    return jsonify({"courses": summary(data), "officers": by_officer(data)})


@bp.get("/api/courses/export.docx")
def export_courses():
    data = load_data(())
    view = request.args.get("view", "course")
    q = request.args.get("q", "").strip()
    kind_filter = request.args.get("kind", "")
    if view == "officer":
        records = by_officer(data)
        if q:
            records = [o for o in records if q in o["name"] or
                       any(q in c["course_name"] for c in o["courses"])]
        rows = [[o["name"], o["role"], o["post"] or "—", str(o["count"]),
                 str(o["days"]), "\n".join(c["course_name"] for c in o["courses"]) or "—"]
                for o in records]
        title = "كشف الفرق والدورات حسب الضابط"
        columns = [("الضابط", 1.5), ("الرتبة", 1), ("العمل المسند إليه", 1.6),
                   ("عدد الفرق", .8), ("إجمالي الأيام", 1), ("الفرق التي التحق بها", 2)]
    else:
        records = summary(data)
        if q:
            records = [c for c in records if q in c["name"] or q in c.get("place", "")
                       or any(q in t["officer_name"] for t in c["terms"])]
        if kind_filter == "__none":
            records = [c for c in records if not c.get("kind")]
        elif kind_filter:
            records = [c for c in records if c.get("kind") == kind_filter]
        rows = [[c["name"], c.get("kind") or "بدون تصنيف", c.get("place") or "—",
                 c.get("note") or "—", "\n".join(
                     f"{t['officer_role']} / {t['officer_name']} — {t.get('start','')} – {t.get('end','')}"
                     for t in c["terms"]) or "لا توجد التحاقات مسجّلة بعد"] for c in records]
        title = "كشف الفِرق والدورات حسب الفرقة"
        columns = [("اسم الفرقة", 1.5), ("النوع", 1), ("المكان", 1.2),
                   ("ملاحظات", 1.5), ("الضباط والالتحاقات", 3)]
    content = build_register_docx(title, columns, rows,
                                  subtitle="تاريخ التصدير: " + __import__("datetime").date.today().isoformat())
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

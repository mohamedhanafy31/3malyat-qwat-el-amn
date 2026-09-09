"""فرق الضباط — الفرقة نفسها والتحاق الضباط بيها."""
from flask import Blueprint, jsonify

from ..courses import (
    build_course, build_term, by_id, by_officer, courses, new_course_id,
    new_term_id, overlapping, summary, terms,
)
from ..people import find_person
from ..store import AbortRequest, load_data, with_data
from ..utils import json_payload

bp = Blueprint("courses", __name__)


@bp.get("/api/courses")
def list_courses():
    """العرضين مع بعض: تجميع بالفرقة وتجميع بالضابط — نفس البيانات
    بمدخلين مختلفين، فنداء واحد يكفي والتبديل بينهم من غير تحميل."""
    data = load_data()
    return jsonify({"courses": summary(data), "officers": by_officer(data)})


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

    return with_data(mutate)


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
            raise AbortRequest((jsonify({"error": "فيه فرقة تانية بنفس الاسم."}), 409))
        current.update(merged)
        return jsonify(current)

    return with_data(mutate)


@bp.delete("/api/courses/<course_id>")
def delete_course(course_id):
    def mutate(data):
        used = sum(1 for t in terms(data) if t.get("course_id") == course_id)
        if used:
            raise AbortRequest((jsonify({
                "error": f"الفرقة ليها {used} التحاق مسجّل. امسح الالتحاقات الأول."}), 409))
        before = len(courses(data))
        data["courses"] = [c for c in courses(data) if c["id"] != course_id]
        if len(data["courses"]) == before:
            raise AbortRequest((jsonify({"error": "الفرقة غير موجودة."}), 404))
        return jsonify({"ok": True})

    return with_data(mutate)


# ---------- التحاق ضابط بفرقة ----------

@bp.post("/api/course-terms")
def add_term():
    payload = json_payload()

    def mutate(data):
        officer_id = str(payload.get("officer_id", "")).strip()
        person, category, _ = find_person(data, officer_id)
        if not person or category != "officers":
            raise AbortRequest((jsonify({"error": "برجاء اختيار الضابط."}), 400))

        term, error = build_term(payload, data, new_term_id(data))
        if error:
            raise AbortRequest((jsonify({"error": error}), 400))
        clash = overlapping(data, term)
        if clash:
            raise AbortRequest((jsonify({
                "error": f"الضابط ملتحق بفرقة تانية من {clash['start']} إلى {clash['end']}."}), 409))
        terms(data).append(term)
        return jsonify(term), 201

    return with_data(mutate)


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
                "error": f"الضابط ملتحق بفرقة تانية من {clash['start']} إلى {clash['end']}."}), 409))
        current.update(term)
        return jsonify(current)

    return with_data(mutate)


@bp.delete("/api/course-terms/<term_id>")
def delete_term(term_id):
    def mutate(data):
        before = len(terms(data))
        data["course_terms"] = [t for t in terms(data) if t["id"] != term_id]
        if len(data["course_terms"]) == before:
            raise AbortRequest((jsonify({"error": "الالتحاق غير موجود."}), 404))
        return jsonify({"ok": True})

    return with_data(mutate)

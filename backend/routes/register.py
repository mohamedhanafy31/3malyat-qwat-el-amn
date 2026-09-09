"""دفتر 43 — الشبكة الشهرية وصفحة الضابط."""
from flask import Blueprint, jsonify

from ..people import find_person
from ..register import month_register, officer_register
from ..store import load_data

bp = Blueprint("register", __name__)


@bp.get("/api/register/<int:year>/<int:month>")
def get_month(year, month):
    if not 1 <= month <= 12:
        return jsonify({"error": "شهر غير صحيح."}), 400
    if not 2000 <= year <= 2100:
        return jsonify({"error": "سنة غير صحيحة."}), 400
    return jsonify(month_register(load_data(), year, month))


@bp.get("/api/register/officer/<officer_id>")
def get_officer(officer_id):
    data = load_data()
    person, category, _ = find_person(data, officer_id)
    if not person or category != "officers":
        return jsonify({"error": "الضابط غير موجود."}), 404
    out = officer_register(data, officer_id)
    # الاسم من سجل القوة لو الضابط مالوش أي يوم مسجّل
    out["officer"]["name"] = out["officer"]["name"] or person.get("name", "")
    out["officer"]["role"] = out["officer"]["role"] or person.get("role", "")
    return jsonify(out)

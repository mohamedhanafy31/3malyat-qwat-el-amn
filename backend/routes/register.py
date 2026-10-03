"""دفتر 43 — الشبكة الشهرية وصفحة الضابط."""
import calendar

from flask import Blueprint, jsonify

from ..repo import Repos
from ..register import month_register, officer_register
from ..store import load_data

bp = Blueprint("register", __name__)


@bp.get("/api/register/<int:year>/<int:month>")
def get_month(year, month):
    if not 1 <= month <= 12:
        return jsonify({"error": "شهر غير صحيح."}), 400
    if not 2000 <= year <= 2100:
        return jsonify({"error": "سنة غير صحيحة."}), 400
    first = f"{year:04d}-{month:02d}-01"
    last = f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
    # أيام الشهر المسجّلة فعلًا بس — الباقي «بدون سجل» من غير تحميل
    data = load_data(lambda view: view.index.recorded_between(first, last))
    return jsonify(month_register(data, year, month))


@bp.get("/api/register/officer/<officer_id>")
def get_officer(officer_id):
    # صفحة الضابط بتعرض كل يوم مسجّل في الأرشيف، لكن بتحمّل بس الأيام
    # المذكور فيها الضابط (من الفهرس) — الباقي مالوش فيه تكليف ولا حالة،
    # وقايمة الأيام المسجّلة نفسها بتيجي من الفهرس (`store.recorded_days`).
    data = load_data(lambda view: view.index.person_days(officer_id))
    person, category, _ = Repos(data).people.locate(officer_id)
    if not person or category != "officers":
        return jsonify({"error": "الضابط غير موجود."}), 404
    out = officer_register(data, officer_id)
    # الاسم من سجل القوة لو الضابط مالوش أي يوم مسجّل
    out["officer"]["name"] = out["officer"]["name"] or person.get("name", "")
    out["officer"]["role"] = out["officer"]["role"] or person.get("role", "")
    return jsonify(out)

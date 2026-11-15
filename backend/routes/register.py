"""دفتر 43 — الشبكة الشهرية وصفحة الضابط."""
import calendar
from io import BytesIO

from flask import Blueprint, jsonify, request, send_file

from ..repo import Repos
from ..register import month_register, officer_register
from ..store import load_data
from ..register_export import build_register_docx, register_file_name

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


@bp.get("/api/register/<int:year>/<int:month>/export.docx")
def export_month(year, month):
    if not 1 <= month <= 12 or not 2000 <= year <= 2100:
        return jsonify({"error": "شهر أو سنة غير صحيحة."}), 400
    first = f"{year:04d}-{month:02d}-01"
    last = f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
    data = load_data(lambda view: view.index.recorded_between(first, last))
    result = month_register(data, year, month)
    q = request.args.get("q", "").strip()
    rows = []
    for officer in result["rows"]:
        if q and q not in officer["name"]:
            continue
        tally = officer["tally"]["by_family"]
        rows.append([officer["name"] + "\n" + officer["role"]] +
            [cell["code"] for cell in officer["cells"]] +
            [tally["عمل"], tally["راحة"], tally["إجازة"], tally["خارج"]])
    total_labels = (("القوة", "force"), ("الموجود", "working"), ("راحة", "resting"),
                    ("إجازة", "on_leave"), ("خارج", "away"))
    for label, key in total_labels:
        rows.append([label] + [str(total[key]) if total["recorded"] else "·"
                               for total in result["totals"]] + ["", "", "", ""])
    columns = [("الضابط", 1.8)] + [(str(int(day[8:10])), .55) for day in result["days"]] + [
        ("عمل", .7), ("راحة", .7), ("إجازة", .7), ("خارج", .7)]
    subtitle = f'الفترة: {year:04d}-{month:02d}' + (f' — بحث: «{q}»' if q else "")
    content = build_register_docx("حصر تشغيل الضباط", columns, rows, subtitle=subtitle, orientation="auto")
    return send_file(BytesIO(content), as_attachment=True,
                     download_name=register_file_name("حصر تشغيل الضباط"),
                     mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


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


@bp.get("/api/register/officer/<officer_id>/export.docx")
def export_officer(officer_id):
    data = load_data(lambda view: view.index.person_days(officer_id))
    person, category, _ = Repos(data).people.locate(officer_id)
    if not person or category != "officers":
        return jsonify({"error": "الضابط غير موجود."}), 404
    out = officer_register(data, officer_id)
    out["officer"]["name"] = out["officer"]["name"] or person.get("name", "")
    out["officer"]["role"] = out["officer"]["role"] or person.get("role", "")
    rows = [[cell["day"], cell["code"], cell["label"],
             " + ".join(f'{s["name"]} — {s["shift"]}' for s in cell["services"]) or "—",
             cell["note"] or "—"] for cell in out["cells"]]
    subtitle = f'{out["officer"]["role"]} / {out["officer"]["name"]}'
    content = build_register_docx("دفتر الضابط", [("التاريخ", 1.2), ("الرمز", .6),
        ("الحالة", 1.2), ("الخدمات", 2.3), ("ملاحظة", 1.5)], rows, subtitle=subtitle)
    return send_file(BytesIO(content), as_attachment=True,
                     download_name=register_file_name("دفتر الضابط"),
                     mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

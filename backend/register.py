"""دفتر 43 — سجل موقف كل ضابط يوم بيوم.

الشكل الورقي: صف لكل ضابط، وعمود لكل يوم في الشهر، والخانة رمز الحالة
اللي كان عليها اليوم ده، وتحت الجدول مفتاح الرموز. الدفتر ده بيتستخدم
كإثبات رسمي لتواجد الفرد من عدمه في يوم معيّن، فكل خانة هنا **محسوبة من
تكليفات اليوم نفسها** — مش مدخلة بإيد تانية — وبتقدر تفتحها وتشوف الخدمة
اللي وراها.

الرموز في REGISTER_CODES تحت — مكان واحد لتعديلها كلها.
"""
import calendar
from datetime import date

from .duty import summarise
from .people import officers_on

# (المجموعة، الخانة) -> رمز الدفتر.
# `family` بتحدد الحصر أسفل الجدول: شغل / راحة / خارج القوة.
REGISTER_CODES = {
    ("حراسات", None):      {"code": "ح",  "label": "حراسات",            "family": "عمل"},
    ("خارجية", "صباحية"):  {"code": "ص",  "label": "خدمة صباحية",       "family": "عمل"},
    ("خارجية", "ليلية"):   {"code": "ل",  "label": "خدمة ليلية",        "family": "عمل"},
    ("خارجية", "بحث"):     {"code": "ب",  "label": "تشغيل إدارة البحث", "family": "عمل"},
    ("داخلية", "صباحية"):  {"code": "دص", "label": "داخلية صباحية",     "family": "عمل"},
    ("داخلية", "ليلية"):   {"code": "دل", "label": "داخلية ليلية",      "family": "عمل"},
    ("طبية", "موجود"):     {"code": "ط",  "label": "طبية",              "family": "عمل"},
    ("صافي", None):        {"code": "إ",  "label": "عمل بالإدارة",      "family": "عمل"},
    ("طبية", "راحة"):      {"code": "طر", "label": "طبية — راحة",       "family": "راحة"},
    ("خوارج", "راحة"):     {"code": "ر",  "label": "راحة",              "family": "راحة"},
    ("خوارج", "تقصيرة"):   {"code": "ت",  "label": "تقصيرة",            "family": "عمل"},
    ("خوارج", "طارئة"):    {"code": "أ",  "label": "إجازة طارئة",       "family": "راحة"},
    ("خوارج", "مرضي"):     {"code": "ض",  "label": "مرضي",              "family": "خارج"},
    ("خوارج", "غياب"):     {"code": "غ",  "label": "غياب",              "family": "خارج"},
    ("خوارج", "انتداب"):   {"code": "ن",  "label": "انتداب",            "family": "خارج"},
    ("خوارج", "فرقة"):     {"code": "ف",  "label": "فرقة",              "family": "خارج"},
}
# الضابط مكانش على القوة يومها (انضم بعده أو خرج قبله)
OFF_FORCE = {"code": "—", "label": "مش على القوة", "family": "خارج القوة"}
# اليوم نفسه مالوش يومية مسجّلة أصلًا. لازم يبقى رمز مستقل: الدفتر ده
# بيتستخدم كإثبات تواجد، وخانة فاضية معناها «مفيش سجل» — مش معناها إن
# الضابط كان بيشتغل بالإدارة، ولا إنه كان غايب.
NO_RECORD = {"code": "·", "label": "مفيش يومية مسجّلة", "family": "بدون سجل"}

FAMILIES = ["عمل", "راحة", "خارج"]


def legend():
    """مفتاح الرموز — بيتعرض تحت الدفتر زي الورق."""
    seen, out = set(), []
    for info in REGISTER_CODES.values():
        if info["code"] in seen:
            continue
        seen.add(info["code"])
        out.append(dict(info))
    out.append(dict(OFF_FORCE))
    out.append(dict(NO_RECORD))
    return out


def recorded_days(data, days):
    """الأيام اللي فيها يومية فعلًا — الباقي «بدون سجل» مش «صافي»."""
    assignments = data.get("day_assignments") or {}
    states = data.get("day_officers") or {}
    return {d for d in days if assignments.get(d) or states.get(d)}


def cell_for(row):
    """رمز الدفتر لصف ضابط من يومية اليوم."""
    info = REGISTER_CODES.get((row["group"], row["bucket"]))
    if info is None:
        # خانة جديدة اتضافت في الإجمالي ومالهاش رمز لسه — أول حرف بدل ما تختفي
        label = f'{row["group"]}{" · " + row["bucket"] if row["bucket"] else ""}'
        info = {"code": row["group"][0], "label": label, "family": "عمل"}
    return info


def month_days(year, month):
    last = calendar.monthrange(year, month)[1]
    return [date(year, month, d).isoformat() for d in range(1, last + 1)]


def _cell(row, day):
    info = cell_for(row)
    return {
        "day": day,
        "code": info["code"],
        "label": info["label"],
        "family": info["family"],
        "group": row["group"],
        "bucket": row["bucket"],
        # الخدمة اللي ورا الخانة — دي اللي بتظهر عند الضغط عليها
        "services": [{"name": s["name"], "shift": s["shift"], "kind": s["kind"]}
                     for s in row["services"]],
        "note": row["note"],
        "taqseera": row["taqseera"],
        "leave": row["leave"],
    }


def _tally(cells):
    """حصر: أيام لكل رمز، وأيام لكل عائلة، وعدد الخدمات بالاسم."""
    by_code, by_family, by_service = {}, {f: 0 for f in FAMILIES}, {}
    for cell in cells:
        by_code[cell["code"]] = by_code.get(cell["code"], 0) + 1
        if cell["family"] in by_family:
            by_family[cell["family"]] += 1
        for svc in cell["services"]:
            key = svc["name"]
            by_service[key] = by_service.get(key, 0) + 1
    return {
        "by_code": by_code,
        "by_family": by_family,
        "services": sorted(({"name": n, "count": c} for n, c in by_service.items()),
                            key=lambda x: (-x["count"], x["name"])),
        "days": len(cells),
    }


def _day_rows(data, days):
    """{اليوم: {officer_id: صف}} — نداء واحد لكل يوم بيغطي كل الضباط."""
    out = {}
    for day in days:
        out[day] = {r["id"]: r for r in summarise(data, day)["rows"]}
    return out


def month_register(data, year, month):
    """دفتر الشهر: صف لكل ضابط، عمود لكل يوم."""
    days = month_days(year, month)
    recorded = recorded_days(data, days)
    # الأيام اللي مالهاش يومية بتتحسب برضو: الراحة والفرقة سجلات بمدى
    # تواريخ، فبنعرف موقف الضابط فيها حتى من غير يومية. اللي مانعرفش عنه
    # حاجة (صافي) هو اللي بيفضل «مفيش سجل».
    per_day = _day_rows(data, days)

    # الضباط اللي كانوا على القوة في أي يوم من الشهر، بترتيب الرتبة
    seen, officers = set(), []
    for day in days:
        for officer in officers_on(data, day):
            if officer["id"] in seen:
                continue
            seen.add(officer["id"])
            officers.append(officer)

    def _flat(info, day):
        return {**info, "day": day, "services": [], "note": "",
                "group": None, "bucket": None, "taqseera": False, "leave": None}

    rows = []
    last_recorded = max(recorded) if recorded else None
    for officer in officers:
        cells = []
        for day in days:
            row = per_day[day].get(officer["id"])
            if not row:
                cells.append(_flat(OFF_FORCE, day))
                continue
            # في يوم من غير يومية، «صافي» معناها إننا مانعرفش حاجة عنه —
            # مش إنه كان بالإدارة. أما الراحة والفرقة فسجلات بمدى تواريخ
            # وبتفضل صحيحة سواء اتعملت يومية أو لأ.
            if day not in recorded and row["group"] == "صافي":
                cells.append(_flat(NO_RECORD, day))
                continue
            cells.append(_cell(row, day))
        counted = [c for c in cells if c["family"] in FAMILIES]
        last = per_day.get(last_recorded, {}).get(officer["id"]) or {}
        rows.append({
            "id": officer["id"],
            "name": officer.get("name", ""),
            "role": last.get("role") or officer.get("role", ""),
            "post": last.get("post") or officer.get("post", ""),
            "cells": cells,
            "tally": _tally(counted),
        })

    # إجمالي كل يوم: القوة والموجود والخارج — ده اللي الدفتر بيتسأل عنه
    totals = []
    for i, day in enumerate(days):
        column = [r["cells"][i] for r in rows]
        on_force = [c for c in column if c["family"] in FAMILIES]
        totals.append({
            "day": day,
            "recorded": day in recorded,
            "force": len(on_force),
            "working": sum(1 for c in on_force if c["family"] == "عمل"),
            "resting": sum(1 for c in on_force if c["family"] == "راحة"),
            "away": sum(1 for c in on_force if c["family"] == "خارج"),
        })

    return {"year": year, "month": month, "days": days, "rows": rows,
            "totals": totals, "legend": legend(),
            "recorded_days": sorted(recorded)}


def officer_register(data, officer_id, days=None):
    """صفحة ضابط واحد: كل يوم مسجّل في الأرشيف + الحصر الكامل."""
    if days is None:
        days = sorted(set(data.get("day_assignments") or {})
                      | set(data.get("day_officers") or {}))
    else:
        days = sorted(days)
    per_day = _day_rows(data, days)

    person = None
    cells = []
    for day in days:
        row = per_day[day].get(officer_id)
        if not row:
            continue                      # مكانش على القوة — مالوش سطر في دفتره
        person = row
        cells.append(_cell(row, day))

    months = {}
    for cell in cells:
        key = cell["day"][:7]
        months.setdefault(key, []).append(cell)

    return {
        "officer": {"id": officer_id,
                    "name": (person or {}).get("name", ""),
                    "role": (person or {}).get("role", ""),
                    "post": (person or {}).get("post", ""),
                    "section": (person or {}).get("section", "")},
        "cells": cells,
        "tally": _tally(cells),
        "months": [{"month": m, "tally": _tally(c), "cells": c}
                   for m, c in sorted(months.items())],
        "legend": legend(),
    }

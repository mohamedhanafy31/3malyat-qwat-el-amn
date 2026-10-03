"""إحصائيات تشغيل الضباط — تجميع على مدى أيام، عكس صفحة اليومية اللي
بتعرض يوم واحد بس. بتتابع انتظام وعدالة التشغيل الفعلي (مين بياخد نصيب
أكبر، مين مالوش تشغيل كفاية، الأهداف بتتغطى بقادتها الرسميين ولا لأ)
عكس صفحة الراحات اللي بتتابع الغياب.

كل التجميع هنا بيتم على `data` المحمّلة بالفعل في الذاكرة — مفيش قراءة
ملفات إضافية (المسار بيحمّل الأيام المسجّلة جوّه المدى بس مرة واحدة —
`utils.recorded_range_scope` — زي ما `register.py` بيعمل لشهر كامل).
"""
from collections import defaultdict
from datetime import date

from .board import target_rows_for_day
from .dated import targets_on
from .duty import summarise
from .utils import recorded_between, resolve_recorded_range

# ترتيب بيطابق date.weekday() (الاثنين=0 ... الأحد=6)
WEEKDAY_BY_INDEX = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]


def stats(data, filters):
    """إحصائيات التشغيل للمدى المطلوب. بترجع كل حاجة معروضة فعلًا في
    الصفحة — نفس المبدأ المتبع في `leaves.py::stats()`."""
    date_from, date_to, recorded = resolve_recorded_range(data, filters)
    days = recorded_between(recorded, date_from, date_to)

    by_officer = {}      # id -> {name, role, load: {kind: n}, net_days, total_days,
                          #        morning, night, taqseera}

    def officer_entry(row):
        entry = by_officer.setdefault(row["id"], {
            "name": row["name"], "role": row["role"],
            "load": defaultdict(int), "net_days": 0, "total_days": 0,
            "morning": 0, "night": 0, "taqseera": 0,
        })
        return entry

    by_weekday = {w: {"services": 0, "net": 0, "days": 0} for w in WEEKDAY_BY_INDEX}
    target_gap = {}

    for day in days:
        result = summarise(data, day)
        rows = result["rows"]
        weekday = WEEKDAY_BY_INDEX[date.fromisoformat(day).weekday()]
        wd = by_weekday[weekday]
        wd["days"] += 1

        for row in rows:
            entry = officer_entry(row)
            entry["total_days"] += 1
            if row["group"] == "صافي":
                entry["net_days"] += 1
                wd["net"] += 1
            if row["taqseera"]:
                entry["taqseera"] += 1
            for svc in row["services"]:
                entry["load"][svc["kind"]] += 1
                wd["services"] += 1
                if svc["shift"] == "صباحية":
                    entry["morning"] += 1
                elif svc["shift"] == "ليلية":
                    entry["night"] += 1

        # القائد المعيّن وعنده تقصيرة النهاردة مايتحسبش «القائد غطّى الهدف»
        taqseera_ids = {r["id"] for r in rows if r["taqseera"]}
        for row in target_rows_for_day(data, day):
            if row["name"] not in targets_on(data, day):
                continue
            target_gap.setdefault(row["name"], {
                "total_days": 0, "commander_known_days": 0,
                "commander_days": 0, "other_days": 0})
            if not row["officers"]:
                continue
            gap = target_gap[row["name"]]
            gap["total_days"] += 1
            assigned_ids = {o["id"] for o in row["officers"]}
            commander_ids = {c["id"] for c in row["commander"]}
            effective_commanders = (assigned_ids & commander_ids) - taqseera_ids
            if commander_ids:
                gap["commander_known_days"] += 1
            if effective_commanders:
                gap["commander_days"] += 1
            # يوم «غير القائد» = فيه ضابط معيّن فعلًا (مش القائد ومالوش
            # تقصيرة). قائد بتقصيرة من غير بديل بيدخل في الفجوة بس مش هنا.
            if assigned_ids - effective_commanders - taqseera_ids:
                gap["other_days"] += 1

    by_officer_load = []
    net_rate = []
    shift_balance = []
    taqseera_count = []
    for oid, e in by_officer.items():
        total_services = sum(e["load"].values())
        by_officer_load.append({"id": oid, "name": e["name"], "role": e["role"],
                                 "total": total_services, "by_kind": dict(e["load"])})
        net_rate.append({"id": oid, "name": e["name"], "role": e["role"],
                          "net_days": e["net_days"], "total_days": e["total_days"],
                          "rate": round(e["net_days"] / e["total_days"] * 100, 1) if e["total_days"] else 0})
        shift_balance.append({"id": oid, "name": e["name"], "role": e["role"],
                               "morning": e["morning"], "night": e["night"]})
        if e["taqseera"]:
            taqseera_count.append({"id": oid, "name": e["name"], "role": e["role"],
                                    "count": e["taqseera"]})

    by_officer_load.sort(key=lambda x: x["total"], reverse=True)
    net_rate.sort(key=lambda x: x["rate"], reverse=True)
    shift_balance.sort(key=lambda x: abs(x["morning"] - x["night"]), reverse=True)
    taqseera_count.sort(key=lambda x: x["count"], reverse=True)

    target_gap_list = []
    for name, g in target_gap.items():
        gap_days = g["total_days"] - g["commander_days"]
        # مفيش قائد رسمي معروف في أي يوم = مفيش حد نقارن بيه، فالنسبة None مش ١٠٠٪
        gap_rate = (round(gap_days / g["total_days"] * 100, 1)
                    if g["commander_known_days"] else None)
        target_gap_list.append({
            "name": name,
            "commander_days": g["commander_days"],
            "other_days": g["other_days"],
            "total_days": g["total_days"],
            "gap_days": gap_days,
            "gap_rate": gap_rate,
            "commander_known_days": g["commander_known_days"],
            # أسماء قديمة محفوظة للتوافق — نفس القيم الجديدة
            "assigned_days": g["total_days"],
            "mismatch_days": gap_days,
            "mismatch_rate": gap_rate,
        })

    return {
        "date_from": date_from, "date_to": date_to,
        "days_count": len(days),
        "by_officer_load": by_officer_load,
        "target_gap": target_gap_list,
        "net_rate": net_rate,
        "shift_balance": shift_balance,
        "taqseera_count": taqseera_count,
        "by_weekday": [{"weekday": w, **v} for w, v in by_weekday.items()],
        "meta_options": {"earliest": recorded[0] if recorded else None,
                         "latest": recorded[-1] if recorded else None},
    }

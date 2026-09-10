"""نقاط الراحات والإجازات."""
from flask import Blueprint, jsonify

from ..leaves import build_leave, overlapping
from ..store import AbortRequest, next_id, with_data
from ..utils import json_payload

bp = Blueprint("leaves", __name__)


@bp.post("/api/leaves")
def add_leave():
    payload = json_payload()

    def mutate(data):
        leave_id = next_id(data["leaves"], "LV")
        leave, err = build_leave(payload, data, leave_id)
        if err:
            raise AbortRequest((jsonify({"error": err}), 400))
        clash = overlapping(data, leave)
        if clash:
            raise AbortRequest((jsonify({"error": f"يوجد راحة متداخلة لنفس الشخص ({clash['start']} → {clash['end']})."}), 409))

        data["leaves"].append(leave)
        data["leaves"].sort(key=lambda l: (l["start"], l.get("name", "")))
        return jsonify(leave), 201

    return with_data(mutate)


@bp.patch("/api/leaves/<leave_id>")
def edit_leave(leave_id):
    payload = json_payload()

    def mutate(data):
        current = next((l for l in data["leaves"] if l.get("id") == leave_id), None)
        if not current:
            raise AbortRequest((jsonify({"error": "سجل الراحة غير موجود."}), 404))

        merged = {**current, **payload}
        leave, err = build_leave(merged, data, leave_id)
        if err:
            raise AbortRequest((jsonify({"error": err}), 400))
        clash = overlapping(data, leave, ignore_id=leave_id)
        if clash:
            raise AbortRequest((jsonify({"error": f"يوجد راحة متداخلة لنفس الشخص ({clash['start']} → {clash['end']})."}), 409))

        data["leaves"] = [leave if l.get("id") == leave_id else l for l in data["leaves"]]
        data["leaves"].sort(key=lambda l: (l["start"], l.get("name", "")))
        return jsonify(leave)

    return with_data(mutate)


@bp.delete("/api/leaves/<leave_id>")
def delete_leave(leave_id):
    def mutate(data):
        before = len(data["leaves"])
        data["leaves"] = [l for l in data["leaves"] if l.get("id") != leave_id]
        if len(data["leaves"]) == before:
            raise AbortRequest((jsonify({"error": "سجل الراحة غير موجود."}), 404))
        return jsonify({"ok": True})

    return with_data(mutate)


@bp.get("/api/leaves/stats")
def leaves_stats():
    """إحصائيات شاملة للراحات — كل البيانات محسوبة على الخادم جاهزة للرسم."""
    from datetime import date as _date, timedelta
    from ..store import load_data
    from collections import defaultdict

    data = load_data()
    leaves = data.get("leaves", [])
    today = _date.today()

    # ── 1. توزيع الأنواع ──
    by_type: dict[str, int] = defaultdict(int)
    for lv in leaves:
        by_type[lv.get("type", "غير محدد")] += 1

    # ── 2. توزيع شهري (عدد الراحات التي بدأت في كل شهر) ──
    by_month: dict[str, int] = defaultdict(int)
    for lv in leaves:
        m = (lv.get("start") or "")[:7]
        if m:
            by_month[m] += 1

    # ── 3. مدة الراحة (توزيع عدد الأيام) ──
    duration_buckets = {"1 يوم": 0, "2-3 أيام": 0, "4-7 أيام": 0, "أكثر من 7": 0}
    total_days = 0
    for lv in leaves:
        try:
            s = _date.fromisoformat(lv["start"])
            e = _date.fromisoformat(lv["end"])
            n = (e - s).days + 1
            total_days += n
        except Exception:
            n = 0
        if n == 1:
            duration_buckets["1 يوم"] += 1
        elif n <= 3:
            duration_buckets["2-3 أيام"] += 1
        elif n <= 7:
            duration_buckets["4-7 أيام"] += 1
        elif n > 7:
            duration_buckets["أكثر من 7"] += 1

    # ── 4. توزيع الأيام (من الأسبوع الذي تبدأ فيه الراحة) ──
    day_names = ["الأحد", "الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت"]
    by_weekday: dict[str, int] = defaultdict(int)
    for lv in leaves:
        try:
            s = _date.fromisoformat(lv["start"])
            by_weekday[day_names[s.weekday() % 7]] += 1  # Python: Mon=0, Sun=6
        except Exception:
            pass
    # Python isoweekday: Mon=1 .. Sun=7, we want Arabic Sun-first
    # recalc using weekday(): Mon=0..Sun=6
    # Sunday in Python = weekday 6 → index 0 in our day_names list above:
    # Mon(0)→الاثنين, Tue(1)→الثلاثاء ... Sun(6)→الأحد
    # already correct above

    # ── 5. أكثر الضباط راحات (Top 10) ──
    by_officer: dict[str, dict] = {}
    for lv in leaves:
        pid = lv.get("person_id", "")
        name = lv.get("name", pid)
        if pid not in by_officer:
            by_officer[pid] = {"name": name, "count": 0, "days": 0}
        by_officer[pid]["count"] += 1
        try:
            s = _date.fromisoformat(lv["start"])
            e = _date.fromisoformat(lv["end"])
            by_officer[pid]["days"] += (e - s).days + 1
        except Exception:
            pass
    top_officers = sorted(by_officer.values(), key=lambda x: x["count"], reverse=True)[:10]

    # ── 6. الحالة الراهنة (جارية / قادمة / منتهية) ──
    today_str = today.isoformat()
    status_counts = {"جارية": 0, "قادمة": 0, "منتهية": 0}
    for lv in leaves:
        s, e = lv.get("start", ""), lv.get("end", "")
        if s <= today_str <= e:
            status_counts["جارية"] += 1
        elif s > today_str:
            status_counts["قادمة"] += 1
        else:
            status_counts["منتهية"] += 1

    # ── 7. الراحات المتراكمة تراكمياً بالشهر (cumulative) ──
    sorted_months = sorted(by_month.keys())
    cumulative, running = [], 0
    for m in sorted_months:
        running += by_month[m]
        cumulative.append({"month": m, "total": running})

    avg_duration = round(total_days / len(leaves), 1) if leaves else 0

    return jsonify({
        "summary": {
            "total": len(leaves),
            "total_days": total_days,
            "avg_duration": avg_duration,
            "current": status_counts["جارية"],
            "upcoming": status_counts["قادمة"],
        },
        "by_type": dict(by_type),
        "by_month": dict(sorted(by_month.items())),
        "duration_buckets": duration_buckets,
        "by_weekday": dict(by_weekday),
        "top_officers": top_officers,
        "status_counts": status_counts,
        "cumulative": cumulative,
    })


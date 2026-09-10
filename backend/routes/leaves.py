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
    """إحصائيات شاملة للراحات — قابلة للتصفية بحسب الفلاتر (الشهور، نوع الراحة، الحالة، الفئة)."""
    from datetime import date as _date, timedelta
    from collections import defaultdict
    from flask import request
    from ..store import load_data

    data = load_data()
    all_leaves = data.get("leaves", [])
    today = _date.today()
    today_str = today.isoformat()

    # مجموعات الهويات للفئات (ضباط vs أفراد)
    officer_ids = {p["id"] if isinstance(p, dict) else str(p) for p in data.get("officers", []) if p}
    personnel_ids = {p["id"] if isinstance(p, dict) else str(p) for p in data.get("personnel", []) if p}

    # قراءة الفلاتر من ترويسة الطلب (Query Parameters)
    month_from = request.args.get("month_from", "").strip()
    month_to = request.args.get("month_to", "").strip()
    leave_type = request.args.get("type", "").strip()
    status_filter = request.args.get("status", "").strip()
    category_filter = request.args.get("category", "").strip()

    # تصفية الراحات
    leaves = []
    for lv in all_leaves:
        m = (lv.get("start") or "")[:7]
        # فلتر الفترة الزمنية (من شهر / إلى شهر)
        if month_from and m and m < month_from:
            continue
        if month_to and m and m > month_to:
            continue

        # فلتر نوع الراحة
        if leave_type and leave_type != "الكل" and lv.get("type") != leave_type:
            continue

        # فلتر الفئة (ضباط vs أفراد)
        pid = lv.get("person_id", "")
        if category_filter in ("officers", "ضباط"):
            if pid not in officer_ids and not pid.startswith("OFF_"):
                continue
        elif category_filter in ("personnel", "أفراد"):
            if pid not in personnel_ids and not (pid.startswith("SOL_") or pid.startswith("PER_")):
                continue

        # فلتر الحالة (جارية / قادمة / منتهية)
        s, e = lv.get("start", ""), lv.get("end", "")
        st = "جارية" if s <= today_str <= e else ("قادمة" if s > today_str else "منتهية")
        if status_filter and status_filter != "الكل" and st != status_filter:
            continue

        leaves.append(lv)

    # ── 1. توزيع الأنواع ──
    by_type: dict[str, int] = defaultdict(int)
    for lv in leaves:
        by_type[lv.get("type", "غير محدد")] += 1

    # ── 2. توزيع شهري ──
    by_month: dict[str, int] = defaultdict(int)
    for lv in leaves:
        m = (lv.get("start") or "")[:7]
        if m:
            by_month[m] += 1

    # ── 3. مدة الراحة ──
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

    # ── 4. توزيع الأيام من الأسبوع ──
    day_names = ["الأحد", "الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت"]
    by_weekday: dict[str, int] = defaultdict(int)
    for lv in leaves:
        try:
            s = _date.fromisoformat(lv["start"])
            by_weekday[day_names[s.weekday() % 7]] += 1
        except Exception:
            pass

    # ── 5. أكثر الأشخاص راحات (Top 10) ──
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
    status_counts = {"جارية": 0, "قادمة": 0, "منتهية": 0}
    for lv in leaves:
        s, e = lv.get("start", ""), lv.get("end", "")
        if s <= today_str <= e:
            status_counts["جارية"] += 1
        elif s > today_str:
            status_counts["قادمة"] += 1
        else:
            status_counts["منتهية"] += 1

    # ── 7. الراحات المتراكمة ──
    sorted_months = sorted(by_month.keys())
    cumulative, running = [], 0
    for m in sorted_months:
        running += by_month[m]
        cumulative.append({"month": m, "total": running})

    avg_duration = round(total_days / len(leaves), 1) if leaves else 0

    # القائمة الكاملة للشهور المتاحة في النظام ككل لاستخدامها في خيارات المجموعات
    all_months = sorted(list({(lv.get("start") or "")[:7] for lv in all_leaves if (lv.get("start") or "")[:7]}))
    all_types = sorted(list({lv.get("type", "") for lv in all_leaves if lv.get("type")}))

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
        "meta_options": {
            "months": all_months,
            "types": all_types,
        }
    })


"""القادم والمعلّق — نظرة سريعة على اللي محتاج انتباه قريب، بلوك واحد في
الرئيسية بدل ما المشغّل يدوّر في كذا صفحة (راحات، فرق، اليومية التفصيلية).

كل حاجة هنا محسوبة من بيانات موجودة أصلًا — مفيش تخزين جديد ولا حالة
منفصلة، زي أي عرض تاني في السيستم.
"""
from datetime import timedelta

from .checks import day_warnings
from .duty import summarise
from .repo import PeopleRepo

# المدى اللي "قريب" بيتحسب عليه — ٣ أيام كفاية لمتابعة عملية من غير ما
# البلوك يمتلئ بحاجات لسه بعيدة
HORIZON_DAYS = 3


def leaves_ending_soon(data, today, horizon=HORIZON_DAYS):
    """راحات هترجع خلال المدى — مين هيرجع قريب عشان يتخطط تشغيله."""
    today_iso = today.isoformat()
    end_of_window = (today + timedelta(days=horizon)).isoformat()
    out = [lv for lv in data.get("leaves", [])
           if today_iso <= lv.get("end", "") <= end_of_window]
    return sorted(out, key=lambda lv: lv["end"])


def courses_starting_soon(data, today, horizon=HORIZON_DAYS):
    """فرق هتبدأ خلال المدى."""
    today_iso = today.isoformat()
    end_of_window = (today + timedelta(days=horizon)).isoformat()
    people = {p["id"]: p for p in PeopleRepo(data).raw_all("officers")}
    course_names = {c["id"]: c.get("name", "") for c in data.get("courses", [])}

    out = []
    for term in data.get("course_terms", []):
        start = term.get("start", "")
        if today_iso <= start <= end_of_window:
            out.append({
                "term_id": term["id"], "officer_id": term.get("officer_id"),
                "officer_name": people.get(term.get("officer_id"), {}).get("name", ""),
                "course_name": course_names.get(term.get("course_id"), ""),
                "start": start, "end": term.get("end", ""),
            })
    return sorted(out, key=lambda t: t["start"])


def tomorrow_vacant(data, today):
    """خدمات بكرة اللي لسه من غير أي قوام — تذكير قبل ما اليوم يفوت."""
    tomorrow = (today + timedelta(days=1)).isoformat()
    rows = summarise(data, tomorrow)["rows"]
    warnings = day_warnings(data, tomorrow, rows)
    return [w for w in warnings if w["kind"] == "شاغرة"]


def build(data, today):
    return {
        "leaves_ending_soon": leaves_ending_soon(data, today),
        "courses_starting_soon": courses_starting_soon(data, today),
        "tomorrow_vacant": tomorrow_vacant(data, today),
    }

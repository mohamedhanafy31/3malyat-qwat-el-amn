"""سجل خدمات الضابط — List بترتيب زمني لكل يوم كان الضابط فيه على القوة
في مدى تاريخ مختار، مش شبكة رموز مختصرة زي «دفتر الضابط». صف لكل يوم:
الخدمات اللي اتحطت عليه، أو حالته (راحة/تقصيرة/انتداب/غياب/مرضي/فرقة/صافي).

بيستخدم نفس `summarise()` اللي اليومية والإحصائيات بتستخدمه — مفيش حساب
تاني، فمستحيل يختلف عن أي صفحة تانية بتعرض نفس اليوم.
"""
from datetime import date

from .duty import summarise
from .people import find_person
from .utils import days_between, resolve_recorded_range

WEEKDAY_BY_INDEX = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]


def build(data, officer_id, filters):
    """بترجع None لو الضابط مش موجود. وإلا سجل الخدمات كامل للمدى المطلوب."""
    person, category, _ = find_person(data, officer_id)
    if not person or category != "officers":
        return None

    date_from, date_to, recorded = resolve_recorded_range(data, filters)
    days = [d for d in days_between(date.fromisoformat(date_from), date.fromisoformat(date_to))
            if d in recorded]

    rows = []
    for day in days:
        row = next((r for r in summarise(data, day)["rows"] if r["id"] == officer_id), None)
        # الضابط ممكن ميكونش على القوة في جزء من المدى (اتعيّن بعد بدايته
        # أو خرج قبل نهايته) — يوم زي ده بيتسيب من غير صف بدل ما يظهر
        # «صافي» غلط، مطابقة لسلوك officers_on في باقي السيستم.
        if not row:
            continue
        rows.append({
            "date": day,
            "weekday": WEEKDAY_BY_INDEX[date.fromisoformat(day).weekday()],
            "services": row["services"],
            "group": row["group"], "bucket": row["bucket"],
            "taqseera": row["taqseera"], "note": row["note"],
            "leave": row["leave"], "status": row["status"],
        })

    return {
        "officer": {"id": person["id"], "name": person.get("name", ""), "role": person.get("role", "")},
        "date_from": date_from, "date_to": date_to,
        "rows": rows,
        "meta_options": {"earliest": recorded[0] if recorded else None,
                         "latest": recorded[-1] if recorded else None},
    }

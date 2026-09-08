"""حالة الراحة/التقصيرة لكل ضابط — كانت متحسبة في الفرونت إند بالجافاسكريبت،
واتنقلت هنا عشان:

- الصفحات ما تحتاجش تحمّل كل سجلات الراحات (50 كيلو) عشان تعرض عمود
  «حالة اليوم» — بتوصلها الحالة محسوبة جاهزة.
- منطق المدد وأيام التنبيه أصلًا معرّف في backend/constants.py، فمكانه
  الطبيعي هنا مش متكرر في مكانين.
"""
from datetime import date, timedelta

from .constants import TAQSEERA_NOTICE_DAYS, WEEKDAYS
from .leaves import leave_on

# WEEKDAYS بيبدأ بالسبت؛ date.weekday() بيبدأ بالاثنين (0=اثنين .. 6=أحد)
_WEEKDAY_INDEX = {name: i for i, name in enumerate(WEEKDAYS)}
_TO_PY_WEEKDAY = [5, 6, 0, 1, 2, 3, 4]      # السبت=5, الأحد=6, الاثنين=0 ...


def next_weekday(name, after):
    """أول ظهور ليوم الأسبوع ده بعد التاريخ المُعطى (مش نفس اليوم)."""
    idx = _WEEKDAY_INDEX.get(name)
    if idx is None:
        return None
    target = _TO_PY_WEEKDAY[idx]
    diff = (target - after.weekday()) % 7 or 7
    return after + timedelta(days=diff)


def next_rest_start(data, officer, today):
    """أقرب راحة جاية: من السجلات المسجّلة أو من يوم الراحة الأسبوعية الثابت."""
    today_iso = today.isoformat()
    upcoming = [
        {"start": lv["start"], "type": lv["type"], "weekly": False}
        for lv in data["leaves"]
        if lv.get("person_id") == officer["id"] and lv["start"] > today_iso
    ]
    if officer.get("rest_system") == "أسبوعية" and officer.get("rest_day"):
        weekly = next_weekday(officer["rest_day"], today)
        if weekly:
            upcoming.append({"start": weekly.isoformat(), "type": "أسبوعية", "weekly": True})
    if not upcoming:
        return None
    return min(upcoming, key=lambda x: x["start"])


def officer_status(data, officer, today):
    """حالة الضابط النهاردة: في راحة / تقصيرة / راحة قادمة / بالعمل.

    التقصيرة هي اليوم اللي قبل بداية الراحة، والتنبيه بيبدأ قبلها بيوم
    (TAQSEERA_NOTICE_DAYS).
    """
    today_iso = today.isoformat()
    current = leave_on(data, officer["id"], today_iso)
    if current:
        return {"state": "resting", "leave": {"type": current["type"], "end": current["end"],
                                              "return_date": current["return_date"]}}

    nxt = next_rest_start(data, officer, today)
    if not nxt:
        return {"state": "working"}

    rest_start = date.fromisoformat(nxt["start"])
    taqseera_day = rest_start - timedelta(days=1)
    if taqseera_day < today:
        return {"state": "upcoming", "rest_start": nxt["start"], "type": nxt["type"]}

    due = taqseera_day <= today + timedelta(days=TAQSEERA_NOTICE_DAYS)
    return {
        "state": "taqseera" if due else "upcoming",
        "taqseera_date": taqseera_day.isoformat(),
        "rest_start": nxt["start"],
        "type": nxt["type"],
        "weekly": nxt["weekly"],
    }


def with_status(data, officers, today):
    """نسخة من قايمة الضباط، كل واحد معاه حالته محسوبة."""
    return [{**o, "status_today": officer_status(data, o, today)} for o in officers]


def taqseera_alerts(data, today):
    """الضباط المستحقين تنبيه تقصيرة النهاردة، مرتبين بتاريخ التقصيرة."""
    out = []
    for o in data["officers"]["active"]:
        st = officer_status(data, o, today)
        if st["state"] == "taqseera":
            out.append({"id": o["id"], "name": o.get("name", ""), "role": o.get("role", ""),
                        **{k: st[k] for k in ("taqseera_date", "rest_start", "type") if k in st}})
    out.sort(key=lambda x: x["taqseera_date"])
    return out

#!/usr/bin/env python3
"""يستخرج فرق الضباط من نصوص التشغيل في الأرشيف.

الفرقة كانت مكتوبة جوّه نص التشغيل بالكامل — الاسم والمكان والمدة:

    «فرقة الحراسات المشددة بمدرسة الدفاع الشعبي والعسكري من 5/9 حتى 17/9»
    «فرقة قادة أهداف حيوية من يوم 15/8 حتي 27/8»
    «فرقة القيادات الأولى»

فالبيانات موجودة، بس كنص حر مالوش بنية: مش ممكن تعرف مين خد أنهي فرقة،
ولا الفرقة دي بتتاخد كام مرة، ولا الضابط راجع إمتى. والأهم إن الحالة
كانت بتظهر في الخوارج بس في الأيام اللي حد كتبها فيها بإيده.

السكربت ده بيفكّها لـ:
  courses       الفرقة نفسها (اسم + مكان)
  course_terms  التحاق الضابط بيها بمدى تواريخ

المدة بتتاخد من النص لو مكتوبة فيه، وإلا بتتحسب من أول وآخر يوم ظهرت فيه
في الأرشيف. الفرق اللي مدتها مكتوبة بتغطي كمان أيام لسه ماتعملّهاش يومية
— «حتى 17/9» والأرشيف واقف عند 9/9.

    python3 003_seed_courses.py            # عرض بس
    python3 003_seed_courses.py --write
"""
import re
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.text import norm            # noqa: E402
from common import AlreadyDone, run      # noqa: E402

YEAR = 2026

# «من 5/9 حتى 17/9» أو «من يوم 15/8 حتي 27/8»
_SPAN = re.compile(r'من\s*(?:يوم\s*)?(\d{1,2})\s*/\s*(\d{1,2})\s*'
                   r'(?:حتى|حتي|الى|إلى|ل)\s*(\d{1,2})\s*/\s*(\d{1,2})')
# «بمعهد تدريب ضباط الشرطة» / «بالمعهد القومى...» / «بمدرسة الدفاع...»
_PLACE = re.compile(r'\bب(معهد|المعهد|مدرسة|المدرسة|كلية|الكلية)\s+(.+)$')
_LEAD = re.compile(r'^(?:راحة\s+)?فرقة\b\s*')
# نص مالوش اسم فرقة فعلي — «فرقة» أو «راحة فرقة» لوحدها
UNNAMED = "فرقة"


def parse_note(note):
    """-> (اسم الفرقة، المكان، (من، إلى) أو None)"""
    text = re.sub(r'\s+', ' ', (note or "").strip())

    span = None
    m = _SPAN.search(text)
    if m:
        d1, m1, d2, m2 = (int(x) for x in m.groups())
        try:
            span = (date(YEAR, m1, d1).isoformat(), date(YEAR, m2, d2).isoformat())
        except ValueError:
            span = None
        text = text[:m.start()].strip()

    place = ""
    mp = _PLACE.search(text)
    if mp:
        place = f"{mp.group(1)} {mp.group(2)}".strip()
        text = text[:mp.start()].strip()

    # «راحة فرقة كذا» -> «فرقة كذا»؛ و«فرقة» لوحدها تفضل بلا اسم
    body = _LEAD.sub("", text).strip(" -–—")
    name = f"فرقة {body}".strip() if body else UNNAMED
    return re.sub(r'\s+', ' ', name), place, span


def merge_spells(spells):
    """يضم فترات نفس الضابط المتلاصقة في التحاق واحد.

    الأرشيف بيكتب نفس الفرقة بصور مختلفة في أيام متتالية — «فرقة» لوحدها
    في يوم و«فرقة القيادات الأولى» في اللي بعده. لو سِبناهم منفصلين
    يبقى عندنا التحاقين متداخلين لنفس الضابط، وده اللي الـAPI نفسه
    بيرفضه. الاسم الأوضح (الأطول) هو اللي بيغلب.
    """
    spells = sorted(spells, key=lambda s: s["start"])
    out = []
    for spell in spells:
        prev = out[-1] if out else None
        touching = prev and spell["start"] <= _next_day(prev["end"])
        if not touching:
            out.append(dict(spell))
            continue
        prev["end"] = max(prev["end"], spell["end"])
        prev["days"] += spell["days"]
        prev["notes"] |= spell["notes"]
        if len(spell["name"]) > len(prev["name"]):
            prev["name"], prev["place"] = spell["name"], spell["place"] or prev["place"]
        prev["place"] = prev["place"] or spell["place"]
    return out


def _next_day(day):
    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()


def migrate(data):
    if data.get("courses"):
        raise AlreadyDone(
            f"فيه {len(data['courses'])} فرقة مسجّلة بالفعل — مفيش حاجة تتعمل.")
    day_officers = data.get("day_officers") or {}
    officers = {o["id"]: o for b in ("active", "archive") for o in data["officers"][b]}

    # (الضابط، صورة الاسم المطبّعة) -> {الأيام، النصوص، المدة المكتوبة}
    groups = defaultdict(lambda: {"days": [], "notes": set(), "span": None,
                                  "name": "", "place": ""})
    for day, states in day_officers.items():
        for officer_id, state in states.items():
            note = state.get("note") or ""
            if state.get("status") != "فرقة" and "فرق" not in note:
                continue
            name, place, span = parse_note(note)
            group = groups[(officer_id, norm(name))]
            group["days"].append(day)
            group["notes"].add(note)
            group["name"] = group["name"] or name
            group["place"] = group["place"] or place
            group["span"] = group["span"] or span

    # فترة كل مجموعة = المدى المكتوب في النص، وإلا أول وآخر يوم ظهرت فيه
    by_officer = defaultdict(list)
    for (officer_id, _key), group in groups.items():
        days = sorted(group["days"])
        start, end = group["span"] or (days[0], days[-1])
        by_officer[officer_id].append({
            "start": min(start, days[0]), "end": max(end, days[-1]),
            "days": len(days), "notes": set(group["notes"]),
            "name": group["name"], "place": group["place"],
        })

    # فرق مختلفة بنفس الاسم = فرقة واحدة في الكتالوج
    courses, course_of = [], {}

    def course_id_for(name, place):
        key = norm(name)
        if key in course_of:
            course = courses[course_of[key]]
            course["place"] = course["place"] or place
            return course["id"]
        course_of[key] = len(courses)
        courses.append({"id": f"CRS-{len(courses) + 1:03d}", "name": name,
                        "place": place, "kind": "", "note": ""})
        return courses[-1]["id"]

    terms, report_rows = [], []
    for officer_id, spells in sorted(by_officer.items()):
        for spell in merge_spells(spells):
            terms.append({
                "id": f"CT-{len(terms) + 1:04d}",
                "course_id": course_id_for(spell["name"], spell["place"]),
                "officer_id": officer_id,
                "start": spell["start"], "end": spell["end"],
                "note": "",
                "source": sorted(spell["notes"], key=len)[-1],
            })
            report_rows.append(
                (spell["start"],
                 f'{officers.get(officer_id, {}).get("name", officer_id)[:26]:28}'
                 f' {spell["start"]} .. {spell["end"]}  ({spell["days"]} يوم مسجّل)'
                 f'  {spell["name"][:36]}'))
    report_rows = [r for _, r in sorted(report_rows)]

    data["courses"] = courses
    data["course_terms"] = terms

    report = [f"فرق: {len(courses)}", f"التحاقات: {len(terms)}", ""]
    report += [f'  {c["id"]}  {c["name"]}' + (f'  —  {c["place"]}' if c["place"] else "")
               for c in courses]
    report += ["", "الالتحاقات:"] + [f"  {r}" for r in report_rows]

    covered = sum((date.fromisoformat(t["end"]) - date.fromisoformat(t["start"])).days + 1
                  for t in terms)
    recorded = sum(len(g["days"]) for g in groups.values())
    report += ["", f"أيام كانت مكتوبة في التشغيل: {recorded}",
               f"أيام هتتغطّى بالالتحاقات:      {covered}",
               "(الفرق = أيام المدة المكتوبة اللي مكانش لها يومية أو مكانش متكتب فيها «فرقة»)"]
    return report


run(from_schema=3, to_schema=3, migrate=migrate,
    title="استخراج فرق الضباط من نصوص التشغيل")

"""فرق الضباط — الدورات اللي الضابط بياخدها.

الفرقة حاجتين مربوطين ببعض:

  **الفرقة نفسها** (`courses`) — اسمها ومكانها ونوعها. دي بتتكرر: نفس
  «فرقة الحراسات المشددة» بتتاخد كذا مرة على مدار السنة بضباط مختلفين.

  **التحاق الضابط بيها** (`course_terms`) — ضابط + فرقة + من تاريخ لتاريخ.
  ده اللي بيخلي الضابط يظهر في خانة «فرقة» في الخوارج طول مدتها من غير ما
  حد يكتبها في تشغيله كل يوم.

قبل كده الفرقة كانت مجرد كلمة في نص التشغيل: بتوصل لخانة الخوارج لو حد
كتبها بإيده في اليوم ده بالظبط، والمدة والمكان والاسم بيضيعوا. دلوقتي
الالتحاق سجل بمدى تواريخ — زي الراحة بالظبط — فبيغطي كل أيامه لوحده،
وبيعرف كمان الأيام اللي لسه ماتعملّهاش يومية.
"""
from .store import next_id
from .utils import parse_date

# نوع الفرقة زي ما بتتكتب في التشغيل
COURSE_KINDS = ["تأهيلية", "تخصصية", "قادة", "تدريبية", "أخرى"]


def courses(data):
    return data.setdefault("courses", [])


def terms(data):
    return data.setdefault("course_terms", [])


def by_id(data):
    return {c["id"]: c for c in courses(data)}


def terms_of(data, officer_id):
    """كل التحاقات ضابط، الأحدث الأول."""
    return sorted((t for t in terms(data) if t.get("officer_id") == officer_id),
                  key=lambda t: t.get("start", ""), reverse=True)


def term_on(data, officer_id, day):
    """التحاق الضابط بفرقة في اليوم ده — أو None.

    نفس منطق `leave_on`: مدى تواريخ بيغطي اليوم، فالحالة بتتحسب لوحدها
    بدل ما تتكتب يوم بيوم.
    """
    for term in terms(data):
        if term.get("officer_id") != officer_id:
            continue
        start = term.get("start", "")
        end = term.get("end", "")
        if start and end and start <= day <= end:
            return term
    return None


def overlapping(data, term, ignore_id=None):
    """التحاق تاني لنفس الضابط بيتقاطع مع المدى ده."""
    s1, e1 = term.get("start", ""), term.get("end", "")
    if not s1 or not e1:
        return None
    for other in terms(data):
        if other.get("id") == ignore_id or other.get("officer_id") != term["officer_id"]:
            continue
        s2, e2 = other.get("start", ""), other.get("end", "")
        if s2 and e2 and s2 <= e1 and s1 <= e2:
            return other
    return None


def build_course(payload, course_id):
    name = str(payload.get("name", "")).strip()
    if not name:
        return None, "اسم الفرقة مطلوب."
    kind = str(payload.get("kind", "")).strip()
    if kind and kind not in COURSE_KINDS:
        return None, "نوع الفرقة غير صحيح."
    return {
        "id": course_id,
        "name": name,
        "place": str(payload.get("place", "")).strip(),
        "kind": kind,
        "note": str(payload.get("note", "")).strip(),
    }, None


def build_term(payload, data, term_id):
    officer_id = str(payload.get("officer_id", "")).strip()
    course_id = str(payload.get("course_id", "")).strip()
    if course_id not in by_id(data):
        return None, "الفرقة غير موجودة."

    raw_start = str(payload.get("start", "") or "").strip()
    raw_end = str(payload.get("end", "") or "").strip()

    start = parse_date(raw_start) if raw_start else None
    end = parse_date(raw_end) if raw_end else None

    if raw_start and not start:
        return None, "تاريخ البداية غير صحيح."
    if raw_end and not end:
        return None, "تاريخ النهاية غير صحيح."
    if start and end and end < start:
        return None, "تاريخ النهاية لا يمكن أن يسبق تاريخ البداية."
    if start and end and (end - start).days > 400:
        return None, "مدة الفرقة كبيرة بشكل غير منطقي."

    return {
        "id": term_id,
        "course_id": course_id,
        "officer_id": officer_id,
        "start": start.isoformat() if start else "",
        "end": end.isoformat() if end else "",
        "note": str(payload.get("note", "") or "").strip(),
        # النص الأصلي من الأرشيف لو الالتحاق اتستخرج منه
        "source": str(payload.get("source", "") or "").strip(),
    }, None



def new_course_id(data):
    return next_id(courses(data), "CRS")


def new_term_id(data):
    return next_id(terms(data), "CT", width=4)


def _span_days(term):
    start, end = parse_date(term.get("start")), parse_date(term.get("end"))
    return (end - start).days + 1 if start and end else 0


def _detail(term, course, person, day=None):
    """كل حاجة عن الالتحاق: الفرقة نفسها + المدة + رتبة الضابط ومنصبه
    **وقت ما خدها** (مش النهاردة)."""
    from .people import effective
    eff = effective(person or {}, day or term.get("start", ""))
    return {
        **term,
        "days": _span_days(term),
        "course_name": (course or {}).get("name", ""),
        "course_place": (course or {}).get("place", ""),
        "course_kind": (course or {}).get("kind", ""),
        "course_note": (course or {}).get("note", ""),
        "officer_name": (person or {}).get("name", ""),
        "officer_role": eff["role"],
        "officer_post": eff["post"],
    }


def by_officer(data):
    """صف لكل ضابط، وقدامه الفرق اللي خدها — التجميع التاني للصفحة.

    الضباط اللي مخدوش أي فرقة بيظهروا برضو: «مين لسه ماخدش فرقة» سؤال
    تشغيلي زي «مين خد إيه» بالظبط.
    """
    from .people import officers_on
    from .utils import command_priority_map, rank_key

    catalog = by_id(data)
    people = {p["id"]: p for b in ("active", "archive") for p in data["officers"][b]}
    grouped = {}
    for term in terms(data):
        grouped.setdefault(term["officer_id"], []).append(term)

    # النشطين كلهم + أي متأرشف ليه التحاق مسجّل
    shown = list(data["officers"]["active"])
    known = {p["id"] for p in shown}
    shown += [p for p in data["officers"]["archive"]
              if p["id"] in grouped and p["id"] not in known]
    priority = command_priority_map(data)
    shown.sort(key=lambda p: rank_key(p, priority))

    out = []
    for person in shown:
        rows = sorted(grouped.get(person["id"], []), key=lambda t: t.get("start", ""))
        details = [_detail(t, catalog.get(t["course_id"]), person) for t in rows]
        out.append({
            "id": person["id"],
            "name": person.get("name", ""),
            "role": person.get("role", ""),
            "post": person.get("post", ""),
            "courses": details,
            "count": len(details),
            "days": sum(d["days"] for d in details),
        })
    return out


def summary(data, officer_ids=None):
    """كل فرقة ومعاها التحاقاتها — للعرض في الصفحة."""
    people = {p["id"]: p for cat in ("officers",)
              for b in ("active", "archive") for p in data[cat][b]}
    grouped = {}
    for term in terms(data):
        grouped.setdefault(term["course_id"], []).append(term)

    out = []
    for course in courses(data):
        rows = sorted(grouped.get(course["id"], []), key=lambda t: t.get("start", ""))
        details = [_detail(t, course, people.get(t["officer_id"])) for t in rows]
        out.append({
            **course,
            "terms": details,
            "officers": len({t["officer_id"] for t in rows}),
            "days": sum(d["days"] for d in details),
        })
    return out

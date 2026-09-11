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
from .date_range import overlapping_of, parse_range
from .people import effective
from .store import reserve_id
from .utils import command_priority_map, parse_date, rank_key

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
    return overlapping_of(terms(data), term.get("start", ""), term.get("end", ""),
                           "officer_id", term["officer_id"], ignore_id)


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
    """يبني سجل التحاق متحقق منه. التحقق من الضابط **هنا** مش في المسار،
    عشان الإضافة والتعديل الاتنين يعدّوا عليه — `edit_term` كان بيستدعي
    الدالة دي على طول من غير الفحص اللي في `add_term`، فكان ينفع تعدّل
    التحاق وتحطّ فيه ضابط مش موجود أصلًا ويتخزّن كسجل يتيم بلا اسم."""
    from .people import find_person

    officer_id = str(payload.get("officer_id", "")).strip()
    person, category, _ = find_person(data, officer_id)
    if not person or category != "officers":
        return None, "برجاء اختيار الضابط."

    course_id = str(payload.get("course_id", "")).strip()
    if course_id not in by_id(data):
        return None, "الفرقة غير موجودة."

    start, end, error = parse_range(payload, 400, "مدة الفرقة كبيرة بشكل غير منطقي.")
    if error:
        return None, error

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
    return reserve_id(data, "CRS", courses(data))


def new_term_id(data):
    return reserve_id(data, "CT", terms(data), width=4)


def _span_days(term):
    start, end = parse_date(term.get("start")), parse_date(term.get("end"))
    return (end - start).days + 1 if start and end else 0


def _detail(term, course, person, day=None):
    """كل حاجة عن الالتحاق: الفرقة نفسها + المدة + رتبة الضابط ومنصبه
    **وقت ما خدها** (مش النهاردة)."""
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

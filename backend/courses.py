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
        if term.get("start", "") <= day <= term.get("end", ""):
            return term
    return None


def overlapping(data, term, ignore_id=None):
    """التحاق تاني لنفس الضابط بيتقاطع مع المدى ده."""
    for other in terms(data):
        if other.get("id") == ignore_id or other.get("officer_id") != term["officer_id"]:
            continue
        if other["start"] <= term["end"] and term["start"] <= other["end"]:
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

    start, end = parse_date(payload.get("start")), parse_date(payload.get("end"))
    if not start or not end:
        return None, "برجاء إدخال تاريخ بداية ونهاية صحيحين."
    if end < start:
        return None, "تاريخ النهاية لا يمكن أن يسبق تاريخ البداية."
    if (end - start).days > 400:
        return None, "مدة الفرقة كبيرة بشكل غير منطقي."

    return {
        "id": term_id,
        "course_id": course_id,
        "officer_id": officer_id,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "note": str(payload.get("note", "")).strip(),
        # النص الأصلي من الأرشيف لو الالتحاق اتستخرج منه
        "source": str(payload.get("source", "")).strip(),
    }, None


def new_course_id(data):
    return next_id(courses(data), "CRS")


def new_term_id(data):
    return next_id(terms(data), "CT", width=4)


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
        out.append({
            **course,
            "terms": [{**t,
                       "officer_name": people.get(t["officer_id"], {}).get("name", ""),
                       "officer_role": people.get(t["officer_id"], {}).get("role", "")}
                      for t in rows],
            "officers": len({t["officer_id"] for t in rows}),
            "days": sum(1 for t in rows for _ in [0]),
        })
    return out

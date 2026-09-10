"""تكليفات اليوم — المصدر الوحيد للحقيقة «فلان على الخدمة دي النهاردة».

قبل كده كان فيه سجلّين لنفس الحقيقة: `duties[day][officer]` بالـid و
`day_services[day]` باسم الخدمة كنص، مربوطين بجسر هش `{اسم: خدمة}` في
`sync.py`. النتيجة كانت عائلة أخطاء كاملة: إعادة تسمية خدمة تمسح التكليف
بالسكوت، إزالة تكليف تسيب اسم الضابط على اللوحة، وضابطين على نفس الخدمة
والفترة واحد فيهم يختفي.

دلوقتي فيه سجل واحد:

    day_assignments[day] = [ {id, section, service_id, shift, officer_ids,
                              personnel_ids, conscripts, ...}, ... ]

ويومية الضباط واللوحة **عرضان محسوبان** عليه (`duty.py` و`board.py`) —
مفيش حاجة تتزامن لأن مفيش نسختين.

وجنبه سجل تاني **مش تكرار** — دي حقيقة مختلفة، حالة الضابط نفسه:

    day_officers[day][officer_id] = {taqseera, status, note}

الفرق المهم في الشكل: `officer_ids` **قايمة**:
  - فاضية  = خانة شاغرة. الوورد فيه 1,034 صف خدمات طارئة بقوام أفراد
             ومجندين بس من غير أي ضابط — كانت مستحيلة التمثيل قبل كده.
  - واحد   = الحالة العادية.
  - أكتر   = صف مشترك، زي «رائد/جمال امين م.اول/ماركو ماجد» في لوحة 20/8.
"""
from .constants import SECTION_OCCASIONAL, SHIFTS
from .store import next_id

# حالات الضابط اللي مش تكليف بخدمة. «مرضي» و«فرقة» و«طارئة» كانوا ناقصين،
# فكانت خاناتهم في جدول الإجمالي مستحيل يوصلها رقم صح رغم إنهم في الوورد
# 16 و30 مرة على التوالي.
OFFICER_STATUSES = ["انتداب", "غياب", "مرضي", "فرقة", "طارئة"]


def services_by_id(data):
    return {s["id"]: s for s in data.get("services", [])}


def resolve_service(data, raw_name):
    """خدمة من أي صورة مكتوبة للاسم — بالتطبيع وبالـaliases.

    الاستيراد والهجرة بيستخدموها عشان «نقطة التفتيش» تلاقي «نقطه تفتيش»،
    و«التدخل السريع» تلاقي «تدخل سريع». التطابق الحرفي اللي كان مستخدم
    قبل كده هو اللي خلّى 711 تكليف يقع في «الصافي».
    """
    from .text import core_service_name, norm
    key, core = norm(raw_name), core_service_name(raw_name)
    for svc in data.get("services", []):
        aliases = set(svc.get("aliases") or []) | {norm(svc["name"])}
        if key in aliases or core in aliases:
            return svc
    return None


def for_day(data, day):
    """قايمة تكليفات اليوم — بتتعمل فاضية لو مش موجودة."""
    return data.setdefault("day_assignments", {}).setdefault(day, [])


def peek_day(data, day):
    """زي for_day بس من غير ما تعمل مدخل جديد — للقراءة المجردة."""
    return (data.get("day_assignments") or {}).get(day, [])


def officer_states(data, day):
    return (data.get("day_officers") or {}).get(day, {})


def officer_state(data, day, officer_id):
    return officer_states(data, day).get(officer_id) or {}


def set_officer_state(data, day, officer_id, taqseera=None, status=None, note=None):
    """حالة الضابط (تقصيرة/انتداب/غياب/مرضي/فرقة/طارئة/ملاحظة).
    السجل بيتشال لما يفضّى عشان الملف ما يمتلئش بمدخلات فاضية."""
    states = data.setdefault("day_officers", {}).setdefault(day, {})
    entry = dict(states.get(officer_id) or {})
    if taqseera is not None:
        entry["taqseera"] = bool(taqseera)
    if status is not None:
        entry["status"] = status
    if note is not None:
        entry["note"] = note

    if not entry.get("taqseera") and not entry.get("status") and not entry.get("note"):
        states.pop(officer_id, None)
    else:
        states[officer_id] = entry
    if not states:
        data["day_officers"].pop(day, None)
    return entry


def assignments_of(data, day, officer_id):
    """تكليفات ضابط معيّن في يوم — بترتيبها على اللوحة."""
    return [a for a in peek_day(data, day) if officer_id in (a.get("officer_ids") or [])]


def new_id(entries):
    return next_id(entries, "AS", width=4)


def clean_shift(shift, svc):
    """الفترة المسموحة للخدمة دي. الحراسات هدف ثابت طول اليوم فمالهاش فترة،
    و«محور 1» وأخواتها صباحية بس زي ما الوورد بيكتب («ــــ» في العمود الليلي)."""
    if (svc or {}).get("kind") == "حراسات":
        return ""
    shift = (shift or "").strip()
    if shift not in SHIFTS:
        return ""
    allowed = (svc or {}).get("shifts") or SHIFTS
    return shift if shift in allowed else (allowed[0] if allowed else "")


def clean_conscripts(raw):
    """[{class, count}] — قوام المجندين بالفئة (قتالية/فض/حفظ نظام/رياضي)."""
    out = []
    for item in (raw or []):
        if not isinstance(item, dict):
            continue
        cls = str(item.get("class", "")).strip()
        try:
            count = int(item.get("count", 0))
        except (TypeError, ValueError):
            count = 0
        if not cls and count <= 0:
            continue
        out.append({"class": cls, "count": max(count, 0)})
    return out


def blank(assignment_id, service_id, section, **over):
    """تكليف بالشكل الكامل — مكان واحد بيعرّف الحقول عشان ما تختلفش
    بين الاستيراد والـAPI والهجرة."""
    row = {
        "id": assignment_id,
        "section": section,
        "service_id": service_id,
        "shift": "",
        "officer_ids": [],
        "personnel_ids": [],
        "conscripts": [],
        "weapon": "",
        "time": "",
        "party": "",
        "label_override": "",
        "tags": [],
        "note": "",
    }
    row.update(over)
    return row


def label(assignment, svc, with_shift=True):
    """النص اللي بيتطبع على اللوحة. الوورد بيكتب الفترة **جوّه** اسم
    الخدمة في القسم الأساسي («تدخل سريع صبح»)، والأهداف بأسماء مختصرة
    («سوميد» مش «هدف سوميد») — عشان كده فيه board_label في الكتالوج."""
    from .constants import SHIFT_SHORT
    text = (assignment.get("label_override") or "").strip()
    if text:
        return text
    text = (svc or {}).get("board_label") or (svc or {}).get("name") or ""
    sub = (svc or {}).get("sub") or ""
    if sub:
        text = f"{text} | {sub}"
    short = SHIFT_SHORT.get(assignment.get("shift") or "")
    if with_shift and short:
        text = f"{text} {short}"
    return text


def clean_people(data, day, ids, want):
    """يتحقق إن كل شخص موجود وإنه من النوع الصح وإنه كان على القوة يومها.
    بترجع (القايمة, error, status) — error=None لو تمام.

    الضابط المتأرشف ينفع يتكلّف في يوم كان فيه بالقوة — ده مطلوب عشان
    تعديل الأيام القديمة يشتغل. قبل كده اللوحة كانت بتعرض النشطين بس
    بينما يومية التشغيل بتقبل الاتنين، فالصفحتين مكانوش شايفين نفس القايمة.
    """
    from .people import find_person, officers_on

    out = []
    on_force = {o["id"] for o in officers_on(data, day)} if want == "officers" else None
    for pid in ids or []:
        pid = str(pid).strip()
        if not pid or pid in out:
            continue
        person, category, _ = find_person(data, pid)
        if not person or category != want:
            return None, ("ضابط غير موجود." if want == "officers" else "فرد غير موجود."), 404
        if on_force is not None and pid not in on_force:
            return None, f"«{person.get('name', '')}» لم يكن على القوة في هذا اليوم.", 400
        out.append(pid)
    return out, None, None


def guard_duplicate(data, day, row, ignore_id):
    """التكرار الحرفي بس هو الممنوع: نفس الشخص على نفس الخدمة ونفس الفترة
    مرتين. باقي «التعارضات» بتتعرض كتنبيهات — الأرشيف فيه ضباط على
    خدمتين في نفس الفترة فعلًا (20/8: تبة ضرب النار + كنترول الازهر ليل).

    بترجع رسالة خطأ أو None — الاستيراد جوه الدالة لتفادي دورة استيراد
    (`checks.py` بيستورد من الملف ده أصلًا).
    """
    from .checks import duplicate_of

    people = (row.get("officer_ids") or []) + (row.get("personnel_ids") or [])
    if not people:
        return None
    clash = duplicate_of(data, day, row["service_id"], row.get("shift"),
                         people, ignore_id=ignore_id)
    if clash:
        return "الشخص ده متكلّف بنفس الخدمة ونفس الفترة في خانة تانية."
    return None


def apply_assignment(data, day, row, payload, svc):
    """بيطبّق حقول الطلب على صف التكليف. بترجع (row, error, status) —
    لو error مش None يبقى row=None."""
    if "shift" in payload:
        row["shift"] = clean_shift(payload["shift"], svc)
    if "section" in payload:
        section = str(payload["section"]).strip()
        row["section"] = section or (svc or {}).get("section") or SECTION_OCCASIONAL
    if "officer_ids" in payload:
        ids, err, status = clean_people(data, day, payload["officer_ids"], "officers")
        if err:
            return None, err, status
        row["officer_ids"] = ids
    if "personnel_ids" in payload:
        ids, err, status = clean_people(data, day, payload["personnel_ids"], "personnel")
        if err:
            return None, err, status
        row["personnel_ids"] = ids
    if "conscripts" in payload:
        row["conscripts"] = clean_conscripts(payload["conscripts"])
    if "tags" in payload:
        row["tags"] = [str(t).strip() for t in payload["tags"] if str(t).strip()]
        for tag in row["tags"]:
            if tag not in data["service_tags"]:
                data["service_tags"].append(tag)
    for key in ("weapon", "time", "party", "label_override", "note"):
        if key in payload:
            row[key] = str(payload[key]).strip()
    return row, None, None

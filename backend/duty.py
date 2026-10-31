"""يومية تشغيل الضباط + جدول الإجمالي — **عرض محسوب** على تكليفات اليوم.

مفيش أي تخزين هنا: الجدول كله بيتبني من `day_assignments` و`day_officers`
والراحات، فمستحيل يختلف عن اللوحة لأن الاتنين بيقروا من نفس المكان.

جدول الإجمالي في الوورد (موجود في يوميات 17/8 وطالع، 22 يوم):

    أصل القوة | خارجية (صباحية|ليلية|+N بحث) | داخلية (صباحية|ليلية|+N معسكر فرعي)
    | طبية (موجود|راحة) | خوارج (تقصيرة|راحة|طارئة|غياب|مرضي|فرقة|انتداب)
    | الحراسات المشددة | الصافي (N) + الأسماء

**كل ضابط في خانة واحدة بس** — مجموع الخانات لازم يساوي أصل القوة، وده
مثبت في الوورد (34 في كل الأيام المفحوصة). عشان كده الترتيب اللي تحت
مهم: الضابط بياخد أول خانة تنطبق عليه.
"""
from .assignments import assignments_of, officer_state, officer_statuses
from .courses import by_id as courses_by_id, term_on
from .constants import (LEAVE_BUCKET, ROLE_MEDICAL, ROLE_SEARCH, SECTION_SUBCAMP,
                        SECTION_TARGETS, SHIFTS, SUBCAMP_SERVICES, TARGETS_FIRST)
from .dated import command_on, groups_on, medical_state_on
from .leaves import leave_label, leave_on
from .people import effective, officers_on
from .status_periods import active_on as persistent_status_on
from .status_periods import public as status_period_public

# سلّم أولويات خانة الإجمالي — أول قاعدة تنطبق هي اللي بتاخد الضابط.
# كل ضابط في خانة واحدة بس، ومجموع الخانات لازم يساوي أصل القوة (ثابت في
# كل جداول الوورد المفحوصة). أي تعديل هنا لازم يعدّي على
# tools/calibrate_summary.py الأول.
#
#   1. حالة مكتوبة لليوم ده   انتداب/غياب/مرضي/فرقة/طارئة
#   2. ضابط العيادة           عضو في منصب «طبي» الجماعي في قيادة الإدارة، أو خدمة
#                             اليوم تصنيفها «طبية» — بيفضل في عمود الطبية
#                             حتى وهو في راحة
#   3. راحة مسجّلة             إلا لو الضابط بحث؛ البحث له وسمه في الخارجية
#   4. تقصيرة                 بتغلب الخدمة **والحراسة** — الضابط اشتغل وخرج بدري
#   5. بحث                    عضوية بحث أو search_attached، حتى من غير خدمة أو مع راحة
#   6. أول خدمة اتحط عليها    الخانة اللي اتحط فيها الأول هي اللي تتحسب
#   7. فرقة                   مدى الالتحاق بيملا الأيام الفاضية بس
#   8. معسكر فرعي             لو ده شغله الوحيد، وقبل الصافي
#   9. صافي
PRIORITY = ("حالة مكتوبة", "طبية", "راحة", "تقصيرة", "بحث",
            "حراسات", "أول خدمة اتحط عليها", "فرقة", "معسكر فرعي", "صافي")

# لما التكليف نفسه مالوش فترة مسجّلة
DEFAULT_SHIFT = "صباحية"


def _first_cell(kinds):
    """-> (المجموعة، الخانة) لضابط عليه خدمة أو أكتر.

    الحراسات بتغلب أي ترتيب: قائد الهدف بيتحسب حراسات حتى لو الهدف مش أول
    خدمة مكتوبة في سطره (يومية 31/8: «مدرجات الدرجة الاولي + عمل بهدف
    كهرباء عتاقة» — الوورد حسبه حراسات). قياس على 14 يوم: 93% بالقاعدة
    دي مقابل 71% من غيرها.

    وبعد كده الترتيب هو الحكم: الخانة اللي اتحط فيها الأول هي اللي تتحسب.
    """
    if any(kind == "حراسات" for kind, _ in kinds):
        return ("حراسات", None)

    kind, shift = next(((k, sh) for k, sh in kinds if k in ("خارجية", "داخلية")),
                       (None, None))
    if kind is None:
        return ("صافي", None)
    return (kind, shift if shift in SHIFTS else DEFAULT_SHIFT)


def _empty_summary(force, statuses=()):
    outside = ["تقصيرة", "راحة", "طارئة", "غياب", "مرضي", "فرقة", "انتداب"]
    outside += [value for value in statuses if value not in outside]
    return {
        "أصل القوة": force,
        "خارجية": {"صباحية": 0, "ليلية": 0, "بحث": 0},
        "داخلية": {"صباحية": 0, "ليلية": 0},
        "طبية": {"موجود": 0, "راحة": 0},
        "خوارج": {key: 0 for key in outside},
        "حراسات": 0,
        "معسكر فرعي": 0,
        "صافي": 0,
    }


def _bucket(kinds, leave, state, medical, research, subcamp=False, course=None,
            medical_state="عمل"):
    """-> (المجموعة، الخانة الفرعية) لضابط واحد. القواعد بترتيب PRIORITY."""
    # حالة مكتوبة بالإيد لليوم ده بالذات بتغلب أي افتراض
    status = state.get("status") or ""
    if status:
        # انتداب/غياب/مرضي/فرقة/طارئة — كلها خانات موجودة في جدول الوورد
        return ("خوارج", status)

    # الإجازة الفعلية لضابط الطبي أقوى من اختياره الموروث، وبتفضل في عمود
    # الطبية/راحة زي السلوك القديم. بعد كده «انتداب» الطبي يروح خوارج،
    # و«راحة» تفضل داخل الطبية.
    if medical:
        if leave:
            return ("طبية", "راحة")
        if medical_state == "انتداب":
            return ("خوارج", "انتداب")
        return ("طبية", "راحة" if medical_state == "راحة" else "موجود")

    # الراحة تفضل أقوى من التقصيرة والخدمة في القاعدة القديمة؛ البحث وحده
    # استثناء الوورد، لأنه يظل «بحث» حتى وهو في راحة عادية.
    if leave and not research:
        return ("خوارج", LEAVE_BUCKET.get(leave["type"], "راحة"))
    if state.get("taqseera"):
        return ("خوارج", "تقصيرة")

    # الالتحاق بفرقة بيغطي أيامه لوحده — زي الراحة — بدل ما الكلمة تتكتب
    # في تشغيل كل يوم. لكنه **مابيلغيش تكليف مسجّل**: المدة بتيجي من نص
    # مكتوب مرة واحدة («من 22/8 حتى 3/9») وساعات الضابط بيرجع بدري أو
    # الفرقة بتتأجل، والدليل على كده إنه ظاهر على خدمة في اليوم ده.
    # المكتوب لليوم بعينه أقوى من المدى المستنتج.
    if course and not kinds and not leave:
        return ("خوارج", "فرقة")
    # البحث بيتحسب حتى من غير خدمة، ومع الراحة العادية كمان. الحالات
    # المكتوبة والطبي والتقصيرة والفرقة اتحسمت فوقه، زي precedence الوورد.
    if research:
        return ("خارجية", "بحث")
    if kinds:
        return _first_cell(kinds)
    # خدمة المعسكر الفرعي لا تدخل في الخدمات العددية ولا الصافي؛ لها خانة
    # مستقلة في الإجمالي، بشرط ألا يكون للضابط تصنيف أقوى.
    if subcamp:
        return ("معسكر فرعي", None)
    return ("صافي", None)


def service_line(service):
    """سطر خدمة واحدة زي ما بيتطبع في يومية الضباط: الاسم + «فترة <الفترة>».

    الأهداف بتتكتب في الورقة «عمل بهدف <الهدف>» ومشرف الأهداف «متابعة اعمال
    الاهداف» — مش اسم الهدف لوحده زي ما هو على اللوحة."""
    text = service.get("name", "")
    if service.get("section") == SECTION_TARGETS and text:
        text = "متابعة اعمال الاهداف" if text == TARGETS_FIRST else f"عمل بهدف {text}"
    if service.get("shift"):
        text += f" فترة {service['shift']}"
    return text


def manual_text(note, extra):
    """النص اليدوي بس: `note` (نص تشغيل مستورد) ثم التشغيل الإضافي."""
    return " + ".join(part.strip() for part in (note, extra) if str(part or "").strip())


def operational_text(services, note, extra):
    """النص التشغيلي الكامل للضابط في اليوم: خدمته التلقائية من اللوحة +
    التشغيل الإضافي اليدوي.

    `note` هو نص التشغيل المستورد من الوورد القديم وبيكون **كامل** (خدمة +
    إضافة) — لو موجود بيحل محل الخدمة التلقائية عشان ماتتكررش. أما الأيام
    الجديدة فمفيهاش `note`: الخدمة بتيجي من اللوحة والإضافة من `extra`.
    فاضي لو مفيش خدمة ولا نص."""
    base = str(note or "").strip()
    if not base:
        base = " + ".join(line for line in map(service_line, services or []) if line)
    extra = str(extra or "").strip()
    return " + ".join(part for part in (base, extra) if part)


def research_text(service, regularity_time):
    """تشغيل ضابط البحث لليوم؛ الفاضي له النص الثابت المطلوب في اليومية."""
    service = str(service or "").strip()
    regularity_time = str(regularity_time or "").strip()
    if not service:
        return "تشغيله ـــــــــــــــــــــ"
    return f"{service} — انتظام {regularity_time}" if regularity_time else service


def _dmy(iso):
    """«2026-10-03» -> «3/10/2026» — نفس كتابة التواريخ في نص التشغيل."""
    try:
        year, month, day = (int(part) for part in str(iso).split("-"))
    except ValueError:
        return str(iso or "")
    return f"{day}/{month}/{year}"


def course_text(course):
    """جملة الفرقة زي ما بتتكتب في اليومية: «<الاسم> خلال الفترة من … حتى …
    ب<المكان>». الأجزاء الناقصة بتتشال من غير ما تسيب كلام مكسور."""
    parts = [course.get("name") or "فرقة"]
    if course.get("start") and course.get("end"):
        parts.append(f"خلال الفترة من {_dmy(course['start'])} حتى {_dmy(course['end'])}")
    if course.get("place"):
        parts.append(f"ب{course['place']}")
    return " ".join(parts)


def _fold_arabic(value):
    """توحيد الهمزات والياء/الألف المقصورة والتاء المربوطة والتطويل والتشكيل والشرطات."""
    table = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه", "ـ": None,
                              "—": " ", "–": " ", "-": " ", "،": " "})
    value = "".join(ch for ch in str(value or "").translate(table)
                    if not 0x064B <= ord(ch) <= 0x065F)
    return " ".join(value.split())


def course_with_note(course, note):
    """نص الفرقة + النص اليدوي بلا تكرار. صف مستورد كاتب الفرقة كاملة في
    ملاحظته («فرقة … خلال الفترة …») بيتعرض زي ما هو."""
    note = str(note or "").strip()
    text = (course or {}).get("text", "")
    if not text or (note and (course.get("name") or text) in note):
        return note or text
    # الملاحظة المستوردة كثيرًا ما تكتب نفس اسم الفرقة بهمزة/ياء/تطويل مختلف
    # («إعداد» مقابل «اعداد») فيتكرر الوصف؛ قارن بعد توحيد الإملاء.
    if note and _fold_arabic(course.get("name") or text) in _fold_arabic(note):
        return note
    return f"{text} — {note}" if note else text


def course_detail(term, course):
    """تفاصيل الالتحاق + الفرقة نفسها لصف اليومية — أو None."""
    if not term:
        return None
    course = course or {}
    detail = {"id": term["id"], "course_id": term["course_id"],
              "name": course.get("name", ""), "place": course.get("place", ""),
              "kind": course.get("kind", ""),
              "start": term.get("start", ""), "end": term.get("end", ""),
              "term_note": term.get("note", ""), "course_note": course.get("note", "")}
    detail["text"] = course_text(detail)
    return detail


def officer_row(data, day, o, catalog=None):
    """صف ضابط واحد في يومية اليوم — نفس صف `summarise` بالظبط.

    ``catalog`` فهرس الفرق بالمعرّف (`courses.by_id`) — بيتمرر من `summarise`
    عشان مايتبنيش لكل ضابط."""
    if catalog is None:
        catalog = courses_by_id(data)
    eff = effective(o, day)
    state = officer_state(data, day, o["id"])
    persistent = persistent_status_on(data, o["id"], day)
    effective_state = dict(state)
    if not effective_state.get("status") and persistent:
        effective_state["status"] = persistent.get("status", "")
    leave = leave_on(data, o["id"], day)
    term = term_on(data, o["id"], day)

    items = []
    for a in assignments_of(data, day, o["id"]):
        items.append({"assignment_id": a["id"], "name": a.get("name", ""),
                      "kind": a.get("kind") or "خارجية", "shift": a.get("shift", ""),
                      "section": a.get("section", ""),
                      "counted": a.get("counts_in_summary", True)})
    # خدمة المعسكر الفرعي لا تتحسب كخدمة عادية، لكن لها خانة مستقلة إذا كانت
    # هي الشغل الوحيد للضابط. أي خدمة محسوبة أو حالة أقوى تغلبها.
    kinds = [(it["kind"], it["shift"]) for it in items if it["counted"]]
    subcamp = bool(items) and all(
        not item["counted"] and (item["section"] == SECTION_SUBCAMP or
                                  item["name"] in SUBCAMP_SERVICES)
        for item in items
    )
    groups = groups_on(data, day)
    medical = o["id"] in (groups.get(ROLE_MEDICAL) or [])
    medical_bucket = medical or any(k == "طبية" for k, _ in kinds)
    # عضو مجموعة «بحث» = تعيين خدمته من زرار الحالة ونصّه «تشغيله ـــ».
    # العدّ في «+N بحث» أوسع: العضوية أو search_attached.
    research = o["id"] in (groups.get(ROLE_SEARCH) or [])
    counts_as_research = research or bool(eff["search_attached"])
    medical_choice = medical_state_on(data, o["id"], day) if medical else {
        "state": "", "deputation_text": "", "from": ""}

    group, sub = _bucket(kinds, leave, effective_state, medical_bucket,
                         counts_as_research, subcamp, term, medical_choice["state"])
    text = operational_text(items, state.get("note", ""), state.get("extra", ""))
    # الحالات الخاصة والإجازات الفعلية تفضل صاحبة الأولوية في الشاشة والوورد.
    # لو الضابط عضو في المجموعتين معًا، الطبي هو التصنيف الأقوى زي `_bucket`.
    if not effective_state.get("status") and not leave:
        if medical:
            choice = medical_choice["state"]
            if choice == "انتداب":
                text = medical_choice["deputation_text"] or "انتداب"
            elif choice == "راحة":
                text = "راحة"
            else:
                # «عمل» مابيمسحش تشغيله المكتوب (خدمة/ملاحظة/إضافي)
                text = text or "عمل"
        elif research:
            text = research_text(state.get("research_service", ""),
                                 state.get("research_time", ""))
    return {
        "id": o["id"], "name": o.get("name", ""), "short_name": o.get("short_name", ""),
        "phone": o.get("phone", ""),
        "role": eff["role"], "post": eff["post"], "section": eff["section"],
        "search_attached": eff["search_attached"],
        "research": research,
        "research_service": state.get("research_service", ""),
        "research_time": state.get("research_time", ""),
        "medical": medical,
        "medical_state": medical_choice["state"],
        "medical_deputation_text": medical_choice["deputation_text"],
        "medical_state_from": medical_choice["from"],
        "rest_system": eff["rest_system"], "rest_day": eff["rest_day"],
        "group": group, "bucket": sub,
        "services": items,
        "taqseera": bool(state.get("taqseera")),
        "status": effective_state.get("status", ""),
        "manual_status": state.get("status", ""),
        "status_source": "period" if persistent and not state.get("status") else (
            "day" if state.get("status") else ""),
        # الحالة الممتدة (مستمرة أو طارئة بمدة) اللي بتغطي اليوم، لو فيه
        "persistent_status": status_period_public(persistent),
        "extra": state.get("extra", ""),
        "admin_work": bool(state.get("admin_work")),
        # نص «عمل بالإدارة» الحر — بيدخل الضابط تحت القسم بالنص ده بالظبط
        "admin_work_text": state.get("admin_work_text", ""),
        # النص التشغيلي الكامل (خدمته + اليدوي) والنص اليدوي بس
        "text": text,
        "manual": manual_text(state.get("note", ""), state.get("extra", "")),
        "leave": ({"id": leave.get("id"), "type": leave_label(leave),
                   "raw_type": leave["type"], "start": leave["start"],
                   "end": leave["end"],
                   "return_date": leave["return_date"]} if leave else None),
        "note": state.get("note", ""),
        "course": course_detail(term, catalog.get(term["course_id"]) if term else None),
        # كان بالقوة يومها لكنه خرج بعد كده — للتوضيح في اليوميات القديمة
        "later_left": o.get("leave_date", "") or None,
    }


def summarise(data, day):
    """يومية الضباط كاملة: صف لكل ضابط كان على القوة + جدول الإجمالي."""
    officers = officers_on(data, day)
    catalog = courses_by_id(data)

    statuses = officer_statuses(data)
    s = _empty_summary(len(officers), statuses)
    net_names, rows = [], []
    command_roles = {officer_id: role for role, officer_id in command_on(data, day).items()
                     if officer_id}

    for o in officers:
        row = officer_row(data, day, o, catalog)
        row["command_role"] = command_roles.get(row["id"], "")
        group, sub = row["group"], row["bucket"]
        if sub is None:
            s[group] += 1
            if group == "صافي":
                net_names.append(f'{row["role"]}/ {o.get("name", "")}')
        else:
            # تصنيف حالة قديم أو مضاف يدويًا لا يوقف اليومية حتى لو لم يكن
            # موجودًا بعد في القائمة العامة لسبب ما.
            s[group][sub] = s[group].get(sub, 0) + 1
        rows.append(row)

    counted = (sum(s["خارجية"].values()) + sum(s["داخلية"].values())
               + sum(s["طبية"].values()) + sum(s["خوارج"].values())
               + s["حراسات"] + s["معسكر فرعي"] + s["صافي"])
    s["net_names"] = net_names
    s["counted"] = counted
    s["balanced"] = counted == s["أصل القوة"]
    return {"date": day, "summary": s, "rows": rows,
            "officer_statuses": officer_statuses(data)}

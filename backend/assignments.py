"""تكليفات اليوم — المصدر الوحيد للحقيقة «فلان على الخدمة دي النهاردة».

قبل كده كان فيه سجلّين لنفس الحقيقة: `duties[day][officer]` بالـid و
`day_services[day]` باسم الخدمة كنص، مربوطين بجسر هش `{اسم: خدمة}` في
`sync.py`. النتيجة كانت عائلة أخطاء كاملة: إزالة تكليف تسيب اسم الضابط
على اللوحة، وضابطين على نفس الخدمة والفترة واحد فيهم يختفي.

دلوقتي فيه سجل واحد:

    day_assignments[day] = [ {id, section, name, kind, shift, officer_ids,
                              personnel_ids, conscripts, ...}, ... ]

ويومية الضباط واللوحة **عرضان محسوبان** عليه (`duty.py` و`board.py`) —
مفيش حاجة تتزامن لأن مفيش نسختين.

الخدمة **اسم حر بيكتبه المشغّل على الخانة نفسها** — مفيش كتالوج منفصل
تتربط بيه بـid. القرار ده مقصود: كان فيه كتالوج بـ17 حقل تعريف لكل
خدمة، وطلع في الاستخدام الفعلي معقّد أكتر من اللازم لمرحلة النظام دي.
الخدمات الأساسية المتكررة بقت بتتسكّن في صفحة «اعداد الخدمات»
(`backend/counts.py`) بدل الكتالوج، والخدمات الطارئة بتتكتب مباشرة هنا.

وجنبه سجل تاني **مش تكرار** — دي حقيقة مختلفة، حالة الضابط نفسه:

    day_officers[day][officer_id] = {taqseera, status, note, extra, admin_work}

الفرق المهم في الشكل: `officer_ids` **قايمة**:
  - فاضية  = خانة شاغرة. الوورد فيه 1,034 صف خدمات طارئة بقوام أفراد
             ومجندين بس من غير أي ضابط — كانت مستحيلة التمثيل قبل كده.
  - واحد   = الحالة العادية.
  - أكتر   = صف مشترك، زي «رائد/جمال امين م.اول/ماركو ماجد» في لوحة 20/8.
"""
from .constants import (
    SECTION_ADMIN_WORK, SECTION_NET, SECTION_OCCASIONAL, SECTION_OUTSIDERS, SECTION_RESTS,
    SECTION_TAQSEERA, SECTION_TARGETS, SECTION_PRISON, SERVICE_KINDS, SHIFTS, TARGET_NAMES,
    TARGETS_FIRST,
)
from .text import norm
from .utils import too_long
from .dated import targets_on
from .clocktime import format_time, parse_time

# القسم على اللوحة حر — أي اسم المشغّل يكتبه بيبقى قسم مستقل (لليوم ده بس،
# `backend/board.py` هو اللي بيفسّره). الأسماء المحجوزة دي استثناء: هي عناوين
# محسوبة من حالة الضباط مش خدمات مخزّنة، فلو خدمة اتسمّت بنفس اسم واحد منهم
# صفوفها هتختفي من اللوحة تمامًا (العرض المحسوب بياخد الأولوية) بدل ما تتعرض
# كقسم مخصّص — القسم الحر لازم يتفادى الأسماء دي بالذات.
RESERVED_SECTIONS = {
    SECTION_ADMIN_WORK, SECTION_NET, SECTION_RESTS, SECTION_TAQSEERA, SECTION_OUTSIDERS,
}

# الأهداف قايمة مغلقة (`board.target_row_names`) — عكس باقي الأقسام. الاسم
# والتصنيف ثابتين مش اختيار المشغّل، فالتحقق هنا بيفرضهم حتى لو حد نادى
# المسار العام (`/api/assignments`) بدل مسار الأهداف المخصّص
# (`/api/board/<day>/target/<name>`).
# حالات الضابط اللي مش تكليف بخدمة والمعروضة للاختيار في يومية الضباط.
# «مرضي»/«غياب» مستمرة حتى الإنهاء و«طارئة»/«مأمورية»/«انتداب» لمدة محددة
# (`status_periods.py`).
OFFICER_STATUSES = ["انتداب", "غياب", "مرضي", "طارئة", "مأمورية"]
# قيم بتتقري من الأرشيف بس ومش معروضة كاختيار: «فرقة» مصدرها الالتحاق
# المسجّل (`course_terms`) مش حالة يدوية، و«راحة فرقة» اتلغت. صفوف الأيام
# القديمة المكتوب فيها أي منهم بتفضل تتعرض وتتحسب في خانتها.
LEGACY_OFFICER_STATUSES = ["فرقة", "راحة فرقة"]
MAX_OFFICER_STATUS_LENGTH = 60


def is_legacy_status(value):
    return norm(str(value or "").strip()) in {norm(item) for item in LEGACY_OFFICER_STATUSES}


def officer_statuses(data):
    """الحالات الأساسية ثم أي تصنيف حر سبق حفظه، بلا تكرار نصي/إملائي.

    القيم الأرشيفية (`LEGACY_OFFICER_STATUSES`) مش بتطلع هنا حتى لو اتحفظت
    قبل كده كتصنيف حر."""
    out = list(OFFICER_STATUSES)
    seen = {norm(value) for value in out + LEGACY_OFFICER_STATUSES}
    for raw in data.get("custom_officer_statuses") or []:
        value = str(raw or "").strip()
        key = norm(value)
        if value and key not in seen:
            out.append(value)
            seen.add(key)
    return out


def remember_officer_status(data, value):
    """يسجّل تصنيف حالة جديدًا في البيانات العامة. يرجع رسالة خطأ أو None."""
    value = str(value or "").strip()
    if not value:
        return None
    if len(value) > MAX_OFFICER_STATUS_LENGTH:
        return f"تصنيف الحالة أطول من الحد المسموح ({MAX_OFFICER_STATUS_LENGTH} حرفًا)."
    if any(char in value for char in "\r\n\t"):
        return "تصنيف الحالة يجب أن يكون في سطر واحد."
    if is_legacy_status(value):
        return "«فرقة» تُسجّل من صفحة الفرق (التحاق الضابط بفرقة)، لا كحالة يدوية."
    if norm(value) not in {norm(item) for item in officer_statuses(data)}:
        data.setdefault("custom_officer_statuses", []).append(value)
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


def set_officer_state(data, day, officer_id, taqseera=None, status=None, note=None,
                      extra=None, admin_work=None, research_service=None,
                      research_time=None):
    """حالة الضابط (تقصيرة/انتداب/غياب/مرضي/فرقة/طارئة/ملاحظة/تشغيل إضافي/
    إضافة للعمل بالإدارة). السجل بيتشال لما يفضّى عشان الملف ما يمتلئش
    بمدخلات فاضية. الحقل اللي مش مبعوت (None) مابيتغيّرش."""
    states = data.setdefault("day_officers", {}).setdefault(day, {})
    entry = dict(states.get(officer_id) or {})
    if taqseera is not None:
        entry["taqseera"] = bool(taqseera)
    if status is not None:
        entry["status"] = status
    if note is not None:
        entry["note"] = note
    if extra is not None:
        entry["extra"] = extra
    if admin_work is not None:
        entry["admin_work"] = bool(admin_work)
    if research_service is not None:
        entry["research_service"] = research_service
    if research_time is not None:
        entry["research_time"] = research_time
    # الحقول الاختيارية مابيتخزّنوش فاضيين — ملفات الأيام القديمة تفضل بنفس شكلها
    for optional in ("extra", "admin_work", "research_service", "research_time"):
        if not entry.get(optional):
            entry.pop(optional, None)

    if not any((entry.get("taqseera"), entry.get("status"), entry.get("note"),
                entry.get("extra"), entry.get("admin_work"),
                entry.get("research_service"), entry.get("research_time"))):
        states.pop(officer_id, None)
    else:
        states[officer_id] = entry
    if not states:
        data["day_officers"].pop(day, None)
    return entry


def assignments_of(data, day, officer_id):
    """تكليفات ضابط معيّن في يوم — بترتيبها على اللوحة."""
    return [a for a in peek_day(data, day) if officer_id in (a.get("officer_ids") or [])]


def new_id(data, day, entries):
    """رقم تكليف جديد ما يتكررش **جوّه اليوم ده**، حتى لو اتشال آخر صف
    وحد جديد اتضاف بعده. كان `next_id` (max+1) بيرجّع نفس الرقم بعد مسح
    آخر صف — وده بيخلّي تأكيد اليومية يقرا الصف الجديد كـ«تعديل» على
    الصف المحذوف مش «حذف + إضافة»، فسطر السجل بيقول كذب.

    العدّاد بيتخزّن في `day_assignment_seq[day]` — **جوّه ملف اليوم نفسه**
    (مضاف لـ`DAY_SECTIONS`) مش في `id_seq` العام على `core.json`؛ لو
    استخدمنا `reserve_id` العادي كان كل حفظ خانة على اللوحة هيكتب
    core.json كمان، وده بيكسر مبدأ «الملف اللي ما اتغيّرش ما بيتلمسش»
    وبيلغي تأخير النسخ الاحتياطي لليوميات (BACKUP_MIN_GAP)."""
    from .store import _max_num

    seq = data.setdefault("day_assignment_seq", {})
    nxt = max(int(seq.get(day, 0)), _max_num(entries, "AS")) + 1
    seq[day] = nxt
    return f"AS-{nxt:04d}"


def forget_seq_if_day_empty(data, day):
    """يشيل عدّاد id التكليفات لليوم ده لو مفيش تكليفات عليه خالص بعد
    حذف مباشر من `day_assignments[day]` (زي `board.set_target_officers`/
    `set_slot_officers` — بيشيلوا الصف بإيدهم مش عن طريق `DayRepo`).
    من غيرها، ملف اليوم الفاضي بيفضل موجود بس عشان العدّاد
    (test_split_storage.py::test_emptying_a_day_removes_its_file)."""
    if not data.get("day_assignments", {}).get(day):
        data.get("day_assignment_seq", {}).pop(day, None)


def clean_shift(shift, kind):
    """الفترة المسموحة للخدمة دي. الحراسات هدف ثابت طول اليوم فمالهاش فترة —
    الباقي أي من الفترتين أو من غير فترة، المشغّل هو اللي بيحدد."""
    if kind == "حراسات":
        return ""
    shift = (shift or "").strip()
    return shift if shift in SHIFTS else ""


def clean_kind(kind):
    kind = str(kind or "").strip()
    return kind if kind in SERVICE_KINDS else ""


# أي عدد مجندين (إجمالي أو لفئة) — رقم صحيح من 0 لـ9999. قبل كده القيمة
# الغلط أو السالبة كانت بتتحوّل صفر بصمت، فالمشغّل يفتكر إنه سجّل عدد
# وهو اتمسح.
MAX_CONSCRIPTS = 9999
COUNT_ERROR = f"عدد المجندين لازم يكون رقمًا صحيحًا من 0 إلى {MAX_CONSCRIPTS}."


def parse_count(value):
    """-> العدد كـint، أو None لو مش رقم صحيح في المدى. الفاضي = صفر."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return 0
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        count = value
    elif isinstance(value, float) and value.is_integer():
        count = int(value)
    elif isinstance(value, str) and value.strip().isdecimal():
        count = int(value.strip())
    else:
        return None
    return count if 0 <= count <= MAX_CONSCRIPTS else None


def clean_conscripts(raw):
    """[{class, count}] — قوام المجندين بالفئة (قتالية/فض/حفظ نظام/رياضي).
    بترجع (القايمة, error) — error=None لو تمام."""
    if raw is None:
        return [], None
    if not isinstance(raw, list):
        return None, "قوام المجندين غير صحيح."
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        cls = str(item.get("class", "")).strip()
        count = parse_count(item.get("count", 0))
        if count is None:
            return None, COUNT_ERROR
        if not cls and count <= 0:
            continue
        out.append({"class": cls, "count": count})
    return out, None


def blank(assignment_id, name, section, **over):
    """تكليف بالشكل الكامل — مكان واحد بيعرّف الحقول عشان ما تختلفش
    بين الاستيراد والـAPI والهجرة."""
    row = {
        "id": assignment_id,
        "section": section,
        "name": name,
        "kind": "",
        "shift": "",
        "officer_ids": [],
        "personnel_ids": [],
        "conscripts": [],
        "conscript_count": 0,
        "weapon": "",
        "time": "",
        "party": "",
        "counts_in_summary": True,
        "mission_transport": False,
        "officer_command_required": False,
        "personnel_command_required": False,
        "note": "",
    }
    row.update(over)
    return row


# «رئاسة ضابط» / «رئاسة فرد»: الدور ممكن يكون مطلوب وشاغر في نفس الوقت
# (المشغّل حاجز المكان لحد ما يتعيّن حد)، فالعلم صريح ومحفوظ على الصف بدل ما
# يتستنتج من وجود معرّفات. الصفوف القديمة اللي فيها معرّفات من غير علم بتتعامل
# كأن الدور موجود.
COMMAND_ROLES = {
    "officer": ("officer_command_required", "officer_ids"),
    "personnel": ("personnel_command_required", "personnel_ids"),
}


def command_required(assignment, who):
    """هل دور الرئاسة (``officer``/``personnel``) موجود على الخانة؟ — العلم
    الصريح، أو (للصفوف القديمة) وجود شخص معيّن فعلًا."""
    flag, ids_key = COMMAND_ROLES[who]
    return bool(assignment.get(flag)) or bool(assignment.get(ids_key))


def command_vacant(assignment, who):
    """الدور موجود لكن لسه مفيش حد معيّن فيه."""
    _flag, ids_key = COMMAND_ROLES[who]
    return command_required(assignment, who) and not assignment.get(ids_key)


def label(assignment, with_shift=True):
    """النص اللي بيتطبع على اللوحة. الوورد بيكتب الفترة **جوّه** اسم
    الخدمة في القسم الأساسي («تدخل سريع صبح»)."""
    from .constants import SHIFT_SHORT
    text = (assignment.get("name") or "").strip()
    short = SHIFT_SHORT.get(assignment.get("shift") or "")
    if with_shift and short:
        text = f"{text} {short}"
    return text


def clean_people(data, day, ids, want):
    """يتحقق إن كل شخص موجود وإنه من النوع الصح وإنه كان على القوة يومها.
    بترجع (القايمة, error, status) — error=None لو تمام.

    الشخص المتأرشف ينفع يتكلّف في يوم كان فيه بالقوة — ده مطلوب عشان
    تعديل الأيام القديمة يشتغل. قبل كده اللوحة كانت بتعرض النشطين بس
    بينما يومية التشغيل بتقبل الاتنين، فالصفحتين مكانوش شايفين نفس القايمة.

    القيد ده كان على الضباط بس — أي فرد اتأرشف زمان كان لسه ينفع يتكلّف
    بأي يوم، حتى قبل انضمامه أو بعد خروجه بكتير، من غير أي فحص.
    """
    from .people import find_person
    from .repo import PeopleRepo

    if ids is None:
        ids = []
    if not isinstance(ids, list):
        return None, "قائمة الأشخاص غير صحيحة.", 400
    out = []
    on_force = {p["id"] for p in PeopleRepo(data).raw_on_force(day, want)}
    for pid in ids:
        pid = str(pid).strip()
        if not pid or pid in out:
            continue
        person, category, _ = find_person(data, pid)
        if not person or category != want:
            return None, ("ضابط غير موجود." if want == "officers" else "فرد غير موجود."), 404
        if pid not in on_force:
            return None, f"«{person.get('name', '')}» لم يكن على القوة في هذا اليوم.", 400
        out.append(pid)
    return out, None, None


def guard_duplicate(data, day, row, ignore_id):
    """التكرار الحرفي بس هو الممنوع: نفس الشخص على نفس اسم الخدمة (بعد
    التطبيع) ونفس الفترة مرتين. باقي «التعارضات» بتتعرض كتنبيهات — الأرشيف
    فيه ضباط على خدمتين في نفس الفترة فعلًا (20/8: تبة ضرب النار + كنترول
    الازهر ليل).

    بترجع رسالة خطأ أو None — الاستيراد جوه الدالة لتفادي دورة استيراد
    (`checks.py` بيستورد من الملف ده أصلًا).
    """
    from .checks import duplicate_of

    people = (row.get("officer_ids") or []) + (row.get("personnel_ids") or [])
    if not people:
        return None
    clash = duplicate_of(data, day, row.get("name", ""), row.get("shift"),
                         people, ignore_id=ignore_id)
    if clash:
        return "هذا الشخص مكلَّف بنفس الخدمة والفترة في خانة أخرى."
    return None


def vacant_twin(data, day, row):
    """-> id خانة شاغرة موجودة بنفس الاسم (بعد التطبيع) والقسم والتصنيف
    والفترة، لو `row` نفسها شاغرة — أو None.

    مش منع: خانتين شاغرتين متطابقتين ممكن تكونوا مقصودين (دوريتين بنفس
    الاسم)، بس الأغلب ضغطة «حفظ» اتكررت. فالإضافة بتسأل الأول
    (`allow_duplicate`) بدل ما ترفض أو تقبل بصمت."""
    if row.get("officer_ids") or row.get("personnel_ids"):
        return None
    key = (norm(row.get("name", "")), norm(row.get("section", "")),
           row.get("kind") or "", row.get("shift") or "")
    for other in peek_day(data, day):
        if other.get("id") == row.get("id"):
            continue
        if other.get("officer_ids") or other.get("personnel_ids"):
            continue
        if (norm(other.get("name", "")), norm(other.get("section", "")),
                other.get("kind") or "", other.get("shift") or "") == key:
            return other.get("id")
    return None


def apply_assignment(data, day, row, payload):
    """بيطبّق حقول الطلب على صف التكليف. بترجع (row, error, status) —
    لو error مش None يبقى row=None."""
    if "name" in payload:
        name = str(payload["name"]).strip()
        if not name:
            return None, "اسم الخدمة مطلوب.", 400
        err = too_long(payload, "name")
        if err:
            return None, err, 400
        row["name"] = name
    if "kind" in payload:
        row["kind"] = clean_kind(payload["kind"])
    if "shift" in payload:
        row["shift"] = clean_shift(payload["shift"], row.get("kind", ""))
    if "section" in payload:
        err = too_long(payload, "section")
        if err:
            return None, err, 400
        section = str(payload["section"]).strip()
        if section in RESERVED_SECTIONS:
            return None, f"«{section}» اسم محجوز لقسم محسوب تلقائيًا — اختر اسمًا آخر.", 400
        row["section"] = section or SECTION_OCCASIONAL
    if "counts_in_summary" in payload:
        row["counts_in_summary"] = bool(payload["counts_in_summary"])
    if "mission_transport" in payload:
        row["mission_transport"] = bool(payload["mission_transport"])
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
        conscripts, err = clean_conscripts(payload["conscripts"])
        if err:
            return None, err, 400
        row["conscripts"] = conscripts
    if "conscript_count" in payload:
        count = parse_count(payload["conscript_count"])
        if count is None:
            return None, COUNT_ERROR, 400
        row["conscript_count"] = count
    for key in ("weapon", "party", "note"):
        if key in payload:
            err = too_long(payload, key)
            if err:
                return None, err, 400
            row[key] = str(payload[key]).strip()
    if "time" in payload:
        err = too_long(payload, "time")
        if err:
            return None, err, 400
        raw_time = str(payload["time"]).strip()
        if not raw_time:
            row["time"] = ""
        else:
            parsed_time = parse_time(raw_time)
            if parsed_time is None:
                # السطر القديم يفضل قابل للتعديل لو الوقت نفسه ما اتغيرش.
                if raw_time == row.get("time", ""):
                    pass
                else:
                    return None, "اختر معاد الانتظام من لوحة الساعة.", 400
            else:
                row["time"] = format_time(parsed_time)

    # أعلام الرئاسة: العلم الصريح بيغلب. إلغاؤه بيفضّي المعرّفات المقابلة،
    # وتحديد أشخاص من غير علم بيرفع العلم. صف قديم من غير أشخاص ولا علم
    # مابيتغيّرش شكله.
    for who, (flag, ids_key) in COMMAND_ROLES.items():
        if flag in payload:
            if not isinstance(payload[flag], bool):
                return None, "خيار الرئاسة يجب أن يكون نعم أو لا.", 400
            row[flag] = payload[flag]
            if not row[flag]:
                row[ids_key] = []
        elif row.get(ids_key):
            row[flag] = True

    if row.get("section") == SECTION_TARGETS:
        if row.get("name") not in set(targets_on(data, day)):
            return None, f"«{row.get('name')}» ليس من الأهداف الثابتة — قائمة الأهداف مغلقة.", 400
        row["kind"] = "حراسات"
        row["shift"] = ""
    if row.get("mission_transport") and row.get("kind") not in ("داخلية", "خارجية"):
        return None, "المأمورية / الترحيلة يجب أن يكون تصنيفها داخلية أو خارجية.", 400
    return row, None, None

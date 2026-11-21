"""بيانات «يومية التعيينات» — كشف الضباط وحالاتهم ليوم واحد.

الموديول ده عرض محسوب، زي يومية الضباط: التكليفات والحالات والراحات تفضل
مصادر الحقيقة الموجودة بالفعل، والجزء الوحيد المحفوظ خصيصًا للكشف هو أرقام
الذيل واختيار توقيع قسم العمليات.
"""
from copy import deepcopy
from datetime import date

from .board import target_rows_for_day
from .constants import REST_DURATIONS, ROLE_SEARCH, SHIFTS
from .dated import groups_on
from .day_open import needs_prepare, prepare
from .duty import summarise
from .labels import RANK_SHORT, personnel_rank_abbr
from .people import effective, officers_on
from .repo import PeopleRepo
from .signatures import signatories
from .store import load_data, revision
from .text import norm
from .utils import around, canonical_day

WEEKDAYS = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
DEFAULT_FOOTER_CATEGORIES = [
    {"label": "ضابط امن مركزي", "count": 4},
    {"label": "ضابط امن مواني", "count": 1},
]
DEFAULTS = {"central": 4, "ports": 1, "ops_signer_id": "",
            "excluded_officer_ids": [], "footer_categories": DEFAULT_FOOTER_CATEGORIES}


def _short_name(person):
    person = person or {}
    value = str(person.get("short_name") or "").strip()
    if value:
        return value
    return " ".join(str(person.get("name") or "").split()[:4])


def _roster_name(person):
    """الاسم القصير الذي تطبعه اليومية (اختصار الشخص ثم أول كلمتين)."""
    person = person or {}
    value = str(person.get("short_name") or "").strip()
    if value:
        return " ".join(value.replace("ـ", "").split())
    return " ".join(str(person.get("name") or "").replace("ـ", "").split()[:2])


def _full_name(person):
    """الاسم الكامل المنظّف للاستخدام الداخلي/التدقيق."""
    return " ".join(str((person or {}).get("name") or "").replace("ـ", "").split())


def _display_role(role, medical=False):
    value = str(role or "").strip()
    # بعض السجلات القديمة تحفظ الاختصار نفسه؛ لا نعيد كتابته بشكل مختلف.
    value = RANK_SHORT.get(value, value)
    if medical and value.endswith(" طبيب"):
        return value
    return f"{value} طبيب".strip() if medical else value


def _day_date(day):
    try:
        return date.fromisoformat(day)
    except (TypeError, ValueError):
        return None


def title_for(day):
    parsed = _day_date(day)
    if not parsed:
        return str(day or "")
    return (f"كشف بأسماء السادة الضباط عن يوم {WEEKDAYS[parsed.weekday()]} "
            f"الموافق {parsed.day}/{parsed.month}/{parsed.year}م")


def _rest_text(leave, day):
    leave = leave or {}
    raw = str(leave.get("raw_type") or leave.get("type") or "راحة").strip()
    if raw == "أسبوعية":
        return "راحة أسبوعية"
    if raw in ("شهرية", "نصف شهرية"):
        total = REST_DURATIONS.get(raw, 0)
        try:
            current = date.fromisoformat(day)
            start = date.fromisoformat(str(leave.get("start") or ""))
            end = date.fromisoformat(str(leave.get("end") or ""))
            number = (current - start).days + 1
            total = (end - start).days + 1 if end >= start else total
        except (TypeError, ValueError):
            number = ""
        suffix = f" ({number}/{total})" if number and total else ""
        return f"راحة {raw}{suffix}"
    label = str(leave.get("type") or raw or "راحة").strip()
    if label.startswith("إجازة"):
        return "اجازة" + label[len("إجازة"):]
    if label.startswith("اجازة"):
        return label
    return f"اجازة {label}"


def _shift_kind(value):
    """يرجع مفتاح الفترة من قيمة الفترة أو من اسم خدمة أرشيفية قديمة."""
    value = norm(str(value or "")).replace(" ", "")
    if value in {"صباحيه", "صباح", "صبح"}:
        return "morning"
    if value in {"ليليه", "ليل", "ليله"}:
        return "night"
    return ""


def _fast_intervention_shifts(row):
    def compact(value):
        # `norm` يوحّد الهمزات/الياء/التاء المربوطة ويزيل التطويل والتشكيل؛
        # إزالة أل التعريف والمسافات هنا تجعل «التدخل السريع» و«تدخل سريع»
        # والاسم الملحق بالفترة صورًا واحدة للمطابقة فقط، من غير تغيير النص
        # الذي يراه المشغّل.
        value = norm(str(value or "")).replace(" ", "")
        return value[2:] if value.startswith("ال") else value

    shifts = set()
    for service in row.get("services") or []:
        name = compact(service.get("name"))
        if "تدخل" not in name or "سريع" not in name:
            continue
        shift = _shift_kind(service.get("shift"))
        if not shift:
            if "صبح" in name or "صباح" in name:
                shift = "morning"
            elif "ليل" in name:
                shift = "night"
        if shift:
            shifts.add(shift)
    return shifts


def _fast_intervention(row):
    """هل في صف الضابط تكليف تدخل سريع، بغض النظر عن الفترة؟"""
    return any("تدخل" in (name := norm(str(service.get("name") or "")).replace(" ", ""))
               and "سريع" in name for service in row.get("services") or [])


def _intervention_status(row):
    shifts = _fast_intervention_shifts(row)
    if shifts == {"morning"}:
        return "تدخل صبح"
    if shifts == {"night"}:
        return "تدخل ليل"
    if shifts == {"morning", "night"}:
        return "تدخل صبح + ليل"
    return "تدخل"


def _external_service_name(service):
    """اسم الخدمة الخارجية كما يظهر في ملاحظة اليومية.

    الفترة حقل مستقل في التكليف، لكن بعض السجلات القديمة حفظت كلمة الفترة
    في نهاية الاسم نفسه. ننظف هذه اللاحقة فقط؛ لا نضيف فترة التكليف ولا
    نستخدم اسمًا من كتالوج مختلف عن الاسم المحفوظ في اليوم.
    """
    name = " ".join(str((service or {}).get("name") or "").split())
    for shift in SHIFTS:
        suffix = f" {shift}"
        if name.endswith(suffix):
            name = name[:-len(suffix)].rstrip()
            break
    return name


def external_service_names(row):
    """أسماء الخدمات الخارجية الفعلية، بترتيب تكليفات اليوم ومن غير تكرار."""
    names = []
    seen = set()
    for service in row.get("services") or []:
        if service.get("kind") != "خارجية" or not service.get("counted", True):
            continue
        name = _external_service_name(service)
        key = norm(name)
        if name and key and key not in seen:
            seen.add(key)
            names.append(name)
    return names


def _work_status_text(row):
    names = external_service_names(row)
    return f"عمل ({'، '.join(names)})" if names else "عمل"


def is_work_status(value):
    value = str(value or "").strip()
    return value == "عمل" or value.startswith("عمل (")


def is_intervention_status(value):
    return str(value or "").strip() in {
        "تدخل", "تدخل صبح", "تدخل ليل", "تدخل صبح + ليل",
    }


def status_text(row, day):
    """الحالة القصيرة المطلوبة في عمود «ملاحظات».

    الحالات الخارجة محفوظة قبل فحص «تدخل» عمدًا؛ فالتكليف القديم لا يجعل
    ضابطًا في راحة أو حالة ممتدة يظهر كأنه تدخل.
    """
    status = str(row.get("status") or "").strip()
    if status:
        if is_intervention_status(status) and _fast_intervention(row):
            return _intervention_status(row)
        return _work_status_text(row) if status == "عمل" else status
    if row.get("leave"):
        return _rest_text(row["leave"], day)
    if row.get("course") or (row.get("group"), row.get("bucket")) == ("خوارج", "فرقة"):
        return "فرقة"
    if row.get("medical_state") == "راحة":
        return "راحة"
    if row.get("medical_state") == "انتداب":
        return "انتداب"
    if _fast_intervention(row):
        return _intervention_status(row)
    # التقصيرة علامة على تشغيل الضابط، لا حالة خروج في الكشف.
    return _work_status_text(row)


def _current_officer_ids(data, day):
    """معرّفات القوة النشطة التي كانت على القوة في D.

    ``officers_on`` يحافظ عمدًا على الأرشيف لتعديل الأيام القديمة؛ اليومية
    الحالية لها قاعدة أضيق: لا تعرض أي سجل أرشيفي، حتى لو كان على القوة
    تاريخيًا، مع احترام تاريخي الانضمام والخروج.
    """
    active_ids = {person.id for person in PeopleRepo(data).active("officers")
                  if person.on_force(day)}
    return {person.get("id") for person in officers_on(data, day)
            if person.get("id") in active_ids}


def _operations_members(data, day):
    members = []
    for person in PeopleRepo(data).on_force(day, "personnel"):
        raw = person.as_dict() if hasattr(person, "as_dict") else dict(person)
        dated = {**raw, **effective(raw, day)}
        if "عمليات" not in norm(dated.get("post")):
            continue
        members.append({
            "id": raw.get("id", ""),
            # التوقيع بالاختصار (م.ش / ا.ش)؛ role الكامل للقائمة المنسدلة
            "rank": personnel_rank_abbr(dated.get("role") or raw.get("role") or ""),
            "role": dated.get("role") or raw.get("role") or "",
            "name": raw.get("name") or "",
            "short_name": _short_name(raw),
        })
    return members


def _stored_config(data, day):
    value = (data.get("day_roster") or {}).get(day) or {}
    excluded = value.get("excluded_officer_ids", [])
    if not isinstance(excluded, list):
        excluded = []
    excluded = list(dict.fromkeys(str(item).strip() for item in excluded if str(item).strip()))
    categories = value.get("footer_categories")
    if not isinstance(categories, list):
        # ترحيل شفاف من شكل Delta 4. لا نكتب الترحيل أثناء GET؛ أول حفظ
        # سيحوّله إلى القائمة الجديدة.
        categories = [
            {"label": "ضابط امن مركزي", "count": value.get("central", 4)},
            {"label": "ضابط امن مواني", "count": value.get("ports", 1)},
        ]
    clean_categories = []
    for item in categories[:8]:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        count = item.get("count", 0)
        if not label or isinstance(count, bool):
            continue
        try:
            count = int(count)
        except (TypeError, ValueError):
            continue
        if 0 <= count <= 999:
            clean_categories.append({"label": label[:60], "count": count})
    if "footer_categories" not in value and not clean_categories:
        clean_categories = deepcopy(DEFAULT_FOOTER_CATEGORIES)
    central = next((item["count"] for item in clean_categories
                    if item["label"] == "ضابط امن مركزي"), 0)
    ports = next((item["count"] for item in clean_categories
                  if item["label"] == "ضابط امن مواني"), 0)
    return {
        "central": central,
        "ports": ports,
        "footer_categories": clean_categories,
        "ops_signer_id": str(value.get("ops_signer_id") or ""),
        "excluded_officer_ids": excluded,
    }


def store_config(data, day, value):
    """يحفظ إعدادات الكشف من خلال موديول المجال، لا من مسار HTTP."""
    excluded = value.get("excluded_officer_ids", [])
    if not isinstance(excluded, list):
        excluded = []
    categories = value.get("footer_categories")
    if not isinstance(categories, list):
        categories = [
            {"label": "ضابط امن مركزي", "count": value.get("central", 4)},
            {"label": "ضابط امن مواني", "count": value.get("ports", 1)},
        ]
    cleaned_categories = [
            {"label": str(item.get("label") or "").strip(),
             "count": int(item.get("count", 0))}
            for item in categories if isinstance(item, dict)
        ]
    data.setdefault("day_roster", {})[day] = {
        "footer_categories": cleaned_categories,
        # يظل المفتاحان القديمان مقروءين للأدوات/النسخ القديمة؛ القائمة هي
        # مصدر الحقيقة الجديد، وهما مجرد إسقاط لأول تصنيفين معروفين.
        "central": next((item["count"] for item in cleaned_categories
                          if item["label"] == "ضابط امن مركزي"), 0),
        "ports": next((item["count"] for item in cleaned_categories
                        if item["label"] == "ضابط امن مواني"), 0),
        "ops_signer_id": str(value.get("ops_signer_id") or ""),
        "excluded_officer_ids": list(dict.fromkeys(
            str(item).strip() for item in excluded if str(item).strip()
        )),
    }


def _target_operation_text(text):
    """تشغيل الهدف فقط من نص يومية الضباط، بدون الإضافات اليدوية بعده.

    «عمل بهدف سوميد حتى 4م + متابعة أعمال الشؤون الإدارية» ← يبقى
    «عمل بهدف سوميد حتى 4م». أي خدمة قبل الهدف (مثل خدمة خارجية) تبقى،
    وكل ما بعد آخر جزء هدف يُحذف.
    """
    parts = [part.strip() for part in str(text or "").split(" + ") if part.strip()]
    last = -1
    for index, part in enumerate(parts):
        if part.startswith("عمل بهدف") or part.startswith("متابعة اعمال الاهداف"):
            last = index
    if last < 0:
        return " + ".join(parts)
    return " + ".join(parts[:last + 1])


def _target_context(data, day, current_ids):
    lines = []
    target_ids = set()
    split_target_ids = set()
    seen_ids = set()
    search_ids = set(groups_on(data, day).get(ROLE_SEARCH) or [])
    for target in target_rows_for_day(data, day):
        people = []
        for person in target.get("officers") or []:
            if person.get("id") not in current_ids or person.get("id") in search_ids:
                continue
            target_ids.add(person.get("id"))
            people.append(person)
        periods = target.get("periods") or []
        split = len(periods) == 2 and all(
            period.get("officer_id") in {person.get("id") for person in people}
            for period in periods
        )
        split_lines = []
        officer_lines = []
        if split:
            split_target_ids.update(person.get("id") for person in people)
        for person in people:
            person_id = person.get("id")
            if person_id in seen_ids:
                continue
            seen_ids.add(person_id)
            role = _display_role(person.get("role"))
            line = f"{role} / {_roster_name(person)}".strip(" /")
            officer_lines.append(line)
            if split:
                split_lines.append(line)
        lines.append({
            "target": str(target.get("name") or ""),
            "names": [_roster_name(person) for person in people],
            "officer_ids": [person.get("id") for person in people],
            "split": split,
            "officer_lines": officer_lines,
            "split_lines": split_lines,
        })
    return lines, target_ids, split_target_ids


def _target_lines(data, day):
    """التوافق القديم: يرجع كل الضباط المعيّنين بالأهداف."""
    lines, _target_ids, _split_ids = _target_context(data, day, _current_officer_ids(data, day))
    return [line for target in lines for line in target.get("officer_lines") or []]


def selectable_officer_ids(data, day):
    """معرّفات الضباط الذين يظهرون في لوحة الاختيار لهذا اليوم."""
    current_ids = _current_officer_ids(data, day)
    _target_lines_value, target_ids, _split_ids = _target_context(data, day, current_ids)
    search_ids = set(groups_on(data, day).get(ROLE_SEARCH) or [])
    return [row["id"] for row in summarise(data, day).get("rows") or []
            if row.get("id") in current_ids and row.get("id") not in search_ids
            and not row.get("medical")
            and row.get("id") not in target_ids
            and is_work_status(status_text(row, day))]


def build(data, day):
    """يبني الـpayload المشترك بين صفحة المعاينة وملف Word."""
    current_ids = _current_officer_ids(data, day)
    summary = summarise(data, day)
    targets, target_ids, split_target_ids = _target_context(data, day, current_ids)
    search_ids = set(groups_on(data, day).get(ROLE_SEARCH) or [])
    normal, target_items, doctors = [], [], []
    summary_items = {}
    for row in summary.get("rows") or []:
        if row.get("id") not in current_ids or row.get("id") in search_ids:
            continue
        item = {
            "id": row.get("id", ""),
            "name": _roster_name(row),
            "full_name": _full_name(row),
            "role": _display_role(row.get("role"), medical=bool(row.get("medical"))),
            "status": status_text(row, day),
            "medical": bool(row.get("medical")),
        }
        summary_items[item["id"]] = (row, item)
        is_target = row.get("id") in target_ids
        if is_target:
            # «نص التشغيل» في يومية الضباط هو مصدر الحقيقة الوحيد للنص
            # الكامل: فيه اسم الهدف، وفترة التغطية (زمنية أو نصية)، وأي
            # تشغيل إضافي. لا نعيد بناء صيغة «عمل بهدف» هنا حتى تظل كتلة
            # الأهداف مطابقة لليومية الأخرى حرفيًا.
            # الحالات الخارجة المكتوبة (مثل «غياب») تظل صاحبة الأولوية؛
            # المطلوب هنا استبدال «عمل» المختصرة فقط بنص التشغيل الكامل.
            if is_work_status(item["status"]):
                item["status"] = _target_operation_text(row.get("text")) or item["status"]
            # كل ضابط مكلّف بهدف يذهب إلى صف عادي تحت عنوان الأهداف؛ القادة
            # المحسوبون للهدف لا يدخلون هنا لأنهم لا يظهرون في officers.
            continue
        elif item["medical"]:
            # العيادة تعرض العاملين فقط. الطبيب الخارج لا يتحول إلى صف
            # عادي، ولا يُحتسب في الإجمالي.
            if is_work_status(item["status"]):
                doctors.append(item)
        else:
            # الخوارج لا يظهرون في كشف التعيينات. الاستثناء الوحيد هو
            # «تقصيرة»، وهي علامة عمل وليست خروجًا. والأهداف تجمع في كتلة
            # الأهداف، حتى لو وصفتها بيانات اليوم بحالة خارجة.
            is_taqseera = (row.get("group"), row.get("bucket")) == ("خوارج", "تقصيرة")
            if (not is_target
                    and not is_taqseera
                    and ((row.get("group") == "خوارج"
                          and not is_work_status(item["status"]))
                         or (not is_work_status(item["status"])
                             and not is_intervention_status(item["status"])))):
                continue
            if not is_target:
                normal.append(item)

    # target_rows_for_day يحافظ على ترتيب خانات الأهداف، بينما summarise
    # يحافظ على ترتيب القوة. نستخدم الأول للكتلة حتى لا تختلط الخانات.
    target_order = []
    seen_target_order = set()
    for target in targets:
        for person_id in target.get("officer_ids") or []:
            if person_id not in seen_target_order:
                seen_target_order.add(person_id)
                target_order.append(person_id)
    for person_id in target_order:
        pair = summary_items.get(person_id)
        if pair is not None:
            target_items.append(pair[1])
    # ضباط الأهداف بترتيب الأقدمية (نفس ترتيب القوة في اليومية) مش بترتيب
    # خانات الأهداف، عشان الترقيم يمشي بالرتبة: رائد ما ييجيش بعد م.أول.
    force_order = {row.get("id"): index for index, row in enumerate(summary.get("rows") or [])}
    target_items.sort(key=lambda item: force_order.get(item["id"], len(force_order)))

    stored = _stored_config(data, day)
    excluded_ids = set(stored["excluded_officer_ids"])
    # لم تعد أسماء الأهداف نصًا داخل الخلية المدمجة؛ تبقى البيانات كصفوف
    # عادية تحت خلية العنوان، ويُترك المفتاح القديم فارغًا للتوافق.
    target_lines = []
    all_rows = [item for item in normal] + target_items + doctors
    selectable = [item for item in normal if is_work_status(item["status"])]
    normal = [item for item in normal
              if not is_work_status(item["status"]) or item["id"] not in excluded_ids]

    visible_items = normal + target_items + doctors
    work_count = sum(is_work_status(item["status"]) for item in visible_items)
    intervention_count = sum(is_intervention_status(item["status"])
                             for item in visible_items)

    # قالب الأرشيف ليس نصفين متساويين: النصف المرئي الأيمن يحمل أول 23
    # صفًا، والنصف الأيسر يواصل من 24 إلى 31 قبل الذيل والعيادة.
    right = normal[:23]
    left = normal[23:31]
    for index, row in enumerate(right, 1):
        row["number"] = index
    for index, row in enumerate(left, len(right) + 1):
        row["number"] = index

    members = _operations_members(data, day)
    stored_section = (data.get("day_roster") or {}).get(day) or {}
    has_saved_signer = "ops_signer_id" in stored_section
    member_ids = {item["id"] for item in members}
    signer_id = stored["ops_signer_id"] if stored["ops_signer_id"] in member_ids else ""
    if not signer_id and members and not has_saved_signer:
        signer_id = members[0]["id"]
    signer = next((item for item in members if item["id"] == signer_id), None)
    chief = signatories(data, day).get("operations") or {"rank": "رائد", "name": "محمد بحر"}

    return {
        "date": day,
        "title": title_for(day),
        "rows": normal + doctors,
        # الضباط المقسّمون ظاهرون داخل كتلة الأهداف، لا داخل نصفي الجدول؛
        # لذلك يدخلون في الإجمالي مرة واحدة من غير إعادتهم إلى القائمة.
        "total": (len(normal) + len(doctors) + len(target_items)
                  + sum(item["count"] for item in stored["footer_categories"])),
        "all_rows": all_rows,
        "left": left,
        "right": right,
        "overflow": normal[31:],
        "doctors": doctors,
        "target_items": target_items,
        "targets": targets,
        "target_lines": target_lines,
        "target_officer_lines": target_lines,
        "central": stored["central"],
        "ports": stored["ports"],
        "footer_categories": stored["footer_categories"],
        "footer_total": sum(item["count"] for item in stored["footer_categories"]),
        "weekday": WEEKDAYS[_day_date(day).weekday()] if _day_date(day) else "",
        "counts": {
            "total": (len(normal) + len(doctors) + len(target_items)
                      + sum(item["count"] for item in stored["footer_categories"])),
            "work": work_count,
            "intervention": intervention_count,
        },
        "config": {**stored, "ops_signer_id": signer_id},
        "excluded_officer_ids": stored["excluded_officer_ids"],
        "selection": {
            "total": len(selectable),
            "selected": sum(item["id"] not in excluded_ids for item in selectable),
            "selected_ids": [item["id"] for item in selectable
                             if item["id"] not in excluded_ids],
            "excluded_ids": stored["excluded_officer_ids"],
        },
        "selectable_officers": [
            {**item, "selected": item["id"] not in excluded_ids}
            for item in selectable
        ],
        "target_officer_ids": sorted(target_ids),
        "split_target_officer_ids": sorted(split_target_ids),
        "operations_members": members,
        "ops_signer": signer,
        "chief": chief,
        "signatories": {
            "operations": signer or {"rank": "", "name": ""},
            "operations_chief": chief,
        },
    }


def prepare_view(day):
    """لقطة اليوم المستخدمة في GET والتصدير، بنفس نطاق اليوميات الأخرى."""
    day = canonical_day(day)
    if not day:
        return None, None, None
    data = load_data(around(day, -1, 0))
    preview = deepcopy(data)
    if needs_prepare(data, day, include_inspections=True):
        prepare(preview, day, include_inspections=True)
    return data, preview, build(preview, day)


def current_revision(day):
    """بصمة نطاق القراءة الحقيقي، بعد أي معاينة على نسخة تجهيز منفصلة."""
    return revision(load_data(around(day, -1, 0)), [day])


def view(data, day):
    """يبني payload route مع revision من نفس اللقطة المحملة."""
    payload = build(data, day)
    payload["revision"] = revision(data, [day])
    return payload

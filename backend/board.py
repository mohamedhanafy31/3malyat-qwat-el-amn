"""اليومية التفصيلية (اللوحة) — **عرض محسوب** على نفس تكليفات اليوم.

التقسيمة هنا مأخوذة من الوورد حرفيًا بعد فحص 101 لوحة: عشرة أقسام بترتيب
ثابت، ستة منهم فيهم خدمات مخزّنة وأربعة **محسوبين** من حالة الضباط.

    1. الخدمات أساسية      خدمات   — الفترة بتتكتب جوّه الاسم («تدخل سريع صبح»)
    2. الخدمات الطارئة     خدمات   — أغلبها بدون ضابط: قوام أفراد ومجندين
    3. عمل بالإدارة        محسوب   — الضباط بلا تكليف خدمي + نص عملهم
    4. الأهداف             قايمة مغلقة — مشرف الأهداف + سبعة أهداف ثابتة، كل
                            واحد بقائده (من منصب الضابط) والمعيّن فيه فعليًا
    5. الراحات             محسوب
    6. التقصيرات           محسوب
    7. الخوارج             محسوب
    8. ضابط عظيم وأمن المعسكر الفرعي   كتلة ثابتة: صف صباحية + صف ليلية
    9. ضابط عظيم الإدارة               كتلة ثابتة
   10. ضابط الأمن بالإدارة             كتلة ثابتة

الكتل الثابتة (8-10) بتظهر بصفّيها دايمًا حتى لو شاغرة — الوورد بيطبع
الصفين في كل يوم، والخانة الفاضية معناها «محتاجة تكليف» مش «مش موجودة».
"""
from .assignments import forget_seq_if_day_empty, label, officer_states, peek_day
from .checks import day_warnings
from .confirm import state_of as confirm_state
from .constants import (
    BOARD_ROTATIONS, SECTION_ADMIN_WORK, SECTION_BASIC, SECTION_GREAT,
    SECTION_OCCASIONAL, SECTION_OUTSIDERS, SECTION_PRISON, SECTION_RESTS, SECTION_SECURITY,
    SECTION_SUBCAMP, SECTION_TAQSEERA, SECTION_TARGETS, SHIFTS, SUBCAMP_SERVICES,
    TARGET_NAMES, TARGETS_FIRST, ROLE_MEDICAL,
)
from .duty import summarise
from .dated import groups_on, targets_on
from .people import effective
from .text import norm

# ترتيب API القديم محفوظ للتوافق؛ ترتيب العرض الجديد موجود في layout_columns.
BOARD_ORDER = [
    SECTION_BASIC, SECTION_OCCASIONAL, SECTION_ADMIN_WORK, SECTION_TARGETS,
    SECTION_RESTS, SECTION_TAQSEERA, SECTION_OUTSIDERS,
    SECTION_SUBCAMP, SECTION_GREAT, SECTION_SECURITY,
]

# الأقسام اللي فيها خدمات مخزّنة (الباقي محسوب من حالة الضباط)
ASSIGNMENT_SECTIONS = [SECTION_BASIC, SECTION_OCCASIONAL, SECTION_TARGETS,
                       SECTION_PRISON, SECTION_SUBCAMP, SECTION_GREAT, SECTION_SECURITY]

# الكتل اللي ليها صفّان ثابتان (صباحية/ليلية) بيتطبعوا حتى لو فاضيين
FIXED_SLOT_SECTIONS = [SECTION_SUBCAMP, SECTION_GREAT, SECTION_SECURITY]

# الأقسام الحرة اللي المشغّل يضيف جواها خدمات من مودال الخانة العام. الأهداف
# والكتل الثابتة ليهم واجهاتهم المقفولة، والأقسام المحسوبة مالهاش صفوف خدمات
# محفوظة أصلًا؛ عشان كده ماينفعش يظهروا كاقتراح لإضافة خانة حرة.
FREE_SERVICE_SECTIONS = [SECTION_BASIC, SECTION_OCCASIONAL, SECTION_PRISON]
NON_FREE_SECTIONS = {
    SECTION_TARGETS, *FIXED_SLOT_SECTIONS,
    SECTION_ADMIN_WORK, SECTION_RESTS, SECTION_TAQSEERA, SECTION_OUTSIDERS,
}

# تعريف الخدمة اللي يتنقل بين الأيام. القائمون بها مستبعدين عمدًا: الأشخاص
# تكليف يومي، إنما الحقول دي هي قالب الخدمة نفسه.
SECTION_COPY_FIELDS = (
    "name", "kind", "section", "shift", "weapon", "time",
    "party", "conscripts", "conscript_count", "note", "counts_in_summary",
)
_SECTION_COPY_DEFAULTS = {
    "name": "", "kind": "", "section": "", "shift": "",
    "weapon": "", "time": "", "party": "", "conscripts": [], "conscript_count": 0,
    "note": "", "counts_in_summary": True,
}


def section_names(data):
    """اقتراحات أقسام الخدمات من كل الأيام المسجّلة.

    الرسمية الحرة ثابتة في الأول، وبعدها المخصّصة حسب أحدث يوم استُخدمت
    فيه. الأيام المحمّلة بتتقرا من ``day_assignments``، والباقي من فهرس
    أقسام اللوحة في المخزن — من غير تحميل الأرشيف.
    """
    from .store import board_section_days

    latest = {}
    first_seen = {}
    seen_seq = 0
    prison_seen = False
    for day, names in board_section_days(data):
        for raw_name in names:
            name = canonical_section_name(raw_name)
            if name == SECTION_PRISON and day >= "2026-09-26":
                prison_seen = True
            if not name or name in FREE_SERVICE_SECTIONS or name in NON_FREE_SECTIONS:
                continue
            if name not in first_seen:
                first_seen[name] = seen_seq
                seen_seq += 1
            if day > latest.get(name, ""):
                latest[name] = day

    custom = sorted(latest, key=lambda name: (latest[name], -first_seen[name]), reverse=True)
    # The prison block became an official suggestion only with the Word
    # template introduced on 26 Sep 2026; do not leak it into older boards.
    official = [SECTION_BASIC, SECTION_OCCASIONAL]
    if prison_seen:
        official.append(SECTION_PRISON)
    return [*official, *custom]


SECTION_ALIASES = {
    "خدمات السجن": SECTION_PRISON,
    "خدمات سجن قوات الامن": SECTION_PRISON,
    "خدمات سجن قوات الأمن": SECTION_PRISON,
    "فرد تأمين فترة ليلة": SECTION_PRISON,
    "فرد تأمين فترة ليلية": SECTION_PRISON,
    "فرد تامين فتره ليله": SECTION_PRISON,
    "فرد تامين فتره ليليه": SECTION_PRISON,
}


def canonical_section_name(value):
    """Return the supported display name for historical prison-section aliases."""
    raw = str(value or "").strip()
    return SECTION_ALIASES.get(raw, raw)


def _copyable_row(row):
    """نسخة JSON مستقلة من تعريف الخدمة، من غير أي شخص مكلّف عليها."""
    out = {"id": row.get("id")}
    for key in SECTION_COPY_FIELDS:
        value = row.get(key, _SECTION_COPY_DEFAULTS[key])
        if value is None:
            value = _SECTION_COPY_DEFAULTS[key]
        if key == "conscripts":
            value = [dict(item) for item in (value or []) if isinstance(item, dict)]
        out[key] = value
    return out


def section_source(board_sections, day, section):
    """يوم المصدر لقسم من [(يوم, أسماء أقسامه)]: الأسبق أولًا، وإلا أحدث يوم آخر."""
    section = str(section or "").strip()
    if not section or section in NON_FREE_SECTIONS:
        return None
    earlier_day = None
    other_day = None
    for candidate_day, names in board_sections:
        names = [canonical_section_name(value) for value in names]
        if candidate_day == day or section not in names:
            continue
        if candidate_day < day and (earlier_day is None or candidate_day > earlier_day):
            earlier_day = candidate_day
        if other_day is None or candidate_day > other_day:
            other_day = candidate_day
    return earlier_day or other_day


def section_history(data, day, section):
    """آخر يوم آخر فيه صفوف للقسم: الأسبق أولًا، وإلا أحدث يوم آخر."""
    from .store import board_section_days

    section = str(section or "").strip()
    if not section or section in NON_FREE_SECTIONS:
        return {"section": section, "source_day": None, "rows": []}

    source_day = section_source(board_section_days(data), day, section)
    by_day = data.get("day_assignments") or {}
    rows = [] if not source_day else [
        _copyable_row(row) for row in by_day[source_day]
        if str(row.get("section") or SECTION_OCCASIONAL).strip() == section
    ]
    return {"section": section, "source_day": source_day, "rows": rows}


def copy_section_rows(data, day, section, source_day, ids):
    """ينسخ تعريفات خدمات مختارة إلى يوم جديد، ويرجع (النتيجة، الخطأ، الحالة)."""
    from .assignments import blank, for_day, new_id

    section = str(section or "").strip()
    if not section:
        return None, "اسم القسم مطلوب.", 400
    if section in NON_FREE_SECTIONS:
        return None, f"لـ«{section}» واجهة مخصّصة، وليس قسم خدمات حرًا.", 400
    if source_day == day:
        return None, "يجب أن يختلف يوم المصدر عن يوم اللوحة.", 400
    if not isinstance(ids, list) or not ids:
        return None, "اختر خدمة واحدة على الأقل للنسخ.", 400
    if any(not isinstance(item, str) or not item.strip() for item in ids):
        return None, "معرّفات الخدمات غير صحيحة.", 400

    by_day = data.get("day_assignments") or {}
    if source_day not in by_day:
        return None, "يوم المصدر غير موجود.", 404

    wanted = list(dict.fromkeys(item.strip() for item in ids))
    source_rows = [row for row in by_day[source_day]
                   if str(row.get("section") or SECTION_OCCASIONAL).strip() == section
                   and row.get("id") in wanted]
    found = {row.get("id") for row in source_rows}
    missing = [item for item in wanted if item not in found]
    if missing:
        return None, "خدمة مختارة غير موجودة في يوم المصدر والقسم المحددين.", 404

    entries = for_day(data, day)
    existing = {
        (norm(row.get("name", "")), row.get("shift") or "")
        for row in entries if str(row.get("section") or SECTION_OCCASIONAL).strip() == section
    }
    added = []
    skipped = 0
    for source in source_rows:
        duplicate_key = (norm(source.get("name", "")), source.get("shift") or "")
        if duplicate_key in existing:
            skipped += 1
            continue
        row = blank(new_id(data, day, entries), source.get("name", ""), section)
        copied = _copyable_row(source)
        for key in SECTION_COPY_FIELDS:
            row[key] = copied[key]
        row["section"] = section
        entries.append(row)
        added.append(row)
        existing.add(duplicate_key)

    return {"added": len(added), "skipped": skipped, "rows": added}, None, None


def target_row_names(data=None, day=None):
    """كل أسماء صفوف الأهداف بترتيبها الثابت — «مشرف الأهداف» أولًا."""
    return targets_on(data, day) if data is not None and day else [TARGETS_FIRST, *TARGET_NAMES]


def _people_index(data):
    from .repo import PeopleRepo

    people = PeopleRepo(data)
    return {p["id"]: p for cat in ("officers", "personnel")
            for p in people.raw_all(cat)}


def _person(people, person_id, day):
    p = people.get(person_id)
    if not p:
        return {"id": person_id, "name": "", "role": "", "missing": True}
    eff = effective(p, day)
    return {"id": person_id, "name": p.get("name", ""), "role": eff["role"]}


def _roster(data, day):
    """الضباط والأفراد اللي كانوا على القوة في اليوم ده — نفس القيد اللي
    الحفظ بيفرضه على الضباط بالظبط (`assignments.clean_people` بينده
    `officers_on`)، عشان قايمة الاختيار في مودال الخانة تطابق اللي
    هيتقبل فعلًا. ضابط اتأرشف بعد اليوم ده بيفضل ظاهر — كان على القوة
    وقتها، وده اللي بيخلّي تعديل يوم قديم يشتغل.

    قبل كده مودال الخانة كان بيعرض **كل** ضابط اتسجّل في السيستم يومًا
    (بيانات ثابتة من `bootstrap`، مش محسوبة لليوم)، فأي ضابط خرج من
    القوة كان لسه ظاهر في قايمة الاختيار لأي يوم — حتى النهاردة.

    اللي عنده راحة/إجازة مسجّلة تغطي اليوم ده مش معروض هنا — مايتعيّنش
    خدمة جديدة وهو في الخوارج. لو كان معيّن فعلًا على خدمة قبل ما راحته
    تتسجّل، بيفضل ظاهر في مودال التعديل بتاعه بس (`withCurrent` في
    board.js)، مش في نتيجة البحث لتعيين جديد.
    """
    from .leaves import leave_on
    from .repo import PeopleRepo, Repos

    repo = PeopleRepo(data)
    medical_ids = set(groups_on(data, day).get(ROLE_MEDICAL) or [])

    def slim(person):
        role = person.effective(day)["role"] if hasattr(person, "effective") else person.role
        return {"id": person.id, "name": person.name, "role": role}

    def not_on_leave(person):
        return not leave_on(data, person.id, day)

    return {"officers": [slim(o) for o in repo.on_force(day, "officers")
                         if o.id not in medical_ids and not_on_leave(o)],
            "personnel": [slim(p) for p in repo.on_force(day, "personnel") if not_on_leave(p)]}


def _row(assignment, people, day):
    """صف واحد على اللوحة. الخانة الشاغرة (بلا ضباط) صف مشروع مش نقص —
    1,034 صف خدمات طارئة في الأرشيف قوامها أفراد ومجندين من غير ضابط."""
    officers = [_person(people, oid, day) for oid in assignment.get("officer_ids") or []]
    personnel = [_person(people, pid, day) for pid in assignment.get("personnel_ids") or []]
    return {
        "id": assignment["id"],
        "name": assignment.get("name", ""),
        "kind": assignment.get("kind", ""),
        "section": canonical_section_name(assignment.get("section", "")),
        "label": assignment.get("source_label") or label(
            assignment, with_shift=assignment.get("section") == SECTION_BASIC),
        "source_manning": assignment.get("source_manning", ""),
        "shift": assignment.get("shift", ""),
        "officers": officers,
        "personnel": personnel,
        "conscripts": assignment.get("conscripts") or [],
        "conscript_count": int(assignment.get("conscript_count") or 0),
        "weapon": assignment.get("weapon", ""),
        "time": assignment.get("time", ""),
        "party": assignment.get("party", ""),
        "note": assignment.get("note", ""),
        "pos": assignment.get("pos") if isinstance(assignment.get("pos"), int)
        and not isinstance(assignment.get("pos"), bool) else None,
        "vacant": not officers and not personnel,
    }


# البادئة اللي منصب قائد الهدف الثابت بيتكتب بيها دايمًا («قائد هدف سوميد»)
_COMMANDER_PREFIX = "قائد هدف"

# «مشرف الأهداف» صف مختلف عن باقي السبعة: مالوش منصب «قائد هدف مشرف
# الأهداف» أصلًا — المسئول عنه هو رئيس قسم الحراسات المشددة نفسه (كل
# الأهداف تبع الحراسات المشددة أصلًا)، فمنصبه مكتوب كامل من غير بادئة
# «قائد هدف».
_TARGETS_SUPERVISOR_POST = "رئيس قسم الحراسات المشددة"


def _officers_on_force(data, day):
    """الضباط اللي كانوا فعلًا على القوة في اليوم ده — مش أي ضابط اتسجّل
    يومًا في السيستم. قادة الأهداف بتتاخد من الضباط الحاليين بس، عشان
    ضابط اتأرشف زمان ومنصبه القديم لسه متسجّل بالصدفة زي «قائد هدف
    سوميد» ما يظهرش قائد لهدف هو مالوش أي علاقة بيه فعليًا النهاردة."""
    from .repo import PeopleRepo

    return PeopleRepo(data).raw_on_force(day, "officers")


def _target_commanders(officers, name, day):
    """قائد الهدف العام — خانة ثابتة، مش تكليف يومي. بتتحدد من منصب
    الضابط **الفعّال في اليوم ده** (`effective`) لا الحالي، عشان لوحة
    قديمة تفضل تطبع القائد اللي كان وقتها لو المنصب اتغيّر بعد كده.

    القائد ممكن يكون **مختلف** عن الضابط المعيّن بالهدف فعليًا النهاردة —
    الأرشيف فيه أيام كتير حد بيغطي هدف مش قائده الأصلي (يوم 2/6: هدف
    «أنابيب البترول» غطّاه قائد هدف «هلة المحجر»). الخانتين مقصود يتعرضوا
    منفصلين مش مدموجين.

    `officers` هنا الضباط اللي على القوة في اليوم ده بس (`_officers_on_force`)
    — مش كل ضابط اتسجّل في السيستم يومًا، عشان ضابط متأرشف قبل كده بكتير
    ما يظهرش قائد لهدف من غير علاقة فعلية باليوم ده.

    بترجّع قايمة — ممكن تطلع أكتر من واحد لو المنصب اتكرر بالغلط على
    ضابطين (الأرشيف فيه حالة كده لهدف «عيون موسي» ولرئيس قسم الحراسات
    المشددة نفسه)، وده بيتعرض زي ما هو بدل ما نختار واحد عشوائي ونخبي الغلط.
    """
    from .text import norm

    if name == TARGETS_FIRST:
        needle, prefix = norm(_TARGETS_SUPERVISOR_POST), ""
    else:
        needle, prefix = norm(name), norm(_COMMANDER_PREFIX)

    out = []
    for p in officers:
        post = norm(effective(p, day).get("post", ""))
        if post.startswith(prefix) and post[len(prefix):].strip() == needle:
            out.append({"id": p["id"], "name": p.get("name", ""),
                        "role": effective(p, day)["role"]})
    return out


def _blank_target(name, day, officers):
    """صف هدف من غير أي حد معيّن فيه — القائد بيفضل محسوب حتى لو مفيش
    تكليف مسجّل خالص، عشان القايمة الثابتة تبان كاملة من أول يوم."""
    return {
        "id": None, "name": name, "kind": "حراسات", "section": SECTION_TARGETS,
        "label": name, "shift": "",
        "officers": [], "personnel": [], "conscripts": [], "conscript_count": 0,
        "weapon": "", "time": "", "party": "", "note": "",
        "commander": _target_commanders(officers, name, day),
        "vacant": True, "placeholder": True,
    }


def _target_slots(rows, officers, day, data=None):
    """صف ثابت لكل هدف من الثمانية (مشرف الأهداف + سبعة أهداف)، بترتيب
    ثابت، بيظهر كل يوم حتى لو محدش لسه عيّن حد فيه — عكس باقي الأقسام،
    الأهداف قايمة مغلقة مالهاش «+ إضافة» حر.
    """
    by_name = {}
    for r in rows:
        if r["name"] in by_name:
            # صفين بنفس اسم الهدف في نفس اليوم (بيانات مش متوقعة) — بيتجمّعوا
            # في صف واحد بدل ما واحد منهم يضيع بصمت من الـdict comprehension.
            prev = by_name[r["name"]]
            prev["officers"] = prev["officers"] + r["officers"]
            prev["personnel"] = prev["personnel"] + r["personnel"]
            prev["vacant"] = prev["vacant"] and r["vacant"]
        else:
            by_name[r["name"]] = r
    out = []
    for name in target_row_names(data, day):
        row = by_name.pop(name, None)
        if row:
            row["commander"] = _target_commanders(officers, name, day)
            out.append(row)
        else:
            out.append(_blank_target(name, day, officers))
    # هدف اتكتب قبل كده برّه القايمة المغلقة (ملوش وجود في الأرشيف، بس
    # القاعدة العامة هنا هي «مفيش بيانات بتختفي بصمت») بيتعرض في الآخر
    for row in by_name.values():
        row["commander"] = _target_commanders(officers, row["name"], day)
        out.append(row)
    return out


def target_rows_for_day(data, day):
    """صفوف الأهداف الثمانية ليوم واحد بس — نفس مخرجات قسم الأهداف على
    اللوحة، بس من غير باقي التسعة أقسام. `build_board()` مكلّف زيادة عن
    اللزوم لما محتاج الأهداف بس (زي إحصائيات التشغيل اللي بتلفّ على
    عشرات الأيام)."""
    people = _people_index(data)
    rows = [_row(a, people, day) for a in peek_day(data, day)
            if a.get("section") == SECTION_TARGETS]
    return _target_slots(rows, _officers_on_force(data, day), day, data)


def set_target_officers(data, day, name, officer_ids):
    """بيعيّن (أو يشيل) الضابط المعيّن بهدف من الأهداف الثابتة الثمانية.

    القائد خانة ثابتة محسوبة من منصب الضابط (`_target_commanders`) —
    بيتغيّر من صفحة بيانات الضابط مش من هنا. اللي بيتحدد هنا هو مين
    شغّال في الهدف فعليًا النهاردة بس.

    التعيين الفاضي بيشيل الصف بالكامل من `day_assignments` بدل ما يسيبه
    فاضي بلا فايدة — هدف من غير حد معيّن أصلًا بيتعرض كخانة شاغرة من
    القايمة الثابتة، مش محتاج سجل مخزّن.

    بترجّع (row, error, status).
    """
    from .assignments import blank, clean_people, for_day, new_id

    if name not in target_row_names(data, day):
        return None, f"«{name}» ليس من الأهداف الثابتة — قائمة الأهداف مغلقة.", 400

    ids, err, status = clean_people(data, day, officer_ids, "officers")
    if err:
        return None, err, status

    entries = for_day(data, day)
    row = next((r for r in entries if r.get("section") == SECTION_TARGETS
               and r.get("name") == name), None)

    if not ids:
        if row:
            entries.remove(row)
            forget_seq_if_day_empty(data, day)
        return None, None, None

    if not row:
        row = blank(new_id(data, day, entries), name, SECTION_TARGETS, kind="حراسات")
        entries.append(row)
    row["officer_ids"] = ids
    return row, None, None


# الاسم الثابت لكل قسم من الكتل التلاتة — مش اسم حر زي باقي الخدمات،
# نفس مبدأ الأهداف بالظبط بس هنا اسم واحد لكل قسم مش قايمة. مستخرج من
# الأرشيف: `SUBCAMP_SERVICES[0]`/`BOARD_ROTATIONS` هما الاسمين اللي
# فعليًا اتكتبوا على صفوف الكتل دي في كل الأيام المفحوصة.
FIXED_SLOT_NAMES = {
    SECTION_SUBCAMP: SUBCAMP_SERVICES[0],
    SECTION_GREAT: BOARD_ROTATIONS[0],
    SECTION_SECURITY: BOARD_ROTATIONS[1],
}


def set_slot_officers(data, day, section, shift, officer_ids):
    """بيعيّن (أو يشيل) الضابط في خانة فترة معيّنة من كتلة ثابتة (ضابط
    عظيم الإدارة/الأمن/المعسكر الفرعي) — نفس فكرة `set_target_officers`
    بالظبط، بس المفتاح هنا (قسم، فترة) مش اسم، لأن كل قسم من التلاتة
    اسمه واحد ثابت (`FIXED_SLOT_NAMES`) بيتكرر على صفّين (صباحية/ليلية).

    التعيين الفاضي بيشيل الصف بالكامل بدل ما يسيبه فاضي بلا فايدة —
    الخانة الشاغرة بتتعرض من `_fixed_slots` تلقائيًا زي أي فترة فاضية.

    بترجّع (row, error, status).
    """
    from .assignments import blank, clean_people, for_day, new_id

    name = FIXED_SLOT_NAMES.get(section)
    if not name:
        return None, f"«{section}» ليس من الأقسام الثابتة.", 400
    if shift not in SHIFTS:
        return None, "الفترة غير صحيحة.", 400

    ids, err, status = clean_people(data, day, officer_ids, "officers")
    if err:
        return None, err, status

    entries = for_day(data, day)
    row = next((r for r in entries
               if r.get("section") == section and r.get("shift") == shift), None)

    if not ids:
        if row:
            entries.remove(row)
            forget_seq_if_day_empty(data, day)
        return None, None, None

    if not row:
        # المعسكر الفرعي مالوش خانة في جدول الإجمالي (README) — الضابط
        # بيفضل في الصافي حتى وهو نوبتجي، عكس الاتنين التانيين.
        row = blank(new_id(data, day, entries), name, section, shift=shift, kind="داخلية",
                    counts_in_summary=(section != SECTION_SUBCAMP))
        entries.append(row)
    row["officer_ids"] = ids
    return row, None, None


def _fixed_slots(rows, canonical_name):
    """الكتلة الثابتة: صف لكل فترة بالاسم الثابت (`slot: True` — ده اللي
    زرار «تعيين» السريع بيتحكم فيه)، بالصف الموجود أو خانة شاغرة.

    القسم **مش** قايمة مقفولة زي الأهداف — لو المشغّل ضاف دور تاني في
    نفس القسم بإيده من «＋ إضافة» (زي منصب فرعي تاني للمعسكر الفرعي)،
    الصف ده بيتحط بعد الصفّين الثابتين (`slot: False`) وبيتعرض بجدول
    خدمات عادي تحتهم — عشان الدور ده يفضل **جوّه** قسمه الصح، مش يضطر
    المشغّل يكتبه في قسم تاني (زي «الخدمات الطارئة») علشان مفيش مكان
    يضيفه فيه هنا.
    """
    out = []
    primary_objects = set()
    for shift in SHIFTS:
        match = [r for r in rows if r["shift"] == shift]
        primary = next((r for r in match if r.get("name") == canonical_name), None)
        if primary:
            out.append({**primary, "slot": True})
            primary_objects.add(id(primary))
        else:
            out.append({"id": None, "name": "", "kind": "", "label": "", "shift": shift,
                        "officers": [], "personnel": [], "conscripts": [], "conscript_count": 0,
                        "weapon": "", "time": "", "party": "", "note": "",
                        "vacant": True, "placeholder": True, "slot": True})
    # الأدوار الإضافية بتتعرض كقايمة خدمات واحدة بعد الصفّين الثابتين؛
    # ترتيبها المحفوظ للعرض لازم يغلب تجميعها حسب الفترة، وإلا نقل خدمة
    # ليل قبل خدمة صباح مستحيل حتى لو `pos` اتغيّر صح.
    out.extend({**r, "slot": False} for r in rows if id(r) not in primary_objects)
    return out


def _display_key(row, source_order):
    """ترتيب اللوحة فقط؛ عدم وجود `pos` يرجّع ترتيب التخزين الأصلي."""
    pos = row.get("pos")
    if not isinstance(pos, int) or isinstance(pos, bool):
        pos = source_order
    return pos, source_order


def _visible_list_ids(data, day, stored):
    """معرّفات القايمة اللي الصف بيتعرض جواها فعلًا على اللوحة."""
    board = build_board(data, day)
    section_name = canonical_section_name(stored.get("section") or SECTION_OCCASIONAL)
    section = next((item for item in board["sections"] if item["name"] == section_name), None)
    if not section or section["type"] not in ("services", "slots"):
        return None

    if section["type"] == "slots":
        shown = [row for row in section["rows"] if not row.get("slot")]
    else:
        shown = section["rows"]
    return [row.get("id") for row in shown]


def _renumber_display_positions(entries, ids):
    """يثبّت ترتيب قايمة ظاهرة في `pos` من غير تحريك قايمة التخزين."""
    by_id = {row.get("id"): row for row in entries}
    for pos, row_id in enumerate(ids):
        by_id[row_id]["pos"] = pos


def place_assignment_after(data, day, assignment_id, after_id):
    """يحط الصف بعد صف مرجعي لو الاتنين في نفس القايمة الظاهرة.

    المرجع الغلط أو الموجود في قسم تاني بيتساب من غير خطأ؛ الصف
    الجديد يفضل في آخر قائمته زي الإضافة العادية.
    """
    entries = peek_day(data, day)
    stored = next((row for row in entries if row.get("id") == assignment_id), None)
    if not stored or not after_id or after_id == assignment_id:
        return
    ids = _visible_list_ids(data, day, stored)
    if not ids or assignment_id not in ids or after_id not in ids:
        return

    ids.remove(assignment_id)
    ids.insert(ids.index(after_id) + 1, assignment_id)
    _renumber_display_positions(entries, ids)


def move_assignment(data, day, assignment_id, direction):
    """ينقل خدمة خطوة داخل القايمة اللي بتظهر فيها، من غير تحريك التخزين.

    `day_assignments` نفسها ليها معنى تشغيلي في يومية الضباط: أول خدمة
    اتحط عليها الضابط هي خانته في الإجمالي. عشان كده بنبدّل `pos` للعرض
    فقط، وما بنعملش `remove/insert` في القايمة الأصلية أبدًا.
    """
    entries = peek_day(data, day)
    stored = next((row for row in entries if row.get("id") == assignment_id), None)
    if not stored:
        return "التكليف غير موجود.", 404

    ids = _visible_list_ids(data, day, stored)
    if ids is None:
        return "ترتيب هذه الخدمة ثابت ولا يتغير.", 400
    if assignment_id not in ids:
        return "هذه الخدمة ليست ضمن قائمة قابلة للترتيب.", 400
    index = ids.index(assignment_id)
    neighbour = index - 1 if direction == "up" else index + 1
    if neighbour < 0 or neighbour >= len(ids):
        return None, None

    # بنطبّع مواضع القايمة الظاهرة قبل التبديل؛ كده الصفوف القديمة اللي
    # مالهاش `pos` والصفوف الجديدة تفضل قابلة للحركة من غير تعادل مبهم.
    _renumber_display_positions(entries, ids)
    by_id = {row.get("id"): row for row in entries}
    by_id[ids[index]]["pos"], by_id[ids[neighbour]]["pos"] = neighbour, index
    return None, None


def build_board(data, day):
    from .repo import Repos

    people = _people_index(data)
    states = officer_states(data, day)
    medical_ids = set(groups_on(data, day).get(ROLE_MEDICAL) or [])

    by_section = {name: [] for name in ASSIGNMENT_SECTIONS}
    for source_order, a in enumerate(peek_day(data, day)):
        section = canonical_section_name(a.get("section") or SECTION_OCCASIONAL)
        row = _row(a, people, day)
        row["_source_order"] = source_order
        by_section.setdefault(section, []).append(row)
    # الفرز هنا على نسخة العرض فقط. `_source_order` متغير داخلي بيتشال
    # قبل بناء الاستجابة، وقايمة التكليفات الأصلية ما بتتلمسش.
    for rows in by_section.values():
        rows.sort(key=lambda row: _display_key(row, row["_source_order"]))
        for row in rows:
            row.pop("_source_order", None)
    # الأهداف قايمة مغلقة بترتيب ثابت — عكس باقي الأقسام، بتظهر بصفوفها
    # الثمانية كل يوم حتى لو محدش لسه عيّن حد فيها، ومعاها قائد كل هدف
    # (خانة ثابتة محسوبة من منصب الضابط، منفصلة عن `officers` على نفس
    # الصف اللي هو الضابط المعيّن بالهدف فعليًا النهاردة)
    target_commanders = [o for o in _officers_on_force(data, day)
                         if o["id"] not in medical_ids]
    by_section[SECTION_TARGETS] = _target_slots(
        by_section[SECTION_TARGETS], target_commanders, day, data)

    full = summarise(data, day)
    rests, taqseeras, outsiders, admin_work = [], [], [], []
    for r in full["rows"]:
        # ضباط العيادة ليهم عرضهم وحسابهم في يومية الضباط، إنما اليومية
        # التفصيلية ما بتسردهمش في أقسام الضباط المحسوبة حتى لو حالة مكتوبة
        # نقلتهم من «طبية» إلى «الخوارج». صف خدمة محفوظ يفضل ظاهر فوق عادي.
        if r["id"] in medical_ids:
            continue
        who = {"id": r["id"], "name": r["name"], "role": r["role"]}
        if r["group"] == "خوارج":
            if r["bucket"] == "تقصيرة":
                taqseeras.append({**who, "note": r["note"]})
            elif r["bucket"] == "راحة":
                lv = r["leave"] or {}
                rests.append({**who, "type": (r["leave"] or {}).get("type", "راحة"),
                              "start": lv.get("start"), "end": lv.get("end"),
                              "return_date": lv.get("return_date"), "note": r["note"]})
            else:
                outsiders.append({**who, "reason": (r["leave"] or {}).get("type") or r["bucket"],
                                  "note": r["note"]})
        elif r["group"] == "صافي":
            admin_work.append({**who, "text": r["note"] or r["post"]})

    computed = {
        SECTION_ADMIN_WORK: admin_work,
        SECTION_RESTS: rests,
        SECTION_TAQSEERA: taqseeras,
        SECTION_OUTSIDERS: outsiders,
    }

    sections = []
    for name in BOARD_ORDER:
        if name in computed:
            sections.append({"name": name, "type": "officers", "rows": computed[name]})
            continue
        rows = by_section.get(name, [])
        if name == SECTION_TARGETS:
            # قايمة مغلقة بترتيب ثابت — بلا «+ إضافة» حر
            from .target_defaults import untouched_seed

            seeded = untouched_seed(data, day)
            section = {"name": name, "type": "targets", "rows": rows}
            if seeded:
                section["seeded_from"] = seeded["source_day"]
            sections.append(section)
            continue
        if name in FIXED_SLOT_SECTIONS:
            sections.append({"name": name, "type": "slots",
                             "rows": _fixed_slots(rows, FIXED_SLOT_NAMES.get(name))})
            continue
        sections.append({"name": name, "type": "services", "rows": rows})

    # أي قسم اتكتب بالإيد ومش من العشرة بيتعرض في الآخر بدل ما يختفي —
    # زي «خدمات مباراة المصري» ليوم فيه مباراة، لليوم ده بس من غير أي
    # تسجيل مسبق لاسم القسم في أي مكان.
    extra = [n for n in by_section if n not in BOARD_ORDER and by_section[n]]
    for name in extra:
        sections.append({"name": name, "type": "services", "rows": by_section[name]})

    layout_version = "word-2026-09-26" if day >= "2026-09-26" else "word-legacy"
    return {"date": day, "layout_version": layout_version,
            "layout_columns": {
                "right": [SECTION_BASIC, SECTION_TARGETS, SECTION_SUBCAMP, SECTION_ADMIN_WORK],
                "left": [SECTION_OCCASIONAL, SECTION_PRISON, SECTION_OUTSIDERS],
            }, "sections": sections,
            "confirm": confirm_state(data, day),
            "roster": _roster(data, day),
            # الرسمية الحرة الأول، وبعدها كل اسم مخصّص ظهر في أي يوم حسب
            # أحدث استعمال — عشان القسم اللي اتعمل امبارح يفضل متاح النهاردة.
            "section_names": section_names(data),
            "warnings": day_warnings(data, day, full["rows"])}

"""اليومية التفصيلية (اللوحة) — **عرض محسوب** على نفس تكليفات اليوم.

التقسيمة هنا مأخوذة من الوورد حرفيًا بعد فحص 101 لوحة: عشرة أقسام بترتيب
ثابت، ستة منهم فيهم خدمات مخزّنة وأربعة **محسوبين** من حالة الضباط.

    1. الخدمات أساسية      خدمات   — الفترة بتتكتب جوّه الاسم («تدخل سريع صبح»)
    2. الخدمات الطارئة     خدمات   — أغلبها بدون ضابط: قوام أفراد ومجندين
    3. عمل بالإدارة        محسوب   — الضباط بلا تكليف خدمي + نص عملهم
    4. الأهداف             خدمات   — أسماء مختصرة، «مشرف الأهداف» أولًا، بلا فترة
    5. الراحات             محسوب
    6. التقصيرات           محسوب
    7. الخوارج             محسوب
    8. ضابط عظيم وأمن المعسكر الفرعي   كتلة ثابتة: صف صباحية + صف ليلية
    9. ضابط عظيم الإدارة               كتلة ثابتة
   10. ضابط الأمن بالإدارة             كتلة ثابتة

الكتل الثابتة (8-10) بتظهر بصفّيها دايمًا حتى لو شاغرة — الوورد بيطبع
الصفين في كل يوم، والخانة الفاضية معناها «محتاجة تكليف» مش «مش موجودة».

الخدمات الموسومة (مباراة، خطة انتشار) بتفضل **جوّه** قسمها مع عنوان
فرعي، زي «خطة انتشار 6م» في لوحة 15/6 — مش في جريد منفصل.
"""
from .assignments import label, officer_states, peek_day, services_by_id
from .constants import (
    SECTION_BASIC, SECTION_GREAT, SECTION_OCCASIONAL, SECTION_SECURITY,
    SECTION_SUBCAMP, SECTION_TARGETS, SHIFTS,
)
from .duty import summarise
from .people import effective

SECTION_ADMIN_WORK = "عمل بالإدارة"
SECTION_RESTS = "الراحات"
SECTION_TAQSEERA = "التقصيرات"
SECTION_OUTSIDERS = "الخوارج"

# الترتيب زي الوورد. العمود اليمين: أساسية → طارئة → عمل بالإدارة،
# والشمال: الأهداف → الراحات → التقصيرات → الخوارج → الكتل الثلاثة.
BOARD_ORDER = [
    SECTION_BASIC, SECTION_OCCASIONAL, SECTION_ADMIN_WORK, SECTION_TARGETS,
    SECTION_RESTS, SECTION_TAQSEERA, SECTION_OUTSIDERS,
    SECTION_SUBCAMP, SECTION_GREAT, SECTION_SECURITY,
]

# الأقسام اللي فيها خدمات مخزّنة (الباقي محسوب من حالة الضباط)
ASSIGNMENT_SECTIONS = [SECTION_BASIC, SECTION_OCCASIONAL, SECTION_TARGETS,
                       SECTION_SUBCAMP, SECTION_GREAT, SECTION_SECURITY]

# الكتل اللي ليها صفّان ثابتان (صباحية/ليلية) بيتطبعوا حتى لو فاضيين
FIXED_SLOT_SECTIONS = [SECTION_SUBCAMP, SECTION_GREAT, SECTION_SECURITY]

# «مشرف الأهداف» أول صف في قسم الأهداف في كل يوم من الـ101
TARGETS_FIRST = "مشرف الأهداف"


def _people_index(data):
    out = {}
    for cat in ("officers", "personnel"):
        for bucket in ("active", "archive"):
            for p in data.get(cat, {}).get(bucket, []):
                out[p["id"]] = p
    return out


def _person(people, person_id, day):
    p = people.get(person_id)
    if not p:
        return {"id": person_id, "name": "", "role": "", "missing": True}
    eff = effective(p, day)
    return {"id": person_id, "name": p.get("name", ""), "role": eff["role"]}


def _row(assignment, svc, people, day):
    """صف واحد على اللوحة. الخانة الشاغرة (بلا ضباط) صف مشروع مش نقص —
    1,034 صف خدمات طارئة في الأرشيف قوامها أفراد ومجندين من غير ضابط."""
    officers = [_person(people, oid, day) for oid in assignment.get("officer_ids") or []]
    personnel = [_person(people, pid, day) for pid in assignment.get("personnel_ids") or []]
    return {
        "id": assignment["id"],
        "service_id": assignment.get("service_id"),
        "label": label(assignment, svc, with_shift=assignment.get("section") == SECTION_BASIC),
        "shift": assignment.get("shift", ""),
        "officers": officers,
        "personnel": personnel,
        "conscripts": assignment.get("conscripts") or [],
        "weapon": assignment.get("weapon") or (svc or {}).get("default_weapon", ""),
        "time": assignment.get("time") or (svc or {}).get("default_time", ""),
        "party": assignment.get("party") or (svc or {}).get("party", ""),
        "note": assignment.get("note", ""),
        "tags": assignment.get("tags") or [],
        "vacant": not officers and not personnel,
    }


def _target_key(row):
    """«مشرف الأهداف» أولًا، والباقي بترتيب إدخاله."""
    return (0 if row["label"].startswith(TARGETS_FIRST) else 1,)


def _fixed_slots(rows):
    """الكتلة الثابتة: صف لكل فترة، بالصف الموجود أو خانة شاغرة."""
    out = []
    for shift in SHIFTS:
        match = [r for r in rows if r["shift"] == shift]
        if match:
            out.extend(match)
        else:
            out.append({"id": None, "service_id": None, "label": "", "shift": shift,
                        "officers": [], "personnel": [], "conscripts": [],
                        "weapon": "", "time": "", "party": "", "note": "",
                        "tags": [], "vacant": True, "placeholder": True})
    # صفوف بلا فترة (لو حد حطها كده) بتتعرض بعد الصفّين الثابتين
    out.extend(r for r in rows if r["shift"] not in SHIFTS)
    return out


def _grouped(rows):
    """الخدمات الموسومة بتتجمّع تحت عنوان فرعي جوّه القسم، زي «خطة انتشار
    6م» في لوحة 15/6 — الوورد بيسيبها في مكانها مش في جريد لوحده."""
    plain = [r for r in rows if not r["tags"]]
    groups = {}
    for r in rows:
        for tag in r["tags"]:
            groups.setdefault(tag, []).append(r)
    return plain, [{"tag": t, "rows": rs} for t, rs in groups.items()]


def build_board(data, day):
    services = services_by_id(data)
    people = _people_index(data)
    states = officer_states(data, day)

    by_section = {name: [] for name in ASSIGNMENT_SECTIONS}
    for a in peek_day(data, day):
        svc = services.get(a.get("service_id"))
        section = a.get("section") or (svc or {}).get("section") or SECTION_OCCASIONAL
        by_section.setdefault(section, []).append(_row(a, svc, people, day))
    by_section[SECTION_TARGETS].sort(key=_target_key)

    full = summarise(data, day)
    rests, taqseeras, outsiders, admin_work = [], [], [], []
    for r in full["rows"]:
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
            sections.append({"name": name, "type": "officers",
                             "rows": computed[name], "groups": []})
            continue
        rows = by_section.get(name, [])
        if name in FIXED_SLOT_SECTIONS:
            sections.append({"name": name, "type": "slots",
                             "rows": _fixed_slots(rows), "groups": []})
            continue
        plain, groups = _grouped(rows)
        sections.append({"name": name, "type": "services", "rows": plain, "groups": groups})

    # أي قسم اتكتب بالإيد ومش من العشرة بيتعرض في الآخر بدل ما يختفي
    extra = [n for n in by_section if n not in BOARD_ORDER and by_section[n]]
    for name in extra:
        plain, groups = _grouped(by_section[name])
        sections.append({"name": name, "type": "services", "rows": plain, "groups": groups})

    return {"date": day, "sections": sections, "states": states}

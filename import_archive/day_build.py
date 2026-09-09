#!/usr/bin/env python3
"""بناء تكليفات اليوم من مصدرين: لوحة اليوم ويومية الضباط.

اللوحة (`D.docx`) هي اللي فيها **كل** صفوف اليوم — بما فيها الـ1,034 صف
خدمات طارئة قوامها أفراد ومجندين من غير ضابط. ويومية الضباط
(`D-M-2026.docx`) بتدّي حالة كل ضابط (تقصيرة/راحة/انتداب/…) والتكليفات
اللي مش ظاهرة على اللوحة.

الدمج بيتم بالخدمة والفترة: لو الضابط ظاهر في اليوميتين على نفس الخدمة
بتفضل خانة واحدة.
"""
import re

from board_read import (
    conscripts, individuals_count, is_vacant, party, person_entries, time_of, weapon,
)
from common import strip_ar
from services import status_of

BOARD_SECTIONS = {
    "الخدمات اساسيه": "الخدمات أساسية",
    "بالخدمات اساسيه": "الخدمات أساسية",
    "الخدمات الطاريه": "الخدمات الطارئة",
    "الاهداف": "الأهداف",
    # قسم ظرفي بعنوان مستقل وتحته صفوفه (لوحة 20/8)
    "خدمات سجن قوات الامن": "الخدمات الطارئة",
}
# الأقسام المحسوبة — بتتقري من حالة الضباط مش من صفوف مخزّنة
COMPUTED_HEADERS = ("عمل بالاداره", "الخوارج", "التقصيرات", "الراحات")
FIXED_BLOCKS = {
    "ضابط عظيم وامن المعسكر الفرعي": "ضابط عظيم وأمن المعسكر الفرعي",
    "ضابط عظيم الاداره": "ضابط عظيم الإدارة",
    "ضابط الامن بالاداره": "ضابط الأمن بالإدارة",
}
SHIFT_ROW = {"فتره صباحيه": "صباحية", "فتره ليليه": "ليلية"}
RANKS = ("عقيد", "مقدم", "رائد", "نقيب", "م.اول", "م.أول", "ملازم", "لواء", "عميد")

_SHIFT_IN_NAME = [(r'\bصبح\b|\bصباحيه\b', "صباحية"), (r'\bليل\b|\bليليه\b', "ليلية")]
# ساعة الانتظام هي اللي بتحدد الفترة لما الاسم مايقولهاش — وده حال أغلب
# الخدمات الطارئة («ترحيلة بدر 7ص»، «ارتكاز المسجد الكبير 5م»). من غير
# القراءة دي كان 47% من التكليفات بيقعوا على «صباحية» افتراضيًا.
_TIME_SHIFT = re.compile(r'(\d{1,2})(?::\d{2})?\s*(ص|م|ظ)\b')


def shift_from_time(text):
    """«7ص» و«12ظ» صباحية، و«5م» و«8م» ليلية."""
    m = _TIME_SHIFT.search(text or "")
    if not m:
        return ""
    return "ليلية" if m.group(2) == "م" else "صباحية"


def shift_in_name(text, *fallback):
    flat = strip_ar(text or "")
    for pattern, shift in _SHIFT_IN_NAME:
        if re.search(pattern, flat):
            return shift
    for source in (text, *fallback):
        shift = shift_from_time(source)
        if shift:
            return shift
    return ""


def read_board(table):
    """-> [{section, raw_name, manning, shift}] لكل صف خدمة على اللوحة."""
    rows, section = [], None
    for row in table or []:
        first = (row[0] if row else "").strip()
        second = (row[1] if len(row) > 1 else "").strip()
        flat = strip_ar(first)

        if flat in BOARD_SECTIONS:
            section = BOARD_SECTIONS[flat]
            continue
        if flat in FIXED_BLOCKS:
            section = FIXED_BLOCKS[flat]
            continue
        if any(flat.startswith(h) for h in COMPUTED_HEADERS):
            section = None
            continue
        if not section or not first:
            continue

        # جوّه الكتل الثابتة الصف بيكون «فترة صباحية | الضابط»
        if section in FIXED_BLOCKS.values():
            shift = SHIFT_ROW.get(flat)
            if not shift:
                continue
            rows.append({"section": section, "raw_name": "", "manning": second,
                         "shift": shift})
            continue

        # صف اسمه ضابط ومحتواه الخدمة (بيحصل في بعض الأيام) — نقلبهم
        name, manning = first, second
        if any(r in first for r in RANKS) and "/" in first:
            name, manning = second, first
        rows.append({"section": section, "raw_name": name, "manning": manning,
                     "shift": shift_in_name(name, manning)})
    return rows


def officer_state(row):
    """حالة الضابط من نص تشغيله — تقصيرة والحالات الست."""
    duty = row.get("duty", "")
    state = {}
    if "تقصير" in strip_ar(duty):
        state["taqseera"] = True
    status = status_of(duty, row.get("post", ""))
    if status:
        state["status"] = status
    if duty.strip():
        state["note"] = duty.strip()
    return state


def search_attached(post):
    """مصدر وسم «+N بحث» في جدول الإجمالي — منصب الضابط مش نوع الخدمة.

    الأدلة من الأرشيف على رئيس مباحث الإدارة:
      20/8  منصبه «رئيس مباحث الإدارة»، وتشغيله «ضابط مباحث السجن
            العسكري» (خدمة داخلية) → الوورد حسبه **داخلية** بدون أي وسم
      25/8  نفس المنصب، وتشغيله «كنترول الثانوية العامة» (خارجية)
            → الوورد كتب **+1 بحث**
      1/9   المنصب اتكتب «(تشغيل من ادارة البحث)» صراحةً، خارجية → +1 بحث

    يعني الوسم تابع للمنصب، وبيظهر بس لما يكون على خدمة خارجية — الجملة
    الأخيرة دي في backend/duty.py مش هنا.
    """
    flat = strip_ar(post or "")
    return "مباحث الاداره" in flat or "اداره البحث" in flat


def build_day(board_table, officer_rows, resolve, officer_id_of, personnel_id_of):
    """-> (assignments, officer_states)

    `resolve(raw_name)` بترجّع خدمة من الكتالوج أو None،
    و`officer_id_of(name)` / `personnel_id_of(name)` بيرجّعوا أيدي.
    """
    assignments, states, unresolved = [], {}, []
    seen = {}                       # (service_id, shift) -> index في assignments

    def slot(service, shift, section):
        key = (service["id"], shift)
        if key in seen:
            return assignments[seen[key]]
        # صف اللوحة ساعات مابيقولش الفترة («تسفير الأزهر») بينما نص تشغيل
        # الضابط بيقولها («تسفير الازهر 7ص») — لازم يبقوا صف واحد، وإلا
        # الضابط بيتحسب على خدمتين وأرقام الإجمالي بتتضاعف
        if shift:
            blank_key = (service["id"], "")
            if blank_key in seen:
                row = assignments[seen[blank_key]]
                row["shift"] = shift
                del seen[blank_key]
                seen[key] = assignments.index(row)
                return row
        elif any(k[0] == service["id"] for k in seen):
            existing = next(k for k in seen if k[0] == service["id"])
            return assignments[seen[existing]]
        row = {"section": section, "service_id": service["id"], "shift": shift,
               "officer_ids": [], "personnel_ids": [], "conscripts": [],
               "weapon": "", "time": "", "party": "", "label_override": "",
               "tags": [], "note": ""}
        seen[key] = len(assignments)
        assignments.append(row)
        return row

    # ---- 1) صفوف اللوحة: هي اللي فيها الخدمات بدون ضابط ----
    for entry in read_board(board_table):
        raw, manning = entry["raw_name"], entry["manning"]
        service = resolve(raw) if raw else None
        if raw and not service:
            unresolved.append(raw)
            continue
        if not service:
            continue                # كتلة ثابتة بدون خدمة معروفة

        row = slot(service, entry["shift"], entry["section"])
        if is_vacant(manning):
            continue
        for kind, _rank, name in person_entries(manning):
            pid = officer_id_of(name) if kind == "officer" else personnel_id_of(name)
            if pid and pid not in row["officer_ids"] + row["personnel_ids"]:
                row["officer_ids" if kind == "officer" else "personnel_ids"].append(pid)
        row["conscripts"] = conscripts(manning) or row["conscripts"]
        row["weapon"] = row["weapon"] or weapon(manning)
        row["time"] = row["time"] or time_of(raw, manning)
        row["party"] = row["party"] or party(raw) or party(manning)
        individuals = individuals_count(manning)
        if individuals and not row["personnel_ids"]:
            row["conscripts"].append({"class": "فرد", "count": individuals})

    # ---- 2) يومية الضباط: الحالة + أي تكليف مش ظاهر على اللوحة ----
    for row in officer_rows:
        oid = officer_id_of(row["name"])
        if not oid:
            continue
        state = officer_state(row)
        if state:
            states[oid] = state
        for service, shift in row.get("services", []):
            target = slot(service, shift, service.get("section") or "الخدمات الطارئة")
            if oid not in target["officer_ids"]:
                target["officer_ids"].append(oid)

    for i, row in enumerate(assignments, 1):
        row["id"] = f"AS-{i:04d}"
    return assignments, states, unresolved


def fixed_block_service(section, catalog_by_section):
    """الكتل الثابتة بتشاور على خدمة واحدة معروفة."""
    return catalog_by_section.get(section)

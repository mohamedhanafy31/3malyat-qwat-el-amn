"""يومية الأفراد — نفس ورقة «افراد» الحقيقية اللي بتتكتب بالإيد كل يوم:
جزء «الخدمات الأساسية» قايمة مقفولة (نفس أسماءها وترتيبها بالظبط في
`22-6-2026 افراد.docx` — 22 خدمة، مش دليل الخدمات العام اللي ممكن
يتغيّر أو يبقى فاضي)، وجزء «الخدمات الطارئة» بياخد صفوفه مباشرة من قسم
«الخدمات الطارئة» في اليومية التفصيلية — نفس مبدأ `counts.py` بالظبط
(مفيش سجل مستقل للطوارئ، رقم واحد في مكان واحد).

القائم بها/تليفونه صباحًا وليلًا، وقوام الخدمة، والتسليح، ومعاد الانتظام
—كلهم بيتغيّروا يوميًا فعلًا في الأرشيف الحقيقي (اتفحص يومين مختلفين)،
فكلهم حقول قابلة للتعديل ليوم بعينه، مش قيم ثابتة.

أي قسم مخصّص المشغّل كتبه بإيده على اللوحة (زي «خدمات انتشار» أو «خدمات
مباراة») بينضم لنفس جدول الطوارئ هنا تحت — عين `counts.py` بالظبط.
"""
import re

from .assignments import peek_day
from .board import ASSIGNMENT_SECTIONS, _people_index, _row
from .constants import SECTION_OCCASIONAL
from .dated import afraad_basic_on
from .repo import PeopleRepo
from .text import norm_name

# نفس أسماء وترتيب الخدمات الأساسية الـ22 في `22-6-2026 افراد.docx`
# بالظبط — قايمة مقفولة، مش حرة زي دليل الخدمات العام. «كمين 109» في
# الأصل صفّين بنفس الاسم وقوام تاني (بيك اب/مدرعة)، فبانفصلوا هنا باسمين
# مميّزين عشان يبقى كل صف له هوية واحدة واضحة.
BASIC_SERVICE_NAMES = [
    "مدرعة المديرية",
    "خط الغاز",
    "التدخل سريع",
    "القول المكبر",
    "ميكروباص الأمن الوطني",
    "ارتكاز الأمن الوطني",
    "تأمين فرع الأمن الوطني بالسخنة",
    "كمين 109 - بيك اب",
    "كمين 109 - مدرعة",
    "اعلي كمين 109",
    "كنيسة ماري جرجس الصباح",
    "القنصلية السعودية",
    "استراحة القنصل السعودي",
    'المحاجر "قول 42 لاسلكى"',
    'محور 1 "قول 16 لاسلكي"',
    'محور 2 "قول 18 لاسلكى"',
    "قول 48 لاسلكى",
    "قول 50 لاسلكى",
    "الإسعاف",
    "ارتكاز سوميد",
    "ارتكاز قسم فيصل الجديد",
    "كمين شرق النفق المستحدث",
]
BASIC_SERVICES = [{"id": f"AFB-{i:02d}", "name": name} for i, name in enumerate(BASIC_SERVICE_NAMES, 1)]

def _overrides(data, day):
    return data.setdefault("day_afraad", {}).setdefault(day, {})


_CARRY_FIELDS = ("count", "weapon", "schedule")


def _previous_overrides(data, day):
    previous = [value for value in (data.get("day_afraad") or {}) if value < day]
    if not previous:
        return "", {}
    source_day = max(previous)
    return source_day, (data.get("day_afraad") or {}).get(source_day) or {}


def _slot(data, values, shift):
    person_id = values.get(f"{shift}_person_id", "")
    phone = values.get(f"{shift}_phone", "")
    if person_id:
        raw, category, _bucket = PeopleRepo(data).locate(person_id)
        if raw is not None and category == "personnel":
            # رقم سجل الفرد هو مصدر الحقيقة؛ تعديل الرقم في صفحة القوة
            # ينعكس فورًا على كل اليوميات المرتبطة به.
            phone = raw.get("phone") or phone
    result = {"name": values.get(f"{shift}_name", ""), "phone": phone}
    if person_id:
        result["person_id"] = person_id
    return result


def basic_rows(data, day):
    """صفوف الخدمات الأساسية الـ22 الثابتة — كل حاجة فيها (القائم بها/
    التليفون/القوام/التسليح/الانتظام) بتيجي من نسخة اليوم ده بس."""
    overrides = (data.get("day_afraad") or {}).get(day) or {}
    previous_day, previous = _previous_overrides(data, day)
    rows = []
    for entry in afraad_basic_on(data, day):
        ov = overrides.get(entry["id"], {})
        old = previous.get(entry["id"], {})
        inherited = [field for field in _CARRY_FIELDS if field not in ov and old.get(field)]
        morning = _slot(data, ov, "morning")
        night = _slot(data, ov, "night")
        rows.append({
            "id": entry["id"], "name": entry["name"],
            "count": ov.get("count", old.get("count", "")),
            "weapon": ov.get("weapon", old.get("weapon", "")),
            "morning": morning, "night": night,
            "schedule": ov.get("schedule", old.get("schedule", "")),
            "inherited_from": previous_day if inherited else "",
            "inherited_fields": inherited,
        })
    return rows


_EDITABLE_FIELDS = ("morning_name", "morning_phone", "night_name", "night_phone",
                    "morning_person_id", "night_person_id", "count", "weapon", "schedule")


def set_basic_entry(data, day, entry_id, payload):
    """بيحفظ تفاصيل خدمة أساسية ليوم واحد — بترجع (entry, error, status)."""
    if entry_id not in {e["id"] for e in afraad_basic_on(data, day)}:
        return None, "هذه الخدمة ليست من الخدمات الأساسية الثابتة.", 404
    ov = _overrides(data, day).setdefault(entry_id, {})
    people = PeopleRepo(data)
    payload = dict(payload)
    for shift in ("morning", "night"):
        id_key, name_key, phone_key = (f"{shift}_person_id", f"{shift}_name",
                                       f"{shift}_phone")
        if id_key in payload:
            person_id = str(payload[id_key] or "").strip()
            raw, category, _bucket = people.locate(person_id) if person_id else (None, None, None)
            if person_id and (raw is None or category != "personnel"):
                return None, "معرّف الفرد غير موجود.", 400
            if person_id:
                payload[name_key] = (str(payload.get(name_key) or "").strip()
                                     or f"{raw.get('role', '')}/ {raw.get('name', '')}".strip("/ "))
                payload[phone_key] = raw.get("phone") or ""
        elif name_key in payload and str(payload[name_key] or "").strip() != ov.get(name_key, ""):
            # تغيير النص يلغي الرابط القديم حتى لا ينسب اسمًا جديدًا لشخص آخر.
            ov.pop(id_key, None)
            typed = str(payload[name_key] or "").split("/")[-1].strip()
            matches = [person for person in people.on_force(day, "personnel")
                       if norm_name(person.name) == norm_name(typed)] if typed else []
            if len(matches) == 1:
                payload[id_key] = matches[0].id
                payload[phone_key] = matches[0].phone or ""
    for key in _EDITABLE_FIELDS:
        if key in payload:
            ov[key] = str(payload[key] or "").strip()[:200]
    return ov, None, None


_TIME_RE = re.compile(r"(\d{1,2})\s*(ص|ظ|م)?")


def _time_key(text):
    """معاد الانتظام حر الكتابة تمامًا («8ص»، «12ظ»، «11 ص حتى الانتهاء»)
    — مفتاح ترتيب تقريبي بيدوّر على أول رقم وبادئة ص/ظ/م بعده، مش تحليل
    وقت رسمي. اللي مالوش رقم واضح بيتحط في آخر الجدول بدل ما يوقف الترتيب."""
    m = _TIME_RE.search(text or "")
    if not m:
        return 24 * 60
    hour, suffix = int(m.group(1)), m.group(2) or ""
    if suffix == "ظ":
        return 12 * 60
    if suffix == "م":
        return (hour % 12 + 12) * 60
    return (hour % 12) * 60


def occasional_rows(data, day):
    """كل صفوف «الخدمات الطارئة» + أي قسم مخصّص تاني، مجمّعين في جدول
    واحد ومرتبين بمعاد الانتظام — الأساسية/الأهداف/الكتل الثابتة ليها
    جداولها بتاعتها فمش بتتكرر هنا."""
    people = _people_index(data)
    rows = []
    for a in peek_day(data, day):
        section = a.get("section") or SECTION_OCCASIONAL
        if section in ASSIGNMENT_SECTIONS and section != SECTION_OCCASIONAL:
            continue
        rows.append(_row(a, people, day))
    rows.sort(key=lambda r: _time_key(r.get("time")))
    return rows


def build_afraad(data, day):
    personnel = []
    for person in PeopleRepo(data).on_force(day, "personnel"):
        role = person.effective(day).get("role") or person.role
        personnel.append({"id": person.id, "name": person.name, "role": role,
                          "phone": person.phone})
    return {"date": day, "basic": basic_rows(data, day),
            "occasional": occasional_rows(data, day), "personnel": personnel}

"""تجميعة اليوم — كل حاجة بتخص تاريخ واحد.

دلوقتي البيانات دي مفرودة على خمس مفاتيح عليا مفهرسة بالتاريخ:

    day_assignments[day]  -> التكليفات
    day_officers[day]     -> حالة كل ضابط
    day_status[day]       -> قفل اليوم
    service_counts[day]   -> ورقة اعداد الخدمات (نسخة اليوم)
    day_confirm[day]      -> اللقطة المعتمدة

خمسة مفاتيح، نفس المفتاح الفرعي، وكل واحد بيتقرا ويتكتب من مكان مختلف.
`Day` بتجمّعهم في وحدة واحدة عشان (١) الكود يتعامل مع «اليوم» ككيان بدل
خمس قواميس متوازية، و(٢) تقسيم الملف لشهور بعدين يبقى تغيير جوّه
`DayRepo` بس — لأن الوحدة اللي هتتنقل بقت معرّفة.

التكليف نفسه هو «المصدر الوحيد للحقيقة» لمين على إيه النهاردة؛ اللوحة
ويومية الضباط ودفتر ٤٣ كلهم **عروض محسوبة** عليه.
"""
from dataclasses import dataclass, field

from ..constants import SECTION_OCCASIONAL, SERVICE_KINDS, SHIFTS
from .base import Model, max_length, one_of, require, text


@dataclass
class ConscriptSlot(Model):
    """قوام المجندين بالفئة — {فئة, عدد}."""
    cls_: str = ""               # بيتخزّن بمفتاح "class" — كلمة محجوزة
    count: int = 0

    @classmethod
    def from_dict(cls, raw):
        raw = dict(raw or {})
        if "class" in raw:
            raw["cls_"] = raw.pop("class")
        return super().from_dict(raw)

    def as_dict(self):
        out = super().as_dict()
        if "cls_" in out:
            out = {("class" if k == "cls_" else k): v for k, v in out.items()}
        return out


@dataclass
class Assignment(Model):
    """صف واحد على اللوحة: خدمة + مين عليها + بأي تسليح وفي أي فترة.

    `officer_ids` **قايمة** مش قيمة واحدة، وده مقصود:
      فاضية = خانة شاغرة (الوورد فيه 1,034 صف طوارئ بأفراد ومجندين بس)
      واحد  = الحالة العادية
      أكتر  = صف مشترك («رائد/جمال امين م.اول/ماركو ماجد» في لوحة 20/8)
    """
    id: str = ""
    section: str = ""
    name: str = ""               # اسم حر — الهوية بتيجي في المرحلة ٣
    service_id: str = None       # ★ الرابط للكتالوج — فاضي = خدمة طارئة
    kind: str = ""
    shift: str = ""
    officer_ids: list = field(default_factory=list)
    personnel_ids: list = field(default_factory=list)
    conscripts: list = field(default_factory=list)
    conscript_count: int = 0
    weapon: str = ""
    time: str = ""
    party: str = ""
    label_override: str = ""
    counts_in_summary: bool = True
    tags: list = field(default_factory=list)
    note: str = ""

    ID_PREFIX = "AS"

    def has(self, person_id):
        return (person_id in (self.officer_ids or [])
                or person_id in (self.personnel_ids or []))

    @property
    def vacant(self):
        return not (self.officer_ids or self.personnel_ids)

    def label(self, with_shift=True):
        """النص اللي بيتطبع على اللوحة. الوورد بيكتب الفترة **جوّه** اسم
        الخدمة في القسم الأساسي («تدخل سريع صبح»)."""
        from ..constants import SHIFT_SHORT
        override = text(self.label_override)
        if override:
            return override
        out = text(self.name)
        short = SHIFT_SHORT.get(text(self.shift))
        return f"{out} {short}" if with_shift and short else out

    def _check(self, errors):
        require(errors, self.name, "اسم الخدمة مطلوب.")
        max_length(errors, self.name, "name")
        one_of(errors, self.kind, SERVICE_KINDS, "تصنيف الخدمة غير صحيح.")
        # الحراسات هدف ثابت طول اليوم فمالهاش فترة
        if text(self.kind) != "حراسات":
            one_of(errors, self.shift, SHIFTS, "الفترة غير صحيحة.")
        elif text(self.shift):
            errors.append("الحراسات مالهاش فترة.")
        if self.conscript_count is not None and int(self.conscript_count or 0) < 0:
            errors.append("عدد المجندين لا يمكن أن يكون سالبًا.")
        max_length(errors, self.note, "note")

    @classmethod
    def blank(cls, assignment_id, name, section=SECTION_OCCASIONAL, **over):
        row = cls(id=assignment_id, name=name, section=section)
        for key, value in over.items():
            setattr(row, key, value)
        return row


@dataclass
class OfficerDayState(Model):
    """حالة الضابط نفسه في اليوم — **مش** تكليف بخدمة.

    السجل بيتشال لما يفضّى عشان الملف ما يمتلئش بمدخلات فاضية، فالحقول
    التلاتة كلها اختيارية بالتصميم.
    """
    taqseera: bool = False
    status: str = ""
    note: str = ""

    def _check(self, errors):
        from ..assignments import OFFICER_STATUSES
        one_of(errors, self.status, OFFICER_STATUSES, "حالة غير صحيحة.")
        max_length(errors, self.note, "note")

    @property
    def empty(self):
        return not (self.taqseera or text(self.status) or text(self.note))


@dataclass
class DayStatus(Model):
    """قفل اليوم. القفل التلقائي **مش متخزّن** — بيتحسب بمقارنة التاريخ
    بالنهاردة (شوف `backend/day_status.py`)، فالسجل هنا بيمثّل التدخّل
    اليدوي بس: قفل بدري أو فتح استثنائي."""
    closed: bool = False
    closed_at: str = ""
    closed_by: str = ""
    reopened_on: str = ""
    reopened_at: str = ""
    reopened_by: str = ""
    reason: str = ""


@dataclass
class CountEntry(Model):
    """سطر في ورقة «اعداد الخدمات» — اسم الخدمة وعدد المجندين عليها."""
    id: str = ""
    service_id: str = None       # ★ جاهز للمرحلة ٣
    name: str = ""
    block: str = ""              # صباحية / ليلية / طوارئ
    count: int = 0
    party: str = ""
    order: int = 0

    ID_PREFIX = "CNT"

    def _check(self, errors):
        from ..counts import BLOCKS
        require(errors, self.name, "اسم الخدمة مطلوب.")
        one_of(errors, self.block, BLOCKS, "البلوك غير صحيح.", required=True)
        if int(self.count or 0) < 0:
            errors.append("العدد لا يمكن أن يكون سالبًا.")


@dataclass
class Day:
    """اليوم كوحدة واحدة. مش `Model` — ده تجميع مش سجل مخزّن بذاته؛
    كل جزء بيرجع لمفتاحه الأصلي في الملف عن طريق `DayRepo`."""
    date: str
    assignments: list = field(default_factory=list)        # Assignment
    officer_states: dict = field(default_factory=dict)     # id -> OfficerDayState
    status: DayStatus = None
    count_entries: list = None                             # None = لسه على القالب
    confirmed_at: str = ""
    confirmed_by: str = ""

    def __post_init__(self):
        if self.status is None:
            self.status = DayStatus()

    # ---------- استعلامات ----------

    def of_person(self, person_id):
        """تكليفات شخص في اليوم ده — بترتيبها على اللوحة."""
        return [a for a in self.assignments if a.has(person_id)]

    def assignment(self, assignment_id):
        return next((a for a in self.assignments if a.id == assignment_id), None)

    def state_of(self, officer_id):
        return self.officer_states.get(officer_id) or OfficerDayState()

    def in_section(self, section):
        return [a for a in self.assignments if a.section == section]

    @property
    def people_ids(self):
        """كل معرّفات الأشخاص المكلّفين في اليوم — بدون تكرار."""
        out = []
        for a in self.assignments:
            for pid in (a.officer_ids or []) + (a.personnel_ids or []):
                if pid not in out:
                    out.append(pid)
        return out

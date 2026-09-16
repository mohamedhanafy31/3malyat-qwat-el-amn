"""الفرق والالتحاق بيها.

حاجتين مربوطين: **الفرقة** (`Course`) بتتكرر — نفس «فرقة الحراسات
المشددة» بتتاخد كذا مرة بضباط مختلفين؛ و**الالتحاق** (`CourseTerm`) هو
ضابط + فرقة + مدى تواريخ. الالتحاق بمدى تواريخ بيغطي كل أيامه لوحده،
فالضابط بيظهر في خانة «فرقة» طول المدة من غير ما حد يكتبها كل يوم.
"""
from dataclasses import dataclass

from .base import Model, date_order, max_length, one_of, require, valid_date

COURSE_KINDS = ["تأهيلية", "تخصصية", "قادة", "تدريبية", "أخرى"]


@dataclass
class Course(Model):
    id: str = ""
    name: str = ""
    place: str = ""
    kind: str = ""
    note: str = ""

    ID_PREFIX = "CRS"

    def _check(self, errors):
        require(errors, self.name, "اسم الفرقة مطلوب.")
        max_length(errors, self.name, "name")
        one_of(errors, self.kind, COURSE_KINDS, "نوع الفرقة غير صحيح.")
        max_length(errors, self.note, "note")


@dataclass
class CourseTerm(Model):
    id: str = ""
    course_id: str = ""
    officer_id: str = ""
    start: str = ""
    end: str = ""
    note: str = ""
    source: str = ""            # النص الأصلي لو الالتحاق اتستخرج من الأرشيف

    ID_PREFIX = "CT"
    ID_WIDTH = 4

    def covers(self, day):
        return bool(self.start and self.end) and self.start <= day <= self.end

    def _check(self, errors):
        require(errors, self.officer_id, "برجاء اختيار الضابط.")
        require(errors, self.course_id, "الفرقة غير موجودة.")
        start = valid_date(errors, self.start, "تاريخ البداية غير صحيح.")
        end = valid_date(errors, self.end, "تاريخ النهاية غير صحيح.")
        date_order(errors, start, end)
        if start and end:
            from datetime import date
            span = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
            if span > 400:
                errors.append("مدة الفرقة كبيرة بشكل غير منطقي.")
        max_length(errors, self.note, "note")

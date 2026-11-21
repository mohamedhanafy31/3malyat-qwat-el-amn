"""الفرق والالتحاق بيها.

حاجتين مربوطين: **الفرقة** (`Course`) بتتكرر — نفس «فرقة الحراسات
المشددة» بتتاخد كذا مرة بضباط مختلفين؛ و**الالتحاق** (`CourseTerm`) هو
ضابط + فرقة + مدى تواريخ. الالتحاق بمدى تواريخ بيغطي كل أيامه لوحده،
فالضابط بيظهر في خانة «فرقة» طول المدة من غير ما حد يكتبها كل يوم.
"""
from dataclasses import dataclass

from .base import Model, date_order, max_length, require, valid_date


@dataclass
class Course(Model):
    id: str = ""
    name: str = ""
    place: str = ""
    note: str = ""

    ID_PREFIX = "CRS"

    @classmethod
    def from_dict(cls, raw):
        # Legacy course records may still carry this removed field. It is
        # intentionally ignored and therefore cannot be written back.
        return super().from_dict({key: value for key, value in (raw or {}).items()
                                  if key != "kind"})

    def _check(self, errors):
        require(errors, self.name, "اسم الفرقة مطلوب.")
        max_length(errors, self.name, "name")
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
        require(errors, self.officer_id, "يرجى اختيار الضابط.")
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

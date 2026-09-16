"""الراحة/الإجازة — سجل بمدى تواريخ مربوط بشخص.

الاسم **مش** من حقول السجل: بيتحلّ من `person_id` وقت القراءة
(`LeaveRepo.named`). كان متخزّن هنا قبل `migrations/007_drop_leave_name.py`،
وتخزينه كان معناه إن أي تعديل اسم يسيب الراحات القديمة بالاسم القديم.

الملفات القديمة اللي لسه شايلة `name` بتفضل تشتغل: `Model.from_dict`
بتحفظ الحقول اللي مش في النموذج وبترجّعها زي ما هي.
"""
from dataclasses import dataclass

from ..constants import LEAVE_TYPES
from .base import Model, date_order, max_length, one_of, require, valid_date


@dataclass
class Leave(Model):
    id: str = ""
    person_id: str = ""
    type: str = ""
    start: str = ""
    end: str = ""
    return_date: str = ""           # محسوب: اليوم اللي بعد النهاية
    note: str = ""
    source: str = ""                # النص الأصلي لو السجل اتستخرج من الأرشيف

    ID_PREFIX = "LV"

    def covers(self, day):
        return bool(self.start) and self.start <= day <= self.end

    @property
    def days(self):
        from datetime import date
        if not (self.start and self.end):
            return 0
        return (date.fromisoformat(self.end) - date.fromisoformat(self.start)).days + 1

    def _check(self, errors):
        require(errors, self.person_id, "برجاء اختيار الشخص.")
        one_of(errors, self.type, LEAVE_TYPES, "نوع الراحة غير صحيح.", required=True)
        start = valid_date(errors, self.start, "تاريخ البداية غير صحيح.", required=True)
        end = valid_date(errors, self.end, "تاريخ النهاية غير صحيح.", required=True)
        date_order(errors, start, end)
        # 120 يوم — نفس حد `parse_range` الحالي. أطول من كده غالبًا سنة
        # مكتوبة غلط، والسجل بيفضل يغطّي أيام في كل اليوميات بعدها.
        if start and end and self.days > 120:
            errors.append("مدة الراحة كبيرة بشكل غير منطقي.")
        max_length(errors, self.note, "note")

    def within_service(self, person):
        """-> رسالة خطأ لو الراحة بره فترة خدمة الشخص، أو None.

        راحة بتاريخ قبل الانضمام أو بعد الخروج بتفضل في الإجماليات وهي
        مستحيلة تشغيليًا، ومابتظهرش في أي يومية — فبتفضل غلط مخفي.
        """
        join = str(person.join_date or "")
        if join and self.start < join:
            return f"تاريخ الراحة قبل تاريخ انضمام الشخص ({join})."
        left = str(person.leave_date or "")
        if left and self.end > left:
            return f"تاريخ الراحة بعد تاريخ خروج الشخص من القوة ({left})."
        return None

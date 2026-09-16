"""نماذج البيانات — العقد المكتوب لشكل كل سجل في الملف.

الفهرس ده بيخلي `from ..models import Officer, Leave` تشتغل من غير ما
المستدعي يعرف السجل في أنهي ملف.

القاعدة الحاكمة لكل النماذج: **القراءة ما بتغيّرش الشكل** — سجل بيتقرا
ويترجع لازم يطلع بنفس مفاتيحه بالحرف. الشرح الكامل والسبب في
[base.py](base.py).
"""
from .base import Model
from .change import MAX_ENTRIES, ChangeEntry
from .course import COURSE_KINDS, Course, CourseTerm
from .day import (
    Assignment, ConscriptSlot, CountEntry, Day, DayStatus, OfficerDayState,
)
from .leave import Leave
from .mission import OPEN_STATUSES, STATUSES, Mission
from .person import (
    ACTIVE, ARCHIVED, Individual, Officer, OfficerHistory, Person, of_category,
)

__all__ = [
    "Model",
    "Officer", "Individual", "Person", "OfficerHistory", "of_category",
    "ACTIVE", "ARCHIVED",
    "Leave",
    "Course", "CourseTerm", "COURSE_KINDS",
    "Day", "Assignment", "ConscriptSlot", "OfficerDayState", "DayStatus", "CountEntry",
    "Mission", "STATUSES", "OPEN_STATUSES",
    "ChangeEntry", "MAX_ENTRIES",
]

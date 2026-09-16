"""المأمورية — كيان تشغيلي له دورة حياة، مش خدمة بتتكرر كل يوم.

الفرق عن «الخدمة»: الخدمة نوع تشغيل بيتكتب على اليومية كل يوم لوحده.
المأمورية حدث له بداية وحالة بتتغيّر مع الوقت، ودورة حياتها هي اللي
بتتتابع بدل ما تتكتب من أول وجديد كل يوم.
"""
from dataclasses import dataclass, field

from .base import Model, max_length, one_of, require, valid_date

STATUSES = ["مخططة", "بدأت", "عادت", "أغلقت", "ألغيت"]
OPEN_STATUSES = {"مخططة", "بدأت"}


@dataclass
class Mission(Model):
    id: str = ""
    name: str = ""
    member_ids: list = field(default_factory=list)
    start: str = ""
    note: str = ""
    status: str = "مخططة"

    ID_PREFIX = "MSN"

    @property
    def open(self):
        return self.status in OPEN_STATUSES

    def _check(self, errors):
        require(errors, self.name, "اسم المأمورية مطلوب.")
        max_length(errors, self.name, "name")
        one_of(errors, self.status, STATUSES, "حالة غير صحيحة.", required=True)
        valid_date(errors, self.start, "تاريخ البداية غير صحيح.")
        max_length(errors, self.note, "note")

from dataclasses import dataclass

from ..constants import VEHICLE_ORIGINS, VEHICLE_STATUSES, VEHICLE_TYPES
from .base import Model, max_length, one_of, require, text


@dataclass
class Vehicle(Model):
    id: str = ""
    plate_series: str = ""
    plate_number: str = ""
    type: str = ""
    model: str = ""
    status: str = "operational"
    fault: str = ""
    notes: str = ""
    archived: bool = False
    origin: str = "internal"
    party: str = ""

    ID_PREFIX = "VEH"

    @property
    def plate(self):
        return f"{self.plate_series}/{self.plate_number}" if self.plate_series else self.plate_number

    def _check(self, errors):
        require(errors, self.plate_number, "رقم اللوحة مطلوب.")
        if text(self.plate_number) and not text(self.plate_number).isdigit():
            errors.append("رقم اللوحة يجب أن يتكون من أرقام فقط.")
        one_of(errors, self.type, VEHICLE_TYPES, "نوع المركبة غير صحيح.", required=True)
        one_of(errors, self.status, VEHICLE_STATUSES, "حالة المركبة غير صحيحة.", required=True)
        one_of(errors, self.origin, VEHICLE_ORIGINS, "تبعية المركبة غير صحيحة.", required=True)
        if self.origin == "external" and not text(self.party):
            errors.append("الجهة مطلوبة للمركبة الخارجية.")
        max_length(errors, self.party, "party")
        if self.status == "disabled" and not text(self.fault):
            errors.append("سبب التعطيل مطلوب.")
        max_length(errors, self.plate_series, "plate_series")
        max_length(errors, self.model, "model")
        max_length(errors, self.fault, "reason")
        max_length(errors, self.notes, "note")


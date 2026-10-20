from dataclasses import dataclass

from .base import Model, max_length, require


@dataclass
class Conscript(Model):
    id: str = ""
    name: str = ""
    phone: str = ""
    is_driver: bool = True

    ID_PREFIX = "CON"

    def _check(self, errors):
        require(errors, self.name, "اسم المجند مطلوب.")
        max_length(errors, self.name, "name")
        max_length(errors, self.phone, "phone")

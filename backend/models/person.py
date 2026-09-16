"""الضابط والفرد — وسجل التغييرات المؤرَّخ على الضابط.

الاتنين بيشتركوا في أغلب الحقول (هوية + فترة خدمة)، بس مش متماثلين:
الضابط له `section` و`rest_system`/`rest_day` و`history`، والفرد له
`address` و`other_phones`. الفرق ده حقيقي في البيانات مش صدفة — الفرد
مابيتحسبش في جدول الإجمالي ومالوش نظام راحة مسجّل.

`status` بيقول «على القوة» ولا «خرج». دلوقتي السجل بيتخزّن في قايمتين
منفصلتين (`active` / `archive`) **و** بيشيل `status` كمرآة ليهم — يعني
نفس الحقيقة متخزّنة مرتين. المرحلة ٢ بتخلي القايمتين عرض محسوب على
`status`، والنموذج هنا مكتوب على الشكل النهائي ده من دلوقتي.
"""
from dataclasses import dataclass, field

from ..constants import (
    OFFICER_ROLES, OFFICER_SECTIONS, PERSONNEL_FAMILIES, REST_SYSTEMS, WEEKDAYS,
)
from .base import Model, max_length, one_of, require, text, valid_date

ACTIVE, ARCHIVED = "active", "archived"


@dataclass
class OfficerHistory(Model):
    """الرتبة والمنصب والقسم بتاريخ سريان.

    من غير السجل ده إعادة توليد يوم قديم بتطبع بيانات النهاردة — يومية 5/7
    بتقول «مقدم / أشرف الشريف» والملف فيه «عقيد» بعد الترقية.
    """
    from_: str = ""          # بيتخزّن بمفتاح "from" — كلمة محجوزة في بايثون
    role: str = ""
    post: str = ""
    section: str = ""
    search_attached: bool = False

    # ---- "from" مفتاح محجوز، فالتحويل بيتظبط بالإيد ----

    @classmethod
    def from_dict(cls, raw):
        raw = dict(raw or {})
        if "from" in raw:
            raw["from_"] = raw.pop("from")
        return super().from_dict(raw)

    def as_dict(self):
        out = super().as_dict()
        if "from_" in out:
            out = {("from" if k == "from_" else k): v for k, v in out.items()}
        return out

    def _check(self, errors):
        valid_date(errors, self.from_, "تاريخ سريان التغيير غير صحيح.", required=True)
        one_of(errors, self.role, OFFICER_ROLES, "الرتبة غير صحيحة.")
        one_of(errors, self.section, OFFICER_SECTIONS, "قسم الضابط غير صحيح.")


@dataclass
class Person(Model):
    """الحقول المشتركة بين الضابط والفرد."""
    id: str = ""
    code: str = ""                    # رقم الأقدمية
    name: str = ""
    role: str = ""
    phone: str = ""
    post: str = ""
    join_date: str = ""
    status: str = ACTIVE
    leave_date: str = ""              # تاريخ الخروج من القوة
    leave_reason: str = ""

    @property
    def archived(self):
        return self.status == ARCHIVED

    def on_force(self, day):
        """كان على القوة في اليوم ده؟ — انضم قبله أو فيه، وما خرجش قبله."""
        if self.join_date and self.join_date > day:
            return False
        if self.leave_date and day > self.leave_date:
            return False
        return True

    def _check(self, errors):
        require(errors, self.name, "الاسم مطلوب.")
        require(errors, self.code, "رقم الأقدمية مطلوب.")
        for f in ("name", "code", "phone", "post"):
            max_length(errors, getattr(self, f), f)
        valid_date(errors, self.join_date, "تاريخ الانضمام غير صحيح.", required=True)
        if self.leave_date:
            valid_date(errors, self.leave_date, "تاريخ الخروج غير صحيح.")
            if self.join_date and self.leave_date < self.join_date:
                errors.append("تاريخ الخروج لا يمكن أن يسبق تاريخ الانضمام.")
        max_length(errors, self.leave_reason, "reason")
        if self.phone and not _phone_ok(self.phone):
            errors.append("رقم التليفون غير صحيح.")


@dataclass
class Officer(Person):
    section: str = ""
    rest_system: str = ""
    rest_day: str = ""
    search_attached: bool = False
    history: list = field(default_factory=list)
    previous_archive_id: str = ""     # لما ضابط يرجع للقوة بعد أرشفة

    ID_PREFIX = "OFF"
    CATEGORY = "officers"

    def _check(self, errors):
        super()._check(errors)
        one_of(errors, self.role, OFFICER_ROLES, "الرتبة غير صحيحة.", required=True)
        one_of(errors, self.section, OFFICER_SECTIONS, "قسم الضابط غير صحيح.")
        one_of(errors, self.rest_system, REST_SYSTEMS, "نظام الراحة غير صحيح.")
        one_of(errors, self.rest_day, WEEKDAYS, "يوم الراحة غير صحيح.")
        # راحة أسبوعية من غير يوم بتعطّل حساب الراحة الجاية بالكامل في صمت:
        # `next_rest_start` مابتلاقيش يوم تبني عليه، فالضابط عمره ما بيطلع
        # في تنبيه التقصيرة ولا بيتحسب في الالتزام.
        if text(self.rest_system) == "أسبوعية" and not text(self.rest_day):
            errors.append("الراحة الأسبوعية لازم يتحدد ليها يوم في الأسبوع.")

    def effective(self, day):
        """الرتبة/المنصب/القسم/جهة التشغيل زي ما كانوا في اليوم ده."""
        current = {"role": self.role, "post": self.post,
                   "section": self.section or OFFICER_SECTIONS[0],
                   "search_attached": bool(self.search_attached)}
        if not self.history:
            return current
        applicable = [h for h in self.history if (h.get("from") or "") <= day]
        if not applicable:
            applicable = [min(self.history, key=lambda h: h.get("from") or "")]
        latest = max(applicable, key=lambda h: h.get("from") or "")
        return {k: latest.get(k, v) for k, v in current.items()}


@dataclass
class Individual(Person):
    """الفرد — «ف-###». مالوش قسم ولا نظام راحة ولا تاريخ مؤرَّخ."""
    address: str = ""
    other_phones: list = field(default_factory=list)

    ID_PREFIX = "IND"
    CATEGORY = "personnel"

    def _check(self, errors):
        super()._check(errors)
        max_length(errors, self.address, "address")
        require(errors, self.role, "الرتبة مطلوبة.")
        # الرتبة نص حر بس لازم تبدأ بعائلة معروفة من كشف أرقام الأفراد
        if text(self.role) and not any(text(self.role).startswith(fam)
                                       for fam in PERSONNEL_FAMILIES):
            errors.append("رتبة الفرد غير معروفة.")
        for extra in self.other_phones or []:
            if not _phone_ok(extra):
                errors.append("رقم تليفون إضافي غير صحيح.")
                break


def _phone_ok(value):
    from ..utils import valid_phone
    return valid_phone(value)


def of_category(category):
    """النموذج المناسب لـ«officers» / «personnel»."""
    return Officer if category == "officers" else Individual

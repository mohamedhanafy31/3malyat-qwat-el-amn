"""الأساس المشترك لكل نماذج البيانات.

قبل الملف ده ماكانش فيه في المشروع كله مكان واحد بيقول «سجل الراحة شكله
إيه». الشكل كان متفرّق على: الدالة اللي بتبنيه (`build_leave`)، الدالة
اللي بتعدّله (`apply_*`)، والتحقق اللي في المسار، وأي حد عايز يعرف الحقول
كان بيقرا الملف نفسه. النماذج دي هي العقد المكتوب.

## القاعدة الأهم: القراءة ما بتغيّرش الشكل

السجل اللي بيتقرا من الملف لازم يرجع **بنفس مفاتيحه بالظبط** — لا حقل
بيتضاف ولا بيتشال. ده مش تجميل:

  * `confirm._fingerprint()` بيقارن `r.get(k)` لكل حقل متتبَّع. حقل
    ماكانش موجود بيرجع `None`، ونفس الحقل لو النموذج ضافه بقيمة `""`
    بيرجع `""` — والاتنين مش متساويين. يعني مجرد إن النموذج «يكمّل»
    الحقول الناقصة كان هيخلي **كل يوم متأكّد يبان كأنه اتعدّل بعد
    التأكيد**، من غير ما حد يلمسه.
  * `_write()` بيسلسل الـdict زي ما هو، فأي حقل بيتضاف بيكبّر الملف
    ويدخل في كل نسخة احتياطية بعد كده.

عشان كده `from_dict()` بتفتكر الحقول اللي **ماكانتش** موجودة، و`as_dict()`
بتسيبها ناقصة طول ما محدش غيّرها. السجل الجديد (المبني بالـconstructor
مباشرة) بياخد كل حقوله عادي — ده المكان اللي القيم الافتراضية المفروض
تتكتب فيه.

`test_models.py` بيثبّت ده على `data.json` الحقيقي: كل سجل في الملف
بيعدّي `as_dict(from_dict(x)) == x` بالحرف.
"""
from dataclasses import dataclass, fields


@dataclass
class Model:
    """أب مشترك: تحويل من/إلى dict مع الحفاظ على الشكل الأصلي، وتحقق."""

    def __post_init__(self):
        # الحقول اللي ماكانتش في السجل المقروء. سجل جديد = مفيش حاجة ناقصة.
        self._absent = frozenset()
        self._unknown = {}

    # ---------- التحويل ----------

    @classmethod
    def field_names(cls):
        return [f.name for f in fields(cls)]

    @classmethod
    def from_dict(cls, raw):
        """نموذج من سجل مخزّن. الحقول الزيادة (من نسخة أحدث أو هجرة نصّية)
        بتتحفظ زي ما هي وبترجع في `as_dict()` — ما بتتمسحش في صمت."""
        raw = dict(raw or {})
        known = set(cls.field_names())
        obj = cls(**{k: v for k, v in raw.items() if k in known})
        obj._absent = frozenset(known - set(raw))
        obj._unknown = {k: v for k, v in raw.items() if k not in known}
        return obj

    def as_dict(self):
        """الشكل المخزّن — شوف شرح «القراءة ما بتغيّرش الشكل» فوق."""
        out = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name in self._absent and value == _default_of(f):
                continue          # كان ناقص ولسه على قيمته الافتراضية
            out[f.name] = value
        out.update(self._unknown)
        return out

    # ---------- التحقق ----------

    def validate(self):
        """قايمة أخطاء عربية جاهزة للعرض — فاضية يعني السجل سليم.

        النماذج بتنفّذ `_check()` بدل ما تعيد تعريف الدالة دي، عشان
        الأخطاء تتجمّع كلها مرة واحدة بدل ما المستخدم يصلّح واحد
        ويكتشف اللي بعده.
        """
        errors = []
        self._check(errors)
        return errors

    def _check(self, errors):
        """تنفّذها النماذج اللي ليها قواعد."""

    @property
    def ok(self):
        return not self.validate()


def _default_of(f):
    """القيمة الافتراضية للحقل — من `default` أو `default_factory`."""
    from dataclasses import MISSING
    if f.default is not MISSING:
        return f.default
    if f.default_factory is not MISSING:      # type: ignore[misc]
        return f.default_factory()            # type: ignore[misc]
    return None


# ---------- أدوات تحقق مشتركة ----------

def text(value):
    """نص مجرّد من الفراغات — بيتعامل مع None زي النص الفاضي."""
    return str(value or "").strip()


def require(errors, value, message):
    if not text(value):
        errors.append(message)
        return False
    return True


def one_of(errors, value, allowed, message, required=False):
    """القيمة لازم تكون من القايمة. الفاضي مسموح إلا لو `required`."""
    raw = text(value)
    if not raw:
        if required:
            errors.append(message)
        return
    if raw not in allowed:
        errors.append(message)


def max_length(errors, value, field):
    """الحد الأقصى لطول حقل حر — نفس حدود `utils.MAX_LEN`."""
    from ..utils import MAX_LEN
    limit = MAX_LEN.get(field)
    if limit and len(text(value)) > limit:
        errors.append(f"الحقل «{field}» أطول من الحد المسموح ({limit} حرف).")


def valid_date(errors, value, message, required=False):
    """-> التاريخ المعياري أو None. بيضيف خطأ لو مش صالح."""
    from ..utils import canonical_day
    raw = text(value)
    if not raw:
        if required:
            errors.append(message)
        return None
    day = canonical_day(raw)
    if not day:
        errors.append(message)
    return day


def date_order(errors, start, end, message="تاريخ النهاية قبل تاريخ البداية."):
    if start and end and end < start:
        errors.append(message)

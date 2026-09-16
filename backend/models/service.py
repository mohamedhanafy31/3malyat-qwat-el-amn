"""كتالوج الخدمات — الهوية الثابتة للخدمة المتكررة.

الكتالوج ده **مش مستخدم دلوقتي**. هجرة `004_inline_service_fields` شالت
`service_id` من صفوف التكليف وحطت الاسم والتصنيف مباشرة، ومسار الكتالوج
وصفحته اتحذفوا بعدها. النتيجة: 416 سجل في `data["services"]` ملهاش ولا
قارئ واحد، و392 اسم خدمة حر في 2,904 صف من غير أي هوية تجمعهم.

النموذج ده مكتوب من دلوقتي عشان المرحلة ٣ (الربط الاختياري): المشغّل
يفضل يكتب الاسم حر، والنظام يحلّه للكتالوج عن طريق `aliases` — فتبقى فيه
إحصاءات بالخدمة وإعادة تسمية من غير لمس الأرشيف، من غير ما حد يضطر يختار
من قايمة منسدلة.

لحد ما ده يحصل، `Assignment.service_id` بيفضل `None` وده **مش** مرجع
معلّق — معناه «خدمة طارئة مالهاش هوية»، و255 اسم من الـ392 بيظهروا مرة
واحدة بس في كل الأرشيف، فالحالة دي هي الأغلب مش الاستثناء.
"""
from dataclasses import dataclass, field

from ..constants import SERVICE_KINDS, SERVICE_SECTIONS, SHIFTS
from .base import Model, max_length, one_of, require, text


@dataclass
class Service(Model):
    id: str = ""
    name: str = ""
    aliases: list = field(default_factory=list)   # أسماء تانية بتتطابق عليها
    board_label: str = ""
    sub: str = ""
    kind: str = ""
    section: str = ""
    standing: bool = False                        # خدمة دائمة ولا طارئة
    shifts: list = field(default_factory=list)
    party: str = ""
    default_strength: str = ""
    default_weapon: str = ""
    default_time: str = ""
    needs: dict = field(default_factory=dict)     # {officer, individual, unit, vehicle}
    counts_in_summary: bool = True
    appears_in: list = field(default_factory=list)  # board / afrad / counts / ...

    ID_PREFIX = "SVC"

    def matches(self, name):
        """الاسم ده بيشاور على الخدمة دي؟ — الاسم الرسمي أو أي مرادف."""
        raw = normalise(name)
        return raw and (raw == normalise(self.name)
                        or raw in {normalise(a) for a in self.aliases or []})

    def defaults(self):
        """القيم اللي بتتملّى تلقائيًا على صف تكليف جديد من الخدمة دي."""
        return {"kind": self.kind, "section": self.section, "party": self.party,
                "weapon": self.default_weapon, "time": self.default_time,
                "counts_in_summary": self.counts_in_summary}

    def _check(self, errors):
        require(errors, self.name, "اسم الخدمة مطلوب.")
        max_length(errors, self.name, "name")
        one_of(errors, self.kind, SERVICE_KINDS, "تصنيف الخدمة غير صحيح.")
        one_of(errors, self.section, SERVICE_SECTIONS, "قسم الخدمة غير صحيح.")
        for shift in self.shifts or []:
            if text(shift) not in SHIFTS:
                errors.append("فترة غير صحيحة في قايمة فترات الخدمة.")
                break


def normalise(name):
    """تطبيع خفيف لمطابقة الأسماء العربية المكتوبة بحرية.

    فحص على 392 اسم في الأرشيف: التطبيع ده **مابيدمجش** أي اسمين حاليًا
    (الأسماء اتولدت من الكتالوج في هجرة 004 فورثت كتابته بالحرف). قيمته
    بتبان مع الإدخال اليدوي الجديد، اللي فيه «الاهداف» و«الأهداف» بيتكتبوا
    الاتنين — فبيتحط من دلوقتي بدل ما يتضاف بعد ما التكرار يحصل.
    """
    import re
    raw = text(name)
    if not raw:
        return ""
    raw = re.sub("[أإآٱ]", "ا", raw)
    raw = raw.replace("ة", "ه").replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي")
    raw = re.sub("[ً-ْـ]", "", raw)      # تشكيل وتطويل
    return re.sub(r"\s+", " ", raw).strip()

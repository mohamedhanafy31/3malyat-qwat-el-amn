"""سجل التغييرات — مين عدّل إيه وإمتى، بالقيمة قبل وبعد.

مختلف عن `logs/audit.log`: ده بيسجّل إن فيه طلب كتابة حصل ومين كتبه بس؛
السجل ده بيحفظ الكيان المتأثر والقيمة قبل وبعد، عشان سؤال «إيه اللي
اتغيّر بالظبط؟» يكون له إجابة من غير ما حد يرجع لنسخة احتياطية قديمة.

**السجل ده تاريخ، مش مراجع.** `before`/`after` لقطات لحظة حصلت فعلًا،
فبتفضل شايلة معرّفات سجلات اتمسحت بعد كده — وده مقصود: مسح الـid منها
بأثر رجعي بيحوّل سجل التدقيق لسجل بيكدب. عشان كده `tools/
check_integrity.py` بيستثنيه من الفحص.
"""
from dataclasses import dataclass

from .base import Model

MAX_ENTRIES = 5000


@dataclass
class ChangeEntry(Model):
    id: str = ""
    ts: str = ""
    entity: str = ""            # نوع الكيان: leave / officer_state / day_confirm / ...
    entity_id: str = ""
    action: str = ""            # create / update / delete / close / confirm
    day: str = None             # اليوم المتأثر لو التغيير يخص يومية
    text: str = ""              # جملة عربية جاهزة للعرض
    before: object = None
    after: object = None
    reason: str = ""
    edited_by: str = None

    ID_PREFIX = "CHG"

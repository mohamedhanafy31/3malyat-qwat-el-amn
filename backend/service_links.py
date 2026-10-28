"""حل ربط أسماء الخدمات الحرة بهوية دليل الخدمات."""
from .service_catalog import catalog
from .text import core_service_name, norm
from functools import lru_cache

# كل مجموعة = أسماء لنفس الخدمة اتكتبت بأشكال مختلفة في القوايم. أي اسم من
# المجموعة بيتربط بأي صف في الدليل اسمه من نفس المجموعة — مفيش اتجاه.
_ALIAS_GROUPS = [
    ["قول مكبر", "القول المكبر"],
    ["الاسعاف", "الإسعاف", "ارتكاز الاسعاف", "ارتكاز الإسعاف"],
    ["التدخل السريع", "التدخل سريع", "تدخل سريع"],
    ["مبنى المخابرات", "مبنى المخابرات الحربية"],
    ["استراحة القنصل", "استراحة القنصل السعودي"],
    ["اعلى 109", "اعلي كمين 109", "اعلى كمين 109"],
    ["نقطة تفتيش كمين 109 اسفل", "كمين 109", "كمين 109 - بيك اب", "كمين 109 - مدرعة"],
    ["ارتكاز قسم فيصل", "ارتكاز قسم فيصل الجديد"],
    ["القنصلية السعودية", "القنصلية", "قنصلية"],
    ["قول الكورنيش", "كول كورنيش", "قول كورنيش"],
    ["حملة الأمن الوطني", "حملة أمن وطني 12ص", "حملة امن وطني"],
]


def _keys(name):
    raw = str(name or "")
    return {key for key in (norm(raw), norm(core_service_name(raw))) if key}


@lru_cache(maxsize=512)
def _group_keys(name):
    """مفاتيح الاسم نفسه + مفاتيح كل اسم في مجموعة مرادفاته."""
    keys = _keys(name)
    for group in _ALIAS_GROUPS:
        group_keys = set().union(*(_keys(member) for member in group))
        if keys & group_keys:
            keys |= group_keys
    # frozenset لأن النتيجة متخزنة في lru_cache — أي تعديل عليها كان هيبوّظ الكاش
    return frozenset(keys)


def resolve_service_id(data, name, index=None):
    wanted = _group_keys(str(name or ""))
    if not wanted:
        return None
    if index is not None:
        # الفهرس: مفتاح → (ترتيب الصف في الدليل، المعرّف). بنختار أقدم صف في
        # الدليل زي البحث الخطي القديم بالظبط، مش أول مفتاح يطلع من الـset
        # (ترتيب الـset بيتغيّر من تشغيل للتاني).
        hits = [index[key] for key in wanted if key in index]
        return min(hits)[1] if hits else None
    for entry in catalog(data):
        if _keys(entry.get("name")) & wanted:
            return entry.get("id")
    return None


def service_for_counts_entry(data, entry, index=None):
    stored = str((entry or {}).get("service_id") or "").strip()
    if stored:
        return stored
    return resolve_service_id(data, (entry or {}).get("name"), index=index)

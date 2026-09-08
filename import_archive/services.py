#!/usr/bin/env python3
"""كتالوج خدمات الضباط + استخراج التشغيل اليومي من اليوميات.

الفكرة: ربط الضابط بالخدمة قابل للاستخراج من نص التشغيل بدقة، لكن تصنيف
الخدمة نفسها (داخلية / خارجية) معرفة تشغيلية — فبتتخزن مرة واحدة في
الكتالوج وتتعدّل من الواجهة، وكل الإجماليات بتتحسب منها.
"""
import re
from common import strip_ar

EXTERNAL, INTERNAL, GUARD, MEDICAL, SEARCH = "خارجية", "داخلية", "حراسات", "طبية", "بحث"
MORNING, NIGHT = "صباحية", "ليلية"

# اسم الخدمة الرسمي زي ما ظاهر في "لوحة التشغيل المختصرة" (D.docx) — بيُستخدم
# في صفحة المطابقة بدل الاسم الداخلي؛ افتراضيًا نفس اسم الخدمة.
# BOARD_SLOT لخدمات "الداخلية" الثابتة تحدد صفها في اللوحة (نوبتجي/عظيم/أمن).

# (اسم الخدمة، التصنيف، مفاتيح المطابقة، standing[دائمة؟ للخارجية بس])
CATALOG = [
    # ---------- الحراسات المشددة (كل الأهداف دايمة) ----------
    ("مشرف الأهداف",              GUARD,    ["مشرف الاهداف"], True),
    ("هدف أنابيب البترول",        GUARD,    ["بهدف انابيب"], True),
    ("هدف سوميد",                 GUARD,    ["بهدف سوميد"], True),
    ("هدف عيون موسى",             GUARD,    ["بهدف عيون"], True),
    ("هدف هلة المحجر",            GUARD,    ["بهدف هله", "بهدف هلة"], True),
    ("هدف كهرباء عتاقة",          GUARD,    ["بهدف كهرباء عتاقه"], True),
    ("هدف مصر للبترول",           GUARD,    ["بهدف مصر"], True),
    ("هدف كهرباء السخنة",         GUARD,    ["بهدف السخنه", "بهدف كهرباء السخنه"], True),
    # ---------- الأدوار الدوّارة الثابتة (٣ صفوف اللوحة) ----------
    ("ضابط عظيم الإدارة",         INTERNAL, ["ضابط عظيم"], True),
    ("ضابط أمن الإدارة",          INTERNAL, ["امن الاداره", "ضابط امن الاداره"], True),
    ("نوبتجي المعسكر الفرعي",     INTERNAL, ["نوبتجي"], True),
    # ---------- خدمات داخلية عرضية ----------
    ("ضابط أمن المعسكر",          INTERNAL, ["امن المعسكر"], False),
    ("تأمين السجن العسكري",       INTERNAL, ["تامين السجن العسكري", "تامين سجن العسكري"], False),
    ("العمل بالمعسكر الفرعي",     INTERNAL, ["بالمعسكر الفرعي"], False),
    # ---------- البحث (يظهر كـ "+N بحث") ----------
    ("ضابط مباحث السجن العسكري",  SEARCH,   ["مباحث السجن"], False),
    # ---------- الخدمات الخارجية الأساسية (دائمة، ~90%+ من الأيام) ----------
    ("تدخل سريع",                 EXTERNAL, ["تدخل سريع"], True),
    ("قول مكبر",                  EXTERNAL, ["قول مكبر"], True),
    ("كنترول الأزهر",             EXTERNAL, ["كنترول الازهر"], True),
    ("كنترول الثانوية العامة",    EXTERNAL, ["كنترول الثانويه"], True),
    ("القنصلية السعودية",         EXTERNAL, ["قنصلي"], True),
    # ---------- الخدمات الخارجية الطارئة/العرضية ----------
    ("تسفير الأزهر",              EXTERNAL, ["تسفير الازهر"], False),
    ("توزيع وتجميع أوراق الثانوية", EXTERNAL, ["توزيع وتجميع"], False),
    ("نقطة تفتيش جنيفة",          EXTERNAL, ["نقطه تفتيش", "تفتيش جنيفه"], False),
    ("تبة ضرب النار",             EXTERNAL, ["تبه ضرب النار"], False),
    ("حملة الأمن الوطني",         EXTERNAL, ["الامن الوطني", "امن وطني"], False),
    ("ارتكاز سينما ريسنس",        EXTERNAL, ["سينيما", "سينما"], False),
    ("ارتكاز الخضر",              EXTERNAL, ["ارتكاز الخضر"], False),
    ("مرافقة الجماهير",           EXTERNAL, ["مرافقه الجماهير"], False),
    ("المرور التعقبي",            EXTERNAL, ["المرور التعقبي"], False),
    ("اختبارات كلية الشرطة",      EXTERNAL, ["اختبارات لغه", "كليه الشرطه"], False),
    ("مأمورية إمداد",             EXTERNAL, ["ماموريه امداد"], False),
    ("مأمورية شئون المجندين",     EXTERNAL, ["شئون المجندين"], False),
    ("حجز المجمع الطبي",          EXTERNAL, ["المجمع الطبي"], False),
    ("تأمين مباراة",              EXTERNAL, ["مباراه", "مباريات"], False),
    ("وحدة استاد السويس",         EXTERNAL, ["استاد السويس", "بطوله"], False),
    ("قول مستحدث",                EXTERNAL, ["قول مستحدث"], False),
    ("ارتكاز الحي الحكومي",       EXTERNAL, ["الحي الحكومي"], False),
    ("مرور المدينة",              EXTERNAL, ["مرور المدينه"], False),
    ("تأمين مدرجات الاستاد",      EXTERNAL, ["مدرجات"], False),
    ("تأمين بوابات الاستاد",      EXTERNAL, ["البوابه", "البوابات", "بوابات"], False),
    ("قرعة الحج",                 EXTERNAL, ["قرعه الحج"], False),
    ("ترحيلة",                    EXTERNAL, ["ترحيله"], False),
    # ---------- الخدمات الطبية ----------
    ("العيادة الطبية",            MEDICAL,  ["العياده الطبيه"], False),
]

# مفاتيح المطابقة لازم تتطبّع بنفس تطبيع النص (strip_ar بتحوّل ة→ه و ئ→ي)
CATALOG = [(name, kind, [strip_ar(k) for k in keys], standing)
           for name, kind, keys, standing in CATALOG]

STANDING = {name: standing for name, _, _, standing in CATALOG}

# ٣ الأدوار الدوّارة اللي ليها صف مستقل في لوحة التشغيل المختصرة
BOARD_ROTATIONS = ["نوبتجي المعسكر الفرعي", "ضابط عظيم الإدارة", "ضابط أمن الإدارة"]


def match_services(duty):
    """-> list of (service_name, kind) الموجودة في نص التشغيل."""
    n = strip_ar(duty)
    hits = []
    for name, kind, keys, _standing in CATALOG:
        if any(k in n for k in keys):
            hits.append((name, kind))
    return hits


def catalog_matcher(services):
    """مطابق أسماء الخدمات على الكتالوج المبني من الأرشيف.

    بيطابق بالـaliases بعد التطبيع بدل التطابق الحرفي — التطابق الحرفي هو
    اللي خلّى 711 تكليف يقع في «الصافي»، و«نقطة التفتيش» ما تلاقيش
    «نقطه تفتيش»، و«هدف هلة المحجر» ما تلاقيش نفسها من غير بادئة «عمل ب».
    """
    from backend.text import core_service_name, norm

    index = {}
    for svc in services:
        for alias in set(svc.get("aliases") or []) | {norm(svc["name"])}:
            index.setdefault(alias, svc)

    def resolve(raw):
        if not raw:
            return None
        return index.get(norm(raw)) or index.get(core_service_name(raw))

    return resolve


def _has_shift_word(text):
    n = strip_ar(text)
    # "ليلية"/"صباحية" الكاملة، أو المختصرة "ليل"/"صبح" ("تدخل سريع ليل")
    is_night = bool("ليلي" in n or re.search(r'\bليل\b', n) or re.search(r'\d\s*م\b', n))
    is_morning = bool("صباحي" in n or re.search(r'\bصبح\b', n) or re.search(r'\d\s*ص\b', n))
    return is_night, is_morning


def shift_of(part, whole=None):
    """الفترة من الجزء المخصوص، وإلا من النص كله لو الفترة مذكورة مرة واحدة
    بس آخر الجملة وبتنطبق على كل الأجزاء (مثال: "ضابط عظيم + امن الادارة
    فترة ليلية" — الاتنين ليلية مش الأول بس). لو النص كله فيه صباحية وليلية
    مع بعض، يبقى فعلاً فترتين مختلفتين والافتراضي (صباحية) هو الأسلم."""
    night, morning = _has_shift_word(part)
    if night or morning:
        return NIGHT if night else MORNING
    if whole is not None:
        night, morning = _has_shift_word(whole)
        if night and not morning:
            return NIGHT
        if morning and not night:
            return MORNING
    return MORNING


def split_duty(duty):
    """تقسيم التشغيل لأجزاء عشان كل خدمة تاخد فترتها."""
    return [p for p in re.split(r'\+', duty or "") if p.strip()]


# حالة الضابط من نص التشغيل. الترتيب مهم: «غياب» و«مرضي» و«فرقة» بيغلبوا
# أي كلام تاني في السطر. «مرضي» و«فرقة» كانوا ظاهرين في الأرشيف 16 و30 مرة
# ومكانش فيه أي طريقة توصّلهم لخانتهم في جدول الإجمالي.
STATUS_RULES = [
    ("غياب", ("غياب",)),
    ("مرضي", ("مرضي", "مرضى")),
    ("فرقة", ("فرقه",)),
    ("طارئة", ("جازه طاريه", "اجازه طاريه", "طاريه")),
    ("انتداب", ("انتداب",)),
]
# المنتدب من القطاع الطبي بيتحسب في عمود الطبية مش في الخوارج
_MEDICAL_POSTS = ("العياده الطبيه", "قطاع الخدمات الطبيه", "الخدمات الطبيه")


def status_of(duty, post=""):
    """-> واحدة من حالات الخوارج أو "" لو الضابط شغّال عادي."""
    flat, post_flat = strip_ar(duty), strip_ar(post)
    for status, keys in STATUS_RULES:
        if not any(k in flat for k in keys):
            continue
        if status == "انتداب" and any(k in post_flat for k in _MEDICAL_POSTS):
            return ""
        return status
    return ""


def extract_assignment(row):
    """-> dict {services:[{name,kind,shift}], taqseera:bool}"""
    duty = row.get("duty", "")
    out, seen = [], set()
    for part in split_duty(duty):
        for name, kind in match_services(part):
            if name in seen:
                continue
            seen.add(name)
            out.append({"name": name, "kind": kind, "shift": shift_of(part, duty)})
    # خدمة مذكورة في النص كله من غير ما تتفصل على جزء
    for name, kind in match_services(duty):
        if name not in seen:
            seen.add(name)
            out.append({"name": name, "kind": kind, "shift": shift_of(duty)})
    return {"services": out, "taqseera": "تقصير" in strip_ar(duty)}

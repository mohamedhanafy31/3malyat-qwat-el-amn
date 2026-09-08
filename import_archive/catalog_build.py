#!/usr/bin/env python3
"""يبني كتالوج الخدمات من أرشيف الوورد كله (101 يوم) بدل الـ43 خدمة المكتوبة بالإيد.

ليه: الكتالوج القديم كان 43 خدمة مكتوبة يدويًا من عيّنة صغيرة، والنتيجة إن
**83 خدمة من الـ94 اللي بتتكرر على اللوحة في 3 أيام أو أكتر مكانتش موجودة** —
فـ711 تكليف ضابط عبر الأرشيف كان بيقع في خانة «الصافي» غلط.

المصادر:
  1. لوحة كل يوم (`D.docx`)      → أسماء الخدمات الأساسية والطارئة + تكرارها
  2. يومية الضباط (`D-M-Y.docx`) → نصوص التشغيل، عشان نعرف مين بيشيلها ضابط
  3. `prototype/data/catalog.json` → قوام/تسليح/انتظام/الفترات للخدمات الأساسية
     (مستخرجة قبل كده من يومية الأفراد — الحقول دي مش موجودة في أي مصدر تاني)
  4. `data.json` الحالي           → الـ43 خدمة بأيديها **اللي لازم تفضل زي ما هي**

المخرج: `catalog_seed.json` — يتراجع بالعين، وبعدين
`migrations/001_seed_catalog.py` هو اللي بيطبّقه على data.json.

    python3 catalog_build.py            # يبني ويطبع ملخّص
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from backend.text import core_service_name, norm      # noqa: E402
from common import ROOT, biggest_table, strip_ar      # noqa: E402

PROTO_DATA = HERE.parent.parent / "data"
OUT = HERE / "catalog_seed.json"

RANKS = ("عقيد", "مقدم", "رائد", "نقيب", "م.اول", "م.أول", "ملازم", "لواء", "عميد")
MIN_DAYS = 3        # الخدمة تدخل الكتالوج لو ظهرت في 3 أيام على الأقل

# ---------------------------------------------------------------------------
# أقسام اللوحة زي ما هي مكتوبة في الوورد بالظبط (101 يوم)
# ---------------------------------------------------------------------------
SEC_BASIC = "الخدمات أساسية"
SEC_OCCASIONAL = "الخدمات الطارئة"
SEC_TARGETS = "الأهداف"
SEC_SUBCAMP = "ضابط عظيم وأمن المعسكر الفرعي"
SEC_GREAT = "ضابط عظيم الإدارة"
SEC_SECURITY = "ضابط الأمن بالإدارة"

# المفاتيح بتتحسب بالتطبيع نفسه بدل ما تتكتب بالإيد — أي فرق حرف بين
# الصورتين كان معناه إن عنوان القسم ما يتعرفش وكل صفوفه تتحسب على القسم
# اللي قبله (حصل فعلًا: «الخدمات الطارئة» اتقرت كخدمة 97 مرة).
_BOARD_HEADERS = {strip_ar(k): v for k, v in {
    "الخدمات أساسية": SEC_BASIC,
    "بالخدمات أساسية": SEC_BASIC,
    "الخدمات الطارئة": SEC_OCCASIONAL,
}.items()}
_STOP_HEADERS = tuple(strip_ar(h) for h in (
    "عمل بالإدارة", "الخوارج", "التقصيرات", "الراحات", "الأهداف",
    "ضابط عظيم", "ضابط الأمن", "خدمات سجن قوات الأمن"))

# ---------------------------------------------------------------------------
# دمج صور الاسم الواحد. الأرقام في التعليقات = عدد الأيام اللي ظهرت فيها كل صورة.
# ده الجزء اللي فيه معرفة تشغيلية مش استنتاج آلي: «مستشفي» و«ترحيله مستشفي»
# نفس الخدمة، لكن «مستشفي جنايي» خدمة تانية (وجهة مختلفة).
# ---------------------------------------------------------------------------
MERGE = {
    # حملة الأمن الوطني — 77 + 21
    "حمله امن وطني": "حملة الأمن الوطني",
    "حمله الامن الوطني": "حملة الأمن الوطني",
    "حمله امن وطنى": "حملة الأمن الوطني",
    # الترحيلات — الوورد بيكتب كل وجهة في صف مستقل، فكل وجهة خدمة
    "ترحيله مستشفي": "ترحيلة مستشفى",          # 40
    "مستشفي": "ترحيلة مستشفى",                  # 15
    "ترحيله مسشتفي": "ترحيلة مستشفى",           # 4 (خطأ إملائي في المصدر)
    "ترحيله نيابه عسكريه": "ترحيلة نيابة عسكرية",   # 37
    "نيابه عسكريه": "ترحيلة نيابة عسكرية",          # 30
    "ترحيله عسكريه": "ترحيلة نيابة عسكرية",         # 5
    "ترحيله نيابه عامه": "ترحيلة نيابة عامة",       # 9
    "نيابه عامه": "ترحيلة نيابة عامة",              # 5
    "ترحيله حدث وحريم": "ترحيلة حدث وحريم",         # 19
    "حدث وحريم": "ترحيلة حدث وحريم",                # 14
    "ترحيله جنايي خاصه": "ترحيلة جنائي خاصة",       # 7
    "جنايي خاصه": "ترحيلة جنائي خاصة",              # 7
    "ترحيله جنايي خاص": "ترحيلة جنائي خاصة",        # 3
    "ترحيله طب شرعي": "ترحيلة طب شرعي",             # 5
    "طب شرعي": "ترحيلة طب شرعي",                    # 15
    "ترحيله المطار": "ترحيلة مطار القاهرة",         # 7
    "مطار القاهره": "ترحيلة مطار القاهرة",          # 4
    "ترحيله مطار القاهره": "ترحيلة مطار القاهرة",   # 3
    "ترحيله مستشفي جنايي": "ترحيلة مستشفى جنائي",   # 6
    "مستشفي جنايي": "ترحيلة مستشفى جنائي",          # 11
    "ترحيله مستشفي سياسي": "ترحيلة مستشفى سياسي",   # 5
    "ترحيله بدر": "ترحيلة بدر",
    "تمكين بدر": "ترحيلة بدر",
    "ترحيله الاسماعيليه": "ترحيلة الإسماعيلية",
    "ترحيله العاشر": "ترحيلة العاشر",
    "احضار العاشر": "ترحيلة العاشر",
    "ترحيله القاهره": "ترحيلة القاهرة",
    "ترحيله العباسيه": "ترحيلة العباسية",
    "ترحيله المحكمه": "ترحيلة المحكمة",
    "ترحيله الجيزه": "ترحيلة الجيزة",
    "ترحيله الاسكندريه": "ترحيلة الإسكندرية",
    "ترحيله وادي النطرون": "ترحيلة وادي النطرون",
    "ترحيله 15 مايو": "ترحيلة 15 مايو",
    # الإزالات
    "ازاله الجناين": "إزالة الجناين",
    "ازاله الاربعين": "إزالة الأربعين",
    "ازاله فيصل": "إزالة فيصل",
    # ميدان الأربعين — 15 + 6
    "خدمات ميدان الاربعين": "خدمات ميدان الأربعين",
    "ميدان الاربعين": "خدمات ميدان الأربعين",
    # مأمورية العيادة — 14 + 4
    "ماموريه عياده": "مأمورية العيادة",
    "ماموريه العياده": "مأمورية العيادة",
    # خطة الانتشار — 14 + 3
    "خطه الانتشار": "خطة الانتشار",
    "خطه انتشار": "خطة الانتشار",
    # المسجد الكبير — 5 + 5
    "ارتكاز الجامع الكبير": "ارتكاز المسجد الكبير",
    "المسجد الكبير": "ارتكاز المسجد الكبير",
    # الثانوية
    "توزيع وتجميع وتسفير اوراق الثانويه العامه": "توزيع وتجميع أوراق الثانوية",
    "توزيع وتجميع وتسفير ثانويه عامه": "توزيع وتجميع أوراق الثانوية",
    "توزيع وتجميع وتسفير الثانويه العامه": "توزيع وتجميع أوراق الثانوية",
    "امتحانات الدبلومات الفنيه 5": "امتحانات الدبلومات الفنية",
    "امتحانات الدبلومات الفنيه": "امتحانات الدبلومات الفنية",
    "احضار اسيله الثانويه العامه": "إحضار أسئلة الثانوية العامة",
    "امتحانات الثانويه العامه": "امتحانات الثانوية العامة",
    "تامين كنترول الثانويه": "تأمين كنترول الثانوية",
    "خدمات مقرات امتحانات الثانويه": "خدمات مقرات امتحانات الثانوية",
    "تسفير دبلومات": "تسفير الدبلومات الفنية",
    # المدرجات والاستاد
    "مدرجات الدرجه الاولي": "تأمين مدرجات الاستاد",
    "مدرجات الدرجه الثانيه": "تأمين مدرجات الاستاد",
    "خلف مدرجات الدرجه الثانيه": "تأمين مدرجات الاستاد",
    "المنطقه من الباب حتي مدخل المدرجات": "تأمين مدرجات الاستاد",
    # أسماء موجودة في الكتالوج بإملاء مختلف
    "ارتكاز سينما ريسانس": "ارتكاز سينما ريسنس",
    "ضابط مباحث": "ضابط مباحث السجن العسكري",
    "ماموريه امداد": "مأمورية إمداد",
    "ماموريه شيون مجندين": "مأمورية شئون المجندين",
    "تبه ضرب النار": "تبة ضرب النار",
    "تسفير الازهر": "تسفير الأزهر",
    "كنترول الازهر": "كنترول الأزهر",
    "كنترول الثانويه العامه": "كنترول الثانوية العامة",
    "تدخل سريع": "تدخل سريع",
    "قول مكبر": "قول مكبر",
    "قنصليه": "القنصلية السعودية",
    "ارتكاز الخضر": "ارتكاز الخضر",
    "ارتكاز الحي الحكومي": "ارتكاز الحي الحكومي",
    "تامين السجن العسكري": "تأمين السجن العسكري",
    "قول مستحدث فيصل": "قول مستحدث",
    # باقي المتكرّرات
    "كنيسه العذراء": "كنيسة العذراء",
    "منزل القنصل": "منزل القنصل السعودي",
    "الحمايه المدنيه": "ارتكاز الحماية المدنية",
    "ملاحظه الحاله في مصنع ايماك للورقيات": "ملاحظة الحالة بمصنع إيماك",
    "ملاحظه الحاله بالطرقه ص ل": "ملاحظة الحالة بالطرقة",
    "خدمه باب المحكمه": "خدمة باب المحكمة",
    "وحده المحكمه": "وحدة المحكمة",
    "حجز متهم تابع لقسم فيصل": "حجز متهم بقسم فيصل",
    "مدرسه تعاونيات الصناعيه بنات": "مدرسة تعاونيات الصناعية بنات",
    "الملاك ميخاييل": "كنيسة الملاك ميخائيل",
    "قول الكفور": "قول الكفور",
    "عرب معمل السخنه": "ارتكاز عرب معمل السخنة",
    "طلبه مديريه": "طلبة المديرية",
    "طلبه علاقات المديريه": "طلبة علاقات المديرية",
    "عدد 2وحده احتياطي بقوات الامن": "وحدة احتياطي بقوات الأمن",
    "تمكين امتحان": "تنفيذ قرار تمكين",
    "فرد تامين": "فرد تأمين",
    "فرد تامين فتره ليله": "فرد تأمين",
    "خدمات سجن قوات الامن": "خدمات سجن قوات الأمن",
    "حجز متهم بالمجمع الطبي": "حجز المجمع الطبي",
    # نفس الخدمة باسمين: اللوحة بتكتبها من غير «ال» ويومية الأفراد بيها.
    # من غير الدمج ده بتتعمل خدمتين لنفس الحاجة بأيدي مختلفة.
    "التدخل السريع": "تدخل سريع",
    "القول المكبر": "قول مكبر",
}

# الاسم الرسمي بيطابق نفسه — من غير ده الاسم اللي MERGE بترجّعه ما يتعرفش
# لما يظهر في الوورد بصورته الرسمية («ارتكاز المسجد الكبير» مثلًا).
MERGE.update({core_service_name(v): v for v in set(MERGE.values())})

# خانة جدول الإجمالي لكل خدمة. أي خدمة مش هنا → «خارجية» (خدمة برّه الإدارة).
# ملاحظة: «ضابط مباحث السجن العسكري» بقت **داخلية** مش «بحث» — الدليل من
# يومية 20/8: الضابط كان عليها والوورد حسبه في «الداخلية صباحية» ومكتبش
# «+1 بحث» خالص. وسم «بحث» تابع لجهة تشغيل الضابط مش لنوع الخدمة.
KIND = {
    "داخلية": ["ضابط عظيم الإدارة", "ضابط أمن الإدارة", "نوبتجي المعسكر الفرعي",
               "ضابط أمن المعسكر", "تأمين السجن العسكري", "العمل بالمعسكر الفرعي",
               "ضابط مباحث السجن العسكري", "فرد تأمين", "خدمات سجن قوات الأمن",
               "ملاحظة الحالة بالطرقة"],
    "طبية": ["العيادة الطبية"],
}

TARGETS = ["مشرف الأهداف", "هدف سوميد", "هدف كهرباء السخنة", "هدف عيون موسى",
           "هدف هلة المحجر", "هدف أنابيب البترول", "هدف مصر للبترول",
           "هدف كهرباء عتاقة"]

# الاسم المختصر اللي بيتطبع على اللوحة (الوورد بيكتب «سوميد» مش «هدف سوميد»)
BOARD_LABEL = {
    "هدف سوميد": "سوميد", "هدف كهرباء السخنة": "السخنة",
    "هدف عيون موسى": "عيون موسي", "هدف هلة المحجر": "هلة المحجر",
    "هدف أنابيب البترول": "أنابيب البترول", "هدف مصر للبترول": "مصر للبترول",
    "هدف كهرباء عتاقة": "كهرباء عتاقة", "مشرف الأهداف": "مشرف الأهداف",
    "تدخل سريع": "تدخل سريع", "قول مكبر": "قول مكبر",
}

SECTION_OF = {name: SEC_TARGETS for name in TARGETS}
SECTION_OF.update({
    "ضابط عظيم الإدارة": SEC_GREAT,
    "ضابط أمن الإدارة": SEC_SECURITY,
    "نوبتجي المعسكر الفرعي": SEC_SUBCAMP,
    "العمل بالمعسكر الفرعي": SEC_SUBCAMP,
})


def canonical(raw):
    """الاسم الرسمي للخدمة من أي صورة مكتوبة في الوورد."""
    key = core_service_name(raw)
    return MERGE.get(key), key


# ---------------------------------------------------------------------------
# قراءة الأرشيف
# ---------------------------------------------------------------------------

def board_names():
    """{(القسم، الاسم الخام): مجموعة الأيام} من لوحة كل يوم."""
    hits = defaultdict(set)
    for m, d, folder in _day_dirs():
        path = folder / f"{d}.docx"
        if not path.exists():
            continue
        table = biggest_table(str(path))
        if not table:
            continue
        section = None
        for row in table:
            first = (row[0] if row else "").strip()
            flat = strip_ar(first)
            if flat in _BOARD_HEADERS:
                section = _BOARD_HEADERS[flat]
                continue
            if any(s in flat for s in _STOP_HEADERS):
                section = None
                continue
            if not section or not first or any(r in first for r in RANKS):
                continue
            hits[(section, first)].add(f"2026-{m:02d}-{d:02d}")
    return hits


def duty_texts():
    """كل نصوص «التشغيل اليومي» — عشان نعرف أنهي خدمة بيشيلها ضابط."""
    out = defaultdict(set)
    for m, d, folder in _day_dirs():
        path = folder / f"{d}-{m}-2026.docx"
        if not path.exists():
            continue
        table = biggest_table(str(path))
        for row in (table or [])[1:]:
            if len(row) > 4 and row[4].strip():
                out[row[4].strip()].add(f"2026-{m:02d}-{d:02d}")
    return out


def _day_dirs():
    for month in sorted((p for p in ROOT.iterdir() if p.is_dir() and p.name.isdigit()),
                        key=lambda p: int(p.name)):
        for day in sorted((p for p in month.iterdir() if p.is_dir() and p.name.isdigit()),
                          key=lambda p: int(p.name)):
            yield int(month.name), int(day.name), day


def _clean(value):
    """المصدر بيكتب «//» في الخانة اللي معناها «زي اللي فوق» — دي مش قيمة."""
    v = (value or "").strip()
    return "" if v in {"//", "/", "-", "—", "ــ"} else v


def standing_meta():
    """قوام/تسليح/انتظام/فترات الخدمات الأساسية — مستخرجة قبل كده من يومية الأفراد."""
    raw = json.loads((PROTO_DATA / "catalog.json").read_text(encoding="utf-8"))
    appears = {core_service_name(s["name"]): s.get("appearsIn") or []
               for s in json.loads((PROTO_DATA / "services.json").read_text(encoding="utf-8"))}
    meta = {}
    for entry in raw.get("standing", []):
        key = core_service_name(entry["name"])
        canon = MERGE.get(key)
        # المفتاح لازم يكون على الاسم الرسمي بعد الدمج، مش الخام — «التدخل
        # السريع» بتتدمج في «تدخل سريع»، ولو فضلنا مفهرسين بالخام كان
        # القوام والتسليح والانتظام مايوصلوش للخدمة المدموجة.
        meta[core_service_name(canon) if canon else key] = {
            "default_strength": _clean(entry.get("strength")),
            "default_weapon": _clean(entry.get("weapon")),
            "default_time": _clean(entry.get("time")),
            "shifts": entry.get("shifts") or ["صباحية", "ليلية"],
            "sub": entry.get("sub", ""),
            "needs": {"officer": False, "individual": entry.get("needsIndividual", False),
                      "unit": entry.get("needsUnit", False),
                      "vehicle": entry.get("needsVehicle", False)},
            "appears_in": appears.get(key) or ["afrad", "counts"],
            "name": canon or entry["name"],
        }
    return meta


def addable_meta():
    """فئة المجندين/الساعة/الجهة للخدمات الطارئة — تُستخدم كقيم افتراضية بس."""
    raw = json.loads((PROTO_DATA / "catalog.json").read_text(encoding="utf-8"))
    meta = {}
    for entry in raw.get("addable", []):
        key = core_service_name(entry["name"])
        if key in meta:
            continue
        meta[key] = {
            "default_time": _clean(entry.get("time")),
            "default_weapon": _clean(entry.get("weapon")),
            "party": _clean(entry.get("place")),
            "conscript_class": entry.get("class", ""),
            "conscript_count": entry.get("count", 0),
            "needs": {"officer": bool(entry.get("needsOfficer")),
                      "individual": bool(entry.get("needsIndividual")),
                      "unit": bool(entry.get("needsUnit")),
                      "vehicle": bool(entry.get("needsVehicle"))},
        }
    return meta


_PARTY = re.compile(r'["“”«»]([^"“”«»]+)["“”«»]')
_TIME = re.compile(r'\d{1,2}(?::\d{2})?\s*(?:ص|م|ظ)\b')


def observed_defaults(raw_names):
    """الساعة والجهة زي ما اتكتبوا فعلًا جوّه اسم الخدمة في اللوحة."""
    times, parties = defaultdict(list), defaultdict(list)
    for name in raw_names:
        t = _TIME.search(name)
        if t:
            times[name].append(t.group().strip())
        p = _PARTY.search(name)
        if p:
            parties[name].append(p.group(1).strip())
    return times, parties


# ---------------------------------------------------------------------------
# البناء
# ---------------------------------------------------------------------------

def build():
    existing = json.loads((HERE.parent / "data.json").read_text(encoding="utf-8"))["services"]
    by_core = {core_service_name(s["name"]): s for s in existing}

    board = board_names()
    standing, addable = standing_meta(), addable_meta()

    # اسم رسمي -> {days, sections, aliases, raw}
    merged = defaultdict(lambda: {"days": set(), "sections": defaultdict(int),
                                  "aliases": set(), "raw": set()})

    def add(name, section, days, alias_raw):
        rec = merged[name]
        rec["days"] |= days
        if section:
            rec["sections"][section] += len(days)
        if alias_raw:
            rec["raw"].add(alias_raw)
            rec["aliases"].add(core_service_name(alias_raw))

    # 1) الخدمات القديمة — لازم تفضل كلها، بأيديها
    for svc in existing:
        add(svc["name"], SECTION_OF.get(svc["name"]), set(), None)

    # 2) الخدمات الأساسية من يومية الأفراد
    for key, meta in standing.items():
        add(meta["name"], SEC_BASIC, set(), meta["name"])

    # 3) اللوحة عبر 101 يوم
    unresolved = defaultdict(set)
    for (section, raw), days in board.items():
        name, key = canonical(raw)
        if not name:
            if key in by_core:
                name = by_core[key]["name"]
            elif key in standing:
                name = standing[key]["name"]
            else:
                unresolved[key] |= days
                continue
        add(name, section, days, raw)

    times, parties = observed_defaults({r for _, r in board})

    # ---- تركيب السجلات ----
    kind_of = {n: k for k, names in KIND.items() for n in names}
    out, next_id = [], max(
        (int(s["id"].split("-")[1]) for s in existing if s["id"].startswith("SVC-")), default=0)

    for name, rec in sorted(merged.items(), key=lambda kv: -len(kv[1]["days"])):
        core = core_service_name(name)
        old = by_core.get(core)
        days = len(rec["days"])
        # خدمة جديدة لازم توصل الحد الأدنى؛ القديمة بتفضل مهما كان
        if not old and days < MIN_DAYS and core not in standing:
            continue

        if old:
            svc_id, kind = old["id"], old["kind"]
        else:
            next_id += 1
            svc_id = f"SVC-{next_id:03d}"
            kind = kind_of.get(name, "خارجية")
        if name in kind_of:
            kind = kind_of[name]
        if name in TARGETS:
            kind = "حراسات"

        section = SECTION_OF.get(name)
        if not section:
            section = (max(rec["sections"], key=rec["sections"].get)
                       if rec["sections"] else SEC_OCCASIONAL)

        meta = standing.get(core, {})
        extra = addable.get(core, {})
        aliases = sorted({core} | {a for a in rec["aliases"] if a})

        # في أنهي مستند تظهر الخدمة. الخدمات الجاية من يومية الأفراد ليها
        # قايمتها الأصلية؛ واللي ظهرت على اللوحة بتضيف "board". من غير
        # الحقل ده، الـ22 خدمة بتاعة يومية الأفراد كانت هتتحشر في قسم
        # «الخدمات أساسية» على اللوحة وهي مش بتظهر هناك أصلًا في الوورد.
        appears = list(meta.get("appears_in") or ([] if meta else ["board"]))
        if rec["days"] and "board" not in appears:
            appears.append("board")

        record = {
            "id": svc_id,
            "name": name,
            "board_label": BOARD_LABEL.get(name, name),
            "sub": meta.get("sub", ""),
            "kind": kind,
            "section": section,
            "standing": bool(meta) or (old or {}).get("standing", False),
            "shifts": meta.get("shifts") or ["صباحية", "ليلية"],
            "default_strength": meta.get("default_strength", ""),
            "default_weapon": meta.get("default_weapon") or extra.get("default_weapon", ""),
            "default_time": meta.get("default_time") or extra.get("default_time", ""),
            "party": extra.get("party", ""),
            "needs": meta.get("needs") or extra.get("needs") or {
                "officer": True, "individual": False, "unit": False, "vehicle": False},
            "appears_in": appears,
            "aliases": aliases,
            "seen_days": days,
        }
        out.append(record)

    out.sort(key=lambda s: int(s["id"].split("-")[1]))
    dropped = sorted(((len(d), k) for k, d in unresolved.items() if len(d) >= MIN_DAYS),
                     reverse=True)
    return out, dropped


def main():
    services, dropped = build()
    OUT.write_text(json.dumps(services, ensure_ascii=False, indent=2), encoding="utf-8")

    by_section = defaultdict(int)
    for s in services:
        by_section[s["section"]] += 1
    print(f"=== {len(services)} خدمة في الكتالوج الجديد ===")
    for sec, n in sorted(by_section.items(), key=lambda kv: -kv[1]):
        print(f"  {n:4}  {sec}")
    kinds = defaultdict(int)
    for s in services:
        kinds[s["kind"]] += 1
    print("  الخانات:", dict(kinds))
    print(f"\nاتكتب {OUT}")

    if dropped:
        print(f"\n!! {len(dropped)} اسم ظهر في {MIN_DAYS}+ يوم ومالوش مقابل في MERGE:")
        for n, key in dropped[:30]:
            print(f"   {n:3} يوم  {key}")
        print("   (ضيفهم في MERGE فوق أو سيبهم لو مش خدمات فعلًا)")


if __name__ == "__main__":
    main()

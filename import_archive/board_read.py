#!/usr/bin/env python3
"""قراءة اللوحة (`D.docx`) — الأقسام والصفوف وخانة القوام.

ده اللي بيجيب الجزء الأكبر من اليومية اللي مكانش داخل السيستم خالص:
**1,034 صف خدمات طارئة عبر 101 يوم قوامها أفراد ومجندين من غير أي ضابط**
— 77% من الخدمات الطارئة. الاستيراد القديم كان بيقرا يومية الضباط بس،
فالصفوف دي مكانش ليها أي أثر.

خانة القوام في الوورد نص حر بصور كتير:
    «فرد + مج»                      عدد غير محدد
    «2 فرد + 2 مج»                  بأعداد
    «5 مجند (1 الي + 4 دونك )»      بعدد وتسليح
    «مقدم / طاهر سلطان + وحدة»      ضابط + وحدة
    «أ.ش / محمد سليمان»             فرد بالاسم
    «رائد/ جمال امين  م.اول/ ماركو ماجد»   ضابطين في خانة واحدة
    «6 مجند قسم السويس»             بجهة
    «ضابط من إدارة البحث» / «ــــــ»  شاغرة
"""
import re

from common import strip_ar

OFFICER_RANKS = ("عقيد", "مقدم", "رائد", "نقيب", "لواء", "عميد",
                 "م.اول", "م.أول", "م اول", "ملازم")
PERSONNEL_RANKS = ("أ.ش", "ا.ش", "اش", "م.ش", "م ش", "مش", "امين", "أمين",
                   "معاون", "مساعد", "رقيب", "مراقب", "مندوب", "عريف", "شرطي")

# فئات المجندين زي ما هي مكتوبة في الوورد
CONSCRIPT_CLASSES = {
    "قتاليه": "قتالية", "قتالي": "قتالية", "فض": "فض",
    "حفظ نظام": "حفظ نظام", "رياضي": "رياضي", "طلبه": "طلبة",
}
WEAPONS = ("الي", "آلي", "دونك", "خرطوش", "فيدرال", "كلبش", "مايك", "ميك", "فض")

# الجهة بتتكتب بين علامتي تنصيص أو بعد كلمة «قسم»
_PARTY_QUOTED = re.compile(r'["“”«»]([^"“”«»]{2,20})["“”«»]')
_PARTY_SECTION = re.compile(r'قسم\s+(السويس|فيصل|الجناين|الاربعين|الأربعين|عتاقه|عتاقة)')
_TIME = re.compile(r'\d{1,2}(?::\d{2})?\s*(?:ص|م|ظ)\b')
_VACANT = re.compile(r'^[ـــ\-—\s/]*$')

_PERSON_SPLIT = re.compile(
    r'(?=(?:' + '|'.join(re.escape(r) for r in OFFICER_RANKS + PERSONNEL_RANKS) + r')\s*/)')


def spaced(text):
    """يفصل الرقم عن الكلمة: الوورد بيكتب «2مج» و«2فرد» ملزوقين، والرقم
    والحرف العربي الاتنين \\w فمفيش حد كلمة بينهم — فـ«2مج» مكانتش بتتقري
    كقوام خالص والخانة كانت بتطلع «شاغرة» غلط."""
    return re.sub(r'(\d)(?=[^\W\d_])', r'\1 ', text or "")


def is_vacant(text):
    """«ــــــ» أو خانة فاضية = الخدمة مطلوبة ولسه مالهاش قائم."""
    return bool(_VACANT.match((text or "").strip()))


def split_people(text):
    """يفصل «رائد/ جمال امين  م.اول/ ماركو ماجد» لاسمين."""
    parts = [p.strip(" .+/") for p in _PERSON_SPLIT.split(text or "") if p.strip(" .+/")]
    return [p for p in parts if "/" in p]


def person_entries(text):
    """-> [(نوع, رتبة, اسم)] لكل شخص مذكور بالاسم في الخانة."""
    out = []
    for chunk in split_people(text):
        rank, _, name = chunk.partition("/")
        rank, name = rank.strip(" .ِ"), name.strip(" .ِ")
        # الاسم بيقف عند أول علامة + أو رقم أو كلمة قوام
        name = re.split(r'[+(]|\d', name)[0].strip(" .ِ")
        if not name:
            continue
        flat = strip_ar(rank)
        kind = "officer" if any(strip_ar(r) == flat or flat.startswith(strip_ar(r))
                                for r in OFFICER_RANKS) else "personnel"
        out.append((kind, rank, name))
    return out


def segments(text):
    """التقسيم بيتم على النص الخام قبل التطبيع — strip_ar بتشيل علامة «+»
    اللي هي الفاصل الوحيد بين مجموعات القوام («1 مجند الي + 4 مجند دونك»)."""
    return [s for s in re.split(r'[+،]', spaced(text)) if s.strip()]


def conscripts(text):
    """-> [{class, count}] من نص القوام.

    «5 مجند (1 الي + 4 دونك )» بترجّع العدد الكلي بس — التفصيل اللي جوّه
    القوسين تسليح مش فئة، وبيتقري في weapon().
    """
    out = []
    # التفصيل اللي جوّه القوسين بيتشال لو تسليح («5 مجند (1 الي + 4 دونك)»)،
    # لكن بيفضل لو فيه العدد نفسه («وحدة ( 10 ) مجند»)
    outer = re.sub(r'\(([^)]*)\)',
                   lambda m: " " if weapon(m.group(1)) else m.group(0), spaced(text))
    for part in segments(outer):
        flat = strip_ar(part)
        m = re.search(r'(\d+)?\s*\b(?:مجند|مج)\b', flat)
        if not m:
            continue
        cls = next((label for key, label in CONSCRIPT_CLASSES.items() if key in flat), "")
        out.append({"class": cls, "count": int(m.group(1)) if m.group(1) else 0})
    if not out and re.search(r'\bوحده\b', strip_ar(spaced(text))):
        out.append({"class": "وحدة", "count": 0})
    return out


def individuals_count(text):
    """عدد الأفراد المطلوبين لما يكونوا مذكورين بالعدد مش بالاسم («2 فرد»)."""
    flat = strip_ar(spaced(text))
    total = 0
    for num in re.findall(r'(\d+)?\s*\bفرد\b', flat):
        total += int(num) if num else 1
    return total


def weapon(text):
    flat = strip_ar(spaced(text))
    hits = []
    for w in WEAPONS:
        key = strip_ar(w)
        if key not in hits and re.search(rf'\b{re.escape(key)}\b', flat):
            hits.append(key)          # بالصورة المطبّعة عشان «الي» و«آلي» ما يتكرروش
    # «فض» كلمة فئة وتسليح — بنعدّها تسليح بس لو مفيش كلمة مجند جنبها
    if "فض" in hits and re.search(r'\bمجند\b|\bمج\b', flat):
        hits.remove("فض")
    return " + ".join(hits)


def party(text):
    """الجهة المسؤولة — مش أي كلمة بين علامتي تنصيص: الوورد بيحط فئة
    المجندين برضو بين علامتين («فرد "رياضي"»)."""
    m = _PARTY_QUOTED.search(text or "")
    if m:
        value = m.group(1).strip()
        if strip_ar(value) not in CONSCRIPT_CLASSES:
            return value
    m = _PARTY_SECTION.search(text or "")
    return m.group(1).strip() if m else ""


def time_of(*texts):
    for t in texts:
        m = _TIME.search(t or "")
        if m:
            return m.group().strip()
    return ""

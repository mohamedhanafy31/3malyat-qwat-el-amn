"""اعداد الخدمات اليومية — يومية «اعداد الخدمات الصباحية والمسائية الاساسية»
اللي كانت بتتعمل يدويًا كل يوم في ملف إكسل منفصل (2026/*/*/اعداد الخدمات*.xlsx).

فحصنا 46 ملف حقيقي قبل ما نبني الصفحة دي. النتيجة:
  - بلوك الأساسية (صباحية/ليلية) شبه ثابت: 24-25 خدمة من أصل 26-28 موجودة
    في كل يوم من الـ46 يوم، وعددها بيتغيّر بسيط بس.
  - بلوك الطوارئ يومي بحت: 152 خدمة مختلفة عبر 46 يوم، خدمتين بس (المحكمة
    وكول كورنيش) موجودين كل يوم، وواحدة تالتة (حملة أمن وطني 12ص) في 43
    من 46. الباقي (149 خدمة) نادر ومتغيّر تمامًا.

القرار المبني على ده: الأساسية + التلاتة شبه الثابتين دول بيتسكّنوا في قالب
واحد قابل للتعديل (إضافة/حذف/تغيير عدد)، وبيتفرّد نسخة مستقلة لكل يوم بمجرد
أول تعديل عليه — قبل كده الصفحة بترجّع نسخة حيّة من القالب من غير ما تكتبها.

باقي الطوارئ (اليومي البحت) **مالوش سجل هنا خالص** — الصفوف بتتقرا مباشرة من
قسم «الخدمات الطارئة» في اليومية التفصيلية، وعدد المجندين بيتخزّن على صف
التكليف نفسه (`conscript_count`) مش في نسخة تانية هنا. رقم واحد في مكان واحد،
وأي خدمة طارئة بتتكتب على اللوحة بتظهر هنا على طول.

العدد نفسه ينفع يتكتب من الصفحتين: من خانة الخدمة على اللوحة، أو من الخانة
اللي جنب الخدمة هنا — الاتنين بيكتبوا نفس الحقل. الأول كان بيتكتب من اللوحة
بس، والصف اللي مالوش رقم كان **بيختفي** من الصفحة خالص، فالنتيجة كانت ورقة
طوارئ فاضية في كل يوم من أيام الأرشيف الـ101 رغم إن فيها 1257 خدمة طارئة.

نفس المبدأ بالظبط بيتمدّد لأي **قسم مخصّص** المشغّل كتبه بإيده على اللوحة
لليوم ده بس (زي «خدمات مباراة المصري» ليوم فيه مباراة) — مفيش تسجيل مسبق
لاسم القسم في أي مكان، وأي قسم غير الستة الرسمية بيتحسب هنا تلقائيًا في
بلوكه المستقل بمجرد ما أول صف عليه يتحفظ على اللوحة (`custom_sections`).

اسم الخدمة في القسمين حر بالكامل — مفيش كتالوج تتربط بيه أي خانة هنا.
"""
from .assignments import peek_day as peek_assignments
from .constants import (
    SECTION_BASIC, SECTION_GREAT, SECTION_OCCASIONAL, SECTION_SECURITY,
    SECTION_SUBCAMP, SECTION_TARGETS,
)
from .day_status import status_of
from .store import reserve_id

# الأقسام اللي عددها له مصدر تاني (الأساسية بيها القالب الدائم) أو مش
# «خدمات» أصلًا هنا (الأهداف والكتل التنظيمية الثابتة) — أي قسم غيرهم على
# اللوحة (الطوارئ أو مخصّص) بيتحسب في هذه الصفحة.
_NOT_COUNTABLE_HERE = {SECTION_BASIC, SECTION_TARGETS, SECTION_SUBCAMP,
                       SECTION_GREAT, SECTION_SECURITY}

BLOCKS = ["صباحية", "ليلية", "طوارئ"]

# نقطة انطلاق حقيقية من يومية 5-9-2026 (أقرب يوم كامل اتفحص وقت البناء) —
# مش حقيقة ثابتة، بس بداية تقفل فراغ الصفحة بدل ما تبدأ فاضية. المشغّل
# يعدّل/يضيف/يحذف بعدها زي أي بيانات تانية في السيستم.
DEFAULT_SEED = [
    # (name, block, count, party)
    ("نقطة تفتيش كمين 109 اسفل", "صباحية", 5, ""),
    ("ارتكاز الحي الحكومي", "صباحية", 2, ""),
    ("كنيسة العذراء مريم", "صباحية", 1, "الاربعين"),
    ("اعلى 109", "صباحية", 1, ""),
    ("سيارة تأمين فرع الأمن الوطني", "صباحية", 3, ""),
    ("المحور", "صباحية", 2, ""),
    ("جنيفة", "صباحية", 1, "الطرق"),
    ("القنصلية السعودية", "صباحية", 3, ""),
    ("التدخل السريع", "صباحية", 4, ""),
    ("ام القمر", "صباحية", 1, "الطرق"),
    ("استراحة القنصل", "صباحية", 3, ""),
    ("خط الغاز", "صباحية", 2, ""),
    ("36 لاسلكي", "صباحية", 2, "الطرق"),
    ("مايك المديرية", "صباحية", 1, ""),
    ("قول مكبر", "صباحية", 2, ""),
    ("كنيسة ماري جرجس الصباح", "صباحية", 5, ""),
    ("مبنى المخابرات الحربية", "صباحية", 2, ""),
    ("الاسعاف", "صباحية", 3, ""),
    ("ارتكاز قسم فيصل", "صباحية", 2, ""),
    ("كنيسة الراعي الصالح", "صباحية", 1, "السويس"),
    ("قول السلام", "صباحية", 2, ""),
    ("المركبات", "صباحية", 1, "المركبات"),
    ("قول ممشى بورتوفيق", "صباحية", 1, "السويس"),
    ("المجمع الطبي", "صباحية", 2, "فيصل"),
    ("مستشفى السويس العام", "صباحية", 1, "السويس"),

    ("نقطة تفتيش كمين 109 اسفل", "ليلية", 5, ""),
    ("ارتكاز الحي الحكومي", "ليلية", 2, ""),
    ("مبنى الرقابة الإدارية", "ليلية", 1, ""),
    ("اعلى 109", "ليلية", 1, ""),
    ("سيارة تأمين فرع الأمن الوطني", "ليلية", 3, ""),
    ("قول السلام", "ليلية", 4, ""),
    ("جنيفة", "ليلية", 1, "الطرق"),
    ("القنصلية السعودية", "ليلية", 3, ""),
    ("التدخل السريع", "ليلية", 4, ""),
    ("ام القمر", "ليلية", 1, "الطرق"),
    ("استراحة القنصل", "ليلية", 3, ""),
    ("خط الغاز", "ليلية", 2, ""),
    ("36 لاسلكي", "ليلية", 2, "الطرق"),
    ("مايك المديرية", "ليلية", 1, ""),
    ("قول مكبر", "ليلية", 2, ""),
    ("كنيسة ماري جرجس الصباح", "ليلية", 5, ""),
    ("مبنى المخابرات الحربية", "ليلية", 2, ""),
    ("ارتكاز المحافظة", "ليلية", 1, ""),
    ("ارتكاز قسم فيصل", "ليلية", 2, ""),
    ("كنيسة الراعي الصالح", "ليلية", 1, "السويس"),
    ("كنيسة الإيمان", "ليلية", 1, "الاربعين"),
    ("المركبات", "ليلية", 1, "المركبات"),
    ("قول ممشى بورتوفيق", "ليلية", 1, "السويس"),
    ("الكنيسة الرسولية", "ليلية", 1, "الاربعين"),
    ("المجمع الطبي", "ليلية", 2, "فيصل"),
    ("مستشفى السويس العام", "ليلية", 1, "السويس"),

    ("المحكمة", "طوارئ", 5, ""),
    ("كول كورنيش", "طوارئ", 1, ""),
    ("حملة أمن وطني 12ص", "طوارئ", 4, ""),
]


def _blank_entry(entry_id, block, **over):
    row = {"id": entry_id, "name": "", "block": block,
           "count": 0, "party": "", "weapon": "", "order": 0}
    row.update(over)
    return row


def new_entry_id(data, entries):
    return reserve_id(data, "CNT", entries)


def peek_template(data):
    """قايمة القالب للقراءة المجردة — من غير ما تعمل مدخل جديد لو الملف
    لسه مافيهوش `counts_template` (ملفات قبل الميزة دي)."""
    return (data.get("counts_template") or {}).get("entries", [])


def for_template(data):
    """زي peek_template بس بتحفظ المدخل لو ناقص — للتعديل جوّه with_data() بس."""
    return data.setdefault("counts_template", {}).setdefault("entries", [])


def is_seeded(data):
    return bool(peek_template(data))


def seed_template(data):
    """بيملا القالب أول مرة من نقطة انطلاق حقيقية (DEFAULT_SEED). بيرفض لو
    القالب مش فاضي عشان ما يكرّرش الصفوف أو يمسح تعديلات المشغّل بالغلط."""
    entries = for_template(data)
    if entries:
        return entries
    for i, (name, block, count, party) in enumerate(DEFAULT_SEED):
        entries.append(_blank_entry(new_entry_id(data, entries), block,
                                     name=name, count=count, party=party, order=i))
    return entries


def peek_day_entries(data, day):
    """نسخة عمل اليوم — نسخة من القالب لسه لو اليوم ده مالوش تخصيص محفوظ."""
    stored = (data.get("service_counts") or {}).get(day)
    if stored is not None:
        return stored["entries"]
    return [dict(e) for e in peek_template(data)]


def for_day_entries(data, day):
    """زي peek_day_entries بس بتحفظ نسخة اليوم أول مرة — أي تعديل بعد كده
    بيلمس نسخة اليوم بس، مش القالب ولا أي يوم تاني."""
    store = data.setdefault("service_counts", {})
    if day not in store:
        store[day] = {"entries": [dict(e) for e in peek_template(data)]}
    return store[day]["entries"]


def freeze_past_days(data):
    """بيحفظ نسخة القالب الحالي لكل يوم **مسجّل قبل النهاردة** ومالوش
    نسخة خاصة بيه لسه — لازم تتنادى قبل أي تعديل على القالب نفسه (بذر/
    إضافة/تعديل/حذف صف).

    من غيرها، الصفحة دي كانت باب جانبي بيغيّر شكل أيام اتقفلت وانتهت من
    زمان — رغم إن اليومية التفصيلية نفسها محمية بالقفل (`day_status.
    check_open`) ومحدش قدر يلمسها، تعديل القالب النهاردة كان بيغيّر
    «اعداد الخدمات» المعروضة ليوم فات من غير أي علم لحد راجعه أو
    أكّده بالفعل. بعد التجميد، تعديل القالب بيأثر على النهاردة والأيام
    الجاية بس.
    """
    from .day_status import today_iso
    from .repo import DayRepo

    today = today_iso()
    for day in DayRepo(data).dates():
        if day < today:
            for_day_entries(data, day)


def strength_text(row):
    """قوام الصف زي ما هو مكتوب على اللوحة — تلميح للمشغّل وهو بيكتب العدد،
    **مش رقم بيتحسب**.

    `conscripts` معناه «وحدة / فرد / طلبة» مش «عدد مجندين»: «إزالة الأربعين»
    مكتوب عليها [وحدة ٠، فرد ١] بينما ورقة الإكسل بتقول ٧. فجمعها تلقائيًا
    كان هيدّي رقم غلط وواثق في ورقة بتتطلع للقيادة — الرقم بيتكتب بالإيد،
    والقوام بيتعرض جنبه عشان اللي بيكتبه يبقى شايف الصف كامل.
    """
    bits = []
    officers = len(row.get("officer_ids") or [])
    personnel = len(row.get("personnel_ids") or [])
    if officers:
        bits.append(f"ضابط ×{officers}")
    if personnel:
        bits.append(f"فرد ×{personnel}")
    for con in row.get("conscripts") or []:
        count = int(con.get("count") or 0)
        if count > 0:
            bits.append(f"{con.get('class') or 'مجند'} ×{count}")
    return "، ".join(bits)


def _rows_for(rows):
    """صفوف بلوك محسوب من اللوحة — نفس شكل بلوك الطوارئ بالظبط، مستخدم
    ليه ولأي قسم مخصّص كمان."""
    out = []
    for row in rows:
        count = int(row.get("conscript_count") or 0)
        out.append({
            "assignment_id": row["id"],
            "name": row.get("name", ""), "party": row.get("party", ""),
            "shift": row.get("shift") or "", "count": count,
            "strength": strength_text(row), "needs_count": count <= 0,
        })
    return out


def emergency_rows(data, day):
    """بلوك الطوارئ اليومي — محسوب من اللوحة، مش متخزّن هنا خالص.

    **كل** صف قسمه «الخدمات الطارئة» بيظهر هنا، سواء عليه عدد مجندين أو لأ.
    كان في فلتر بيخفي الصف اللي عدده صفر، فالخدمة اللي المشغّل لسه ما كتبش
    عددها كانت بتختفي من الورقة بدل ما تفكّره إنها ناقصة — والنتيجة ورقة
    طوارئ فاضية تمامًا في كل يوم.
    """
    rows = [r for r in peek_assignments(data, day) if r.get("section") == SECTION_OCCASIONAL]
    return _rows_for(rows)


def custom_sections(data, day):
    """أي قسم كتبه المشغّل بإيده على اللوحة **لليوم ده بس** ومش من الستة
    الرسمية ولا «الخدمات الطارئة» — زي «خدمات مباراة المصري» ليوم فيه
    مباراة. القسم مالوش أي تسجيل مسبق: بيظهر لحظة ما أول صف عليه يتحفظ
    على اللوحة، وبيختفي لوحده لو كل صفوفه اتشالت — مفيش قايمة أقسام
    مخزّنة لازم تتنضّف وراه.

    كل قسم من دول بيتعامل بالظبط زي «الخدمات الطارئة»: عدد المجندين على
    صف التكليف نفسه، والصفحة دي بتجمعه وتسيبه يتعدّل من هنا.
    """
    by_section = {}
    for row in peek_assignments(data, day):
        section = row.get("section") or SECTION_OCCASIONAL
        if section == SECTION_OCCASIONAL or section in _NOT_COUNTABLE_HERE:
            continue
        by_section.setdefault(section, []).append(row)
    return [{"name": name, "rows": _rows_for(rows)} for name, rows in by_section.items()]


def set_board_count(data, day, assignment_id, count):
    """بيكتب عدد المجندين على صف التكليف نفسه — نفس الحقل اللي خانة الخدمة
    على اللوحة بتكتبه. بيشتغل على «الخدمات الطارئة» وأي قسم مخصّص، مش على
    الأساسية ولا الأقسام الثابتة (دول ليهم مصدر عدّهم في مكان تاني).
    بترجّع (row, error)."""
    for row in peek_assignments(data, day):
        if row["id"] == assignment_id:
            section = row.get("section") or SECTION_OCCASIONAL
            if section in _NOT_COUNTABLE_HERE:
                return None, "هذا الصف ليس من الخدمات التي تُحتسب هنا."
            row["conscript_count"] = max(0, int(count))
            return row, None
    return None, "الخدمة غير موجودة في اليومية التفصيلية."


def build(data, day):
    """المخرج الكامل لصفحة اعداد الخدمات — الأساسية والطوارئ شبه الثابتة من
    نسخة عمل اليوم، والطوارئ اليومي وأي قسم مخصّص من اللوحة، مع الإجماليات
    المحسوبة."""
    entries = peek_day_entries(data, day)
    basic_am = [e for e in entries if e["block"] == "صباحية"]
    basic_pm = [e for e in entries if e["block"] == "ليلية"]
    recurring = [e for e in entries if e["block"] == "طوارئ"]
    emergency = emergency_rows(data, day)
    custom = custom_sections(data, day)

    basic_am_total = sum(e["count"] for e in basic_am)
    basic_pm_total = sum(e["count"] for e in basic_pm)
    recurring_total = sum(e["count"] for e in recurring)
    emergency_day_total = sum(r["count"] for r in emergency)
    # الطوارئ في ورقة الإكسل رقم واحد: المتكررة + اليومي مع بعض
    emergency_total = recurring_total + emergency_day_total
    custom_total = sum(r["count"] for sec in custom for r in sec["rows"])
    custom_rows_count = sum(len(sec["rows"]) for sec in custom)

    return {
        "date": day,
        "from_template": (data.get("service_counts") or {}).get(day) is None,
        "locked": bool(status_of(data, day).get("closed")),
        "basic_am": basic_am, "basic_pm": basic_pm,
        "recurring": recurring, "emergency": emergency,
        "emergency_missing": sum(1 for r in emergency if r["needs_count"]),
        # أي قسم كتبه المشغّل بإيده لليوم ده بس، غير الستة الرسمية —
        # قايمة فاضية في الأغلبية الساحقة من الأيام
        "custom_sections": custom,
        # إجمالي المجندين لكل بلوك — `emergency` هو مجموع المتكررة واليومي
        # زي الورقة بالظبط، و`recurring`/`emergency_day` مفكوكين لأن كل
        # واحد منهم بلوك مستقل على الصفحة وله إجمالي تحته. `custom` مجموع
        # كل الأقسام المخصّصة مع بعض — كل قسم منها له بلوكه وإجماليه لوحده.
        "totals": {
            "basic_am": basic_am_total, "basic_pm": basic_pm_total,
            "recurring": recurring_total, "emergency_day": emergency_day_total,
            "emergency": emergency_total, "custom": custom_total,
            "grand_total": basic_am_total + basic_pm_total + emergency_total + custom_total,
        },
        # عدد الخدمات (صفوف) مقابل عدد المجندين — رقمين مختلفين والورقة
        # بتعرضهم مع بعض في كل بلوك
        "services": {
            "basic_am": len(basic_am), "basic_pm": len(basic_pm),
            "recurring": len(recurring), "emergency_day": len(emergency),
            "custom": custom_rows_count,
            "total": (len(basic_am) + len(basic_pm) + len(recurring)
                     + len(emergency) + custom_rows_count),
        },
    }

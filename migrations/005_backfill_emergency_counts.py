#!/usr/bin/env python3
"""تعبئة «عدد المجندين» لخدمات الطوارئ من ملفات إكسل الأرشيف.

الحقل `conscript_count` على صف التكليف اتضاف مع صفحة «اعداد الخدمات»، ومحدش
ملاه ولا مرة — لا الاستيراد من الأرشيف ولا هجرة 004. النتيجة: 1257 خدمة طارئة
في 101 يوم، كلها بصفر، وورقة الطوارئ فاضية في كل يوم.

الأرقام الحقيقية موجودة في 46 ملف `2026/*/*/اعداد الخدمات*.xlsx` — الورق اللي
كان بيتعمل بالإيد كل يوم قبل النظام. الهجرة دي بتقراهم وبتلزّق كل رقم على صف
الخدمة المقابل في `day_assignments`.

المطابقة بالاسم، والأسماء في المصدرين مكتوبة بحرية تامة، فالقاعدة هنا
**التحفّظ**: رقم غلط في ورقة بتطلع للقيادة أسوأ بكتير من خانة فاضية المشغّل
شايفها فاضية. فالهجرة بتكتب بس لما تكون واثقة، وبتسيب الباقي مكتوب بالتفصيل
في تقرير المراجعة:

    حرفية       الاسمين بيتطابقوا بعد التجريد (شيل التشكيل والفترة والساعة
                و«ال» التعريف) — «حملة امن وطني» == «حملة الأمن الوطني»
    حرفية+فترة  نفس الاسم مرتين في اليوم (نوبتين)، والساعة في الورقة
                («12ص»/«12م») بتحدد الصف الصح على اللوحة
    تقريبية     فرق إملائي بس، بثقة >= 0.90 — «ازالة الاريعين» / «إزالة الأربعين»
    احتواء      اسم جوّه التاني ومرشح **واحد** بس — «نيابة عسكرية» جوّه
                «ترحيلة نيابة عسكرية». لو أكتر من مرشح بتتسكت وتتخطى.

أي حاجة برّه الأربعة دول بتتخطى وبتتسجّل في التقرير بالرقم بتاعها عشان
المشغّل يكتبها بإيده من الصفحة.

**ما بتكتبش فوق أي رقم مكتوب بالفعل** — ده اللي بيخليها idempotent: تشغيلة
تانية مالهاش حاجة تكتبها فبتخرج بهدوء.

بتحتاج openpyxl. دي أداة تطوير بتشتغل على جهاز المطوّر مرة واحدة — مش جزء من
التطبيق ولا بتتنقل للجهاز المعزول، فمالهاش علاقة بقيد «stdlib بس».
"""
import difflib
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from common import AlreadyDone, HERE, run

sys.path.insert(0, str(HERE.parent))
from backend.text import core_service_name          # noqa: E402

SECTION = "الخدمات الطارئة"
ARCHIVE = HERE.parent.parent.parent / "2026"        # .../سيستم المعسكر/2026
REPORT = HERE.parent / "تقرير-ترحيل-اعداد-الطوارئ.md"

FUZZY = 0.90            # أقل ثقة مقبولة في المطابقة التقريبية
CONTAIN_RATIO = 0.55    # الاسم الأقصر لازم يكون نص الأطول على الأقل
EMERG_HEAD = "خدمات الطوارئ"


# ---------- قراءة الإكسل ----------

def day_of(path):
    m = re.search(r"(\d{1,2})-(\d{1,2})-(\d{4})", path.name)
    if not m:
        return None
    d, mo, y = m.groups()
    return f"{y}-{int(mo):02d}-{int(d):02d}"


def parse_sheet(path):
    """-> [(الاسم, العدد)] لبلوك الطوارئ، أو None لو البلوك مش موجود.

    الورقة جريد من تلات أزواج (الخدمة / عدد المجندين) جنب بعض، وعمود
    البداية بيختلف من ملف لملف — فالأزواج بتتحدد من صف الترويسة نفسه
    مش بأرقام أعمدة ثابتة.
    """
    import openpyxl

    ws = openpyxl.load_workbook(path, data_only=True).worksheets[0]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]

    head = next((i for i, r in enumerate(rows)
                 if EMERG_HEAD in " ".join(str(c) for c in r if c is not None)), None)
    if head is None:
        return None

    pairs, start = [], None
    for i in range(head + 1, min(head + 4, len(rows))):
        texts = [str(c).strip() if c is not None else "" for c in rows[i]]
        cols = [j for j, t in enumerate(texts) if t == "الخدمة"]
        if cols:
            pairs, start = [(j, j + 1) for j in cols], i + 1
            break
    if not pairs:
        return None

    out = []
    for r in rows[start:]:
        texts = [str(c).strip() if c is not None else "" for c in r + [None] * 8]
        if any(t == "المجموع" for t in texts):
            break
        for a, b in pairs:
            name, raw = texts[a], texts[b]
            if not name or name in ("الخدمة", "عدد المجندين"):
                continue
            try:
                out.append((name, int(float(raw))))
            except (TypeError, ValueError):
                continue
    return out


# ---------- المطابقة ----------

def key_of(name):
    """الاسم المجرّد للمقارنة: بلا تشكيل ولا فترة ولا ساعة ولا «ال» التعريف.

    «ال» بتتشال لأن الورقة بتكتب «حملة امن وطني» واللوحة «حملة الأمن
    الوطني» — نفس الفرق بيتكرر في 60+ صف.
    """
    return re.sub(r"\bال(?=\w)", "", core_service_name(name)).strip()


def shift_hint(name):
    """«12ص» -> صباحية، «12م» -> ليلية.

    الورقة بتفرّق بين نوبتين لنفس الخدمة بالساعة بس، واللوحة بتفرّق
    بينهم بحقل الفترة — فده الجسر الوحيد بينهم.
    """
    m = re.search(r"\d{1,2}(?::\d{2})?\s*(ص|م)\b", name)
    return {"ص": "صباحية", "م": "ليلية"}.get(m.group(1), "") if m else ""


def pick(key, hint, pool):
    """pool = {id: (key, shift)} للصفوف اللي لسه ما اتاخدتش. -> (id, نوع المطابقة)"""
    exact = [i for i, (k, _s) in pool.items() if k == key]
    if len(exact) > 1 and hint:
        narrowed = [i for i in exact if pool[i][1] == hint]
        if len(narrowed) == 1:
            return narrowed[0], "حرفية+فترة"
    if exact:
        return exact[0], "حرفية"

    scored = sorted(((difflib.SequenceMatcher(None, key, k).ratio(), i)
                     for i, (k, _s) in pool.items()), reverse=True)
    if scored and scored[0][0] >= FUZZY:
        return scored[0][1], f"تقريبية {scored[0][0]:.2f}"

    held = [i for i, (k, _s) in pool.items()
            if k and key and (k in key or key in k)
            and min(len(k), len(key)) / max(len(k), len(key)) >= CONTAIN_RATIO]
    if len(held) > 1 and hint:
        held = [i for i in held if pool[i][1] == hint] or held
    if len(held) == 1:
        return held[0], "احتواء"
    return None, "ملتبس — أكتر من مرشح" if held else "مفيش صف مقابل على اللوحة"


# ---------- الهجرة ----------

def migrate(data):
    if not ARCHIVE.exists():
        raise SystemExit(f"مافيش مجلد أرشيف في {ARCHIVE}")
    files = sorted(ARCHIVE.glob("*/*/اعداد الخدمات*.xlsx"))
    if not files:
        raise SystemExit(f"مافيش ملفات إكسل في {ARCHIVE}")

    assignments = data.get("day_assignments", {})
    how = Counter()
    written, skipped, still_zero = [], [], []
    touched_days = set()

    for path in files:
        day = day_of(path)
        sheet = parse_sheet(path)
        if day is None or sheet is None:
            skipped.append((day or path.name, "(الملف كله)", 0, "ما اتقراش"))
            continue

        rows = [r for r in assignments.get(day, []) if r.get("section") == SECTION]
        # الصف اللي عليه رقم بالفعل مابيتلمسش — الهجرة مابتكتبش فوق شغل بني آدم
        pool = {r["id"]: (key_of(r.get("name", "")), r.get("shift") or "")
                for r in rows if not int(r.get("conscript_count") or 0)}
        by_id = {r["id"]: r for r in rows}

        for name, count in sheet:
            rid, kind = pick(key_of(name), shift_hint(name), pool)
            how[kind.split()[0]] += 1
            if not rid:
                skipped.append((day, name, count, kind))
                continue
            by_id[rid]["conscript_count"] = count
            written.append((day, name, by_id[rid].get("name", ""), count, kind))
            touched_days.add(day)
            pool.pop(rid)

        still_zero += [(day, by_id[i].get("name", "")) for i in pool]

    if not written:
        raise AlreadyDone("كل الأرقام اللي الهجرة دي تعرف تلزّقها متلزّقة بالفعل.")

    excel_days = {day_of(p) for p in files}
    no_sheet = sorted(set(assignments) - excel_days)
    _write_report(data, files, written, skipped, still_zero, no_sheet, how)

    total_rows = sum(1 for rs in assignments.values() for r in rs if r.get("section") == SECTION)
    return [
        f"{len(files)} ملف إكسل، {len(written) + len(skipped)} صف طوارئ فيهم",
        f"اتكتب: {len(written)} رقم على {len(touched_days)} يوم",
        *(f"   {k}: {v}" for k, v in how.most_common()),
        f"اتخطّى: {len(skipped)} صف إكسل (مكتوبين بالتفصيل في التقرير)",
        f"فضل بصفر: {len(still_zero)} صف لوحة في أيام ليها إكسل",
        f"{len(no_sheet)} يوم على اللوحة مالوش ملف إكسل أصلًا — كله هيفضل بصفر",
        f"إجمالي صفوف الطوارئ في النظام: {total_rows}",
        f"التقرير: {REPORT.name}",
    ]


def _write_report(data, files, written, skipped, still_zero, no_sheet, how):
    """تقرير مراجعة — كل رقم اتكتب ومنين، وكل رقم ما اتكتبش وليه."""
    by_day = defaultdict(list)
    for day, xl_name, board_name, count, kind in written:
        by_day[day].append((xl_name, board_name, count, kind))
    skip_by_day = defaultdict(list)
    for day, name, count, why in skipped:
        skip_by_day[day].append((name, count, why))
    zero_by_day = defaultdict(list)
    for day, name in still_zero:
        zero_by_day[day].append(name)

    no_board = Counter(core_service_name(n) for _d, n, _c, w in skipped
                       if w.startswith("مفيش صف"))

    lines = [
        "# تقرير ترحيل أعداد خدمات الطوارئ",
        "",
        f"المصدر: {len(files)} ملف إكسل في `2026/`. "
        f"اتكتب **{len(written)}** رقم، واتخطّى **{len(skipped)}**.",
        "",
        "الهجرة بتكتب بس لما تكون واثقة من المطابقة. الصفوف المتخطّاة تحت "
        "مكتوبة بأرقامها — اكتبها من صفحة «اعداد الخدمات» في الخانة اللي "
        "جنب كل خدمة.",
        "",
        "## طريقة المطابقة",
        "",
        "| النوع | العدد |",
        "|---|---|",
        *(f"| {k} | {v} |" for k, v in how.most_common()),
        "",
        "## خدمات في الورقة ومالهاش صف على اللوحة خالص",
        "",
        "دي غالبًا خدمات متكررة مكانها بلوك «طوارئ متكررة» في القالب الدائم، "
        "مش اليومية التفصيلية:",
        "",
        "| الخدمة | كام يوم |",
        "|---|---|",
        *(f"| {n} | {c} |" for n, c in no_board.most_common(20)),
        "",
        f"## أيام على اللوحة مالهاش ملف إكسل ({len(no_sheet)} يوم)",
        "",
        "أعدادها مش موجودة في أي مصدر — لازم تتكتب بالإيد لو محتاجينها:",
        "",
        "`" + "`، `".join(no_sheet) + "`" if no_sheet else "(مفيش)",
        "",
        "## التفصيل يوم بيوم",
        "",
    ]
    for day in sorted(set(by_day) | set(skip_by_day) | set(zero_by_day)):
        lines.append(f"### {day}")
        lines.append("")
        if by_day[day]:
            lines.append("**اتكتب:**")
            lines.append("")
            lines.append("| من الورقة | على اللوحة | العدد | المطابقة |")
            lines.append("|---|---|---|---|")
            for xl, board, count, kind in by_day[day]:
                same = "" if key_of(xl) == key_of(board) else " ⚠"
                lines.append(f"| {xl} | {board}{same} | **{count}** | {kind} |")
            lines.append("")
        if skip_by_day[day]:
            lines.append("**اتخطّى — محتاج يتكتب بالإيد:**")
            lines.append("")
            lines.append("| الخدمة في الورقة | العدد | السبب |")
            lines.append("|---|---|---|")
            for name, count, why in skip_by_day[day]:
                lines.append(f"| {name} | {count} | {why} |")
            lines.append("")
        if zero_by_day[day]:
            lines.append("**صفوف على اللوحة فضلت بصفر:** "
                         + "، ".join(zero_by_day[day]))
            lines.append("")

    REPORT.write_text("\n".join(lines), encoding="utf-8")


run(from_schema=3, to_schema=3, migrate=migrate,
    title="تعبئة عدد مجندين خدمات الطوارئ من إكسل الأرشيف")

#!/usr/bin/env python3
"""معايرة جدول الإجمالي المحسوب مقابل الجدول المكتوب في الوورد.

ده بوابة القبول لقواعد التصنيف في `backend/duty.py`: أي تعديل في ترتيب
الأولوية أو في تصنيفات الكتالوج لازم يعدّي من هنا الأول.

الوورد فيه 22 يوم بجدول إجمالي مكتوب (من 17/8). بس الجدول ده مكتوب
بالإيد، وفيه أيام واضح إنها منسوخة من يوم قبله من غير تحديث — 31/8 مثلًا
مكتوب فيه «غياب 0» رغم إن الصفحة نفسها فيها ضابط تشغيله «غياب». الأيام
دي بتتعلّم «متقادمة» وبتتحسب على جنب بدل ما تلوّث النسبة.

    python3 tools/calibrate_summary.py
    python3 tools/calibrate_summary.py --all      # يعرض الأيام المتقادمة كمان
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "import_archive"))

from backend.duty import summarise                       # noqa: E402
from word_summary import is_stale, word_summaries        # noqa: E402

CELLS = [
    ("خارجية/صباحية", ("خارجية", "صباحية")), ("خارجية/ليلية", ("خارجية", "ليلية")),
    ("خارجية/بحث", ("خارجية", "بحث")),
    ("داخلية/صباحية", ("داخلية", "صباحية")), ("داخلية/ليلية", ("داخلية", "ليلية")),
    ("طبية/موجود", ("طبية", "موجود")), ("طبية/راحة", ("طبية", "راحة")),
    ("خوارج/تقصيرة", ("خوارج", "تقصيرة")), ("خوارج/راحة", ("خوارج", "راحة")),
    ("خوارج/طارئة", ("خوارج", "طارئة")), ("خوارج/غياب", ("خوارج", "غياب")),
    ("خوارج/مرضي", ("خوارج", "مرضي")), ("خوارج/فرقة", ("خوارج", "فرقة")),
    ("خوارج/انتداب", ("خوارج", "انتداب")),
]
SINGLE = [("حراسات", "حراسات"), ("صافي", "صافي"), ("أصل القوة", "أصل القوة")]

TARGETS = {"حراسات": 95, "خارجية/صباحية": 90, "داخلية/صباحية": 90,
           "صافي": 90, "خارجية/بحث": 100}


def main():
    show_all = "--all" in sys.argv
    data = json.loads((ROOT / "data.json").read_text(encoding="utf-8"))
    word = word_summaries()
    if not word:
        raise SystemExit("مش لاقي أي جدول إجمالي في الأرشيف.")

    hits = {name: 0 for name, _ in CELLS + SINGLE}
    total = 0
    stale_days, rows = [], []

    for day in sorted(word):
        computed = summarise(data, day)
        reasons = is_stale(word[day], computed["rows"])
        if reasons:
            stale_days.append((day, reasons))
            continue
        total += 1
        s, w = computed["summary"], word[day]
        line = {"day": day}
        for name, path in CELLS:
            got = s[path[0]][path[1]]
            expected = w.get(name)
            line[name] = (got, expected)
            if expected is None or got == expected:
                hits[name] += 1
        for name, key in SINGLE:
            got, expected = s[key], w.get(name)
            line[name] = (got, expected)
            if expected is None or got == expected:
                hits[name] += 1
        rows.append(line)

    print(f"=== معايرة على {total} يوم سليم "
          f"(من {len(word)} يوم فيهم جدول، و{len(stale_days)} متقادم) ===\n")
    print(f"{'الخانة':22}{'مطابق':>8}{'النسبة':>9}   الهدف")
    worst = []
    for name, _ in CELLS + SINGLE:
        pct = round(100 * hits[name] / total) if total else 0
        target = TARGETS.get(name)
        mark = "" if target is None else ("✓" if pct >= target else "✗")
        print(f"{name:22}{hits[name]:>5}/{total:<3}{pct:>7}%   "
              f"{str(target) + '%' if target else '—':>5} {mark}")
        if target and pct < target:
            worst.append(name)

    if stale_days:
        print(f"\n=== أيام جدولها متقادم في الوورد نفسه ({len(stale_days)}) ===")
        for day, reasons in stale_days:
            print(f"  {day}: {'; '.join(reasons)}")

    if worst:
        print(f"\n=== أكتر الخانات اختلافًا ===")
        for name in worst:
            print(f"\n  {name}:")
            for line in rows:
                got, expected = line[name]
                if expected is not None and got != expected:
                    print(f"    {line['day']}  محسوب {got}  ≠  وورد {expected}")

    if show_all:
        print("\n=== كل يوم ===")
        for line in rows:
            diffs = [f"{n}: {v[0]}≠{v[1]}" for n, v in line.items()
                     if n != "day" and v[1] is not None and v[0] != v[1]]
            print(f"  {line['day']}  " + ("مطابق تمامًا" if not diffs else "، ".join(diffs)))

    return 0 if not worst else 1


if __name__ == "__main__":
    sys.exit(main())

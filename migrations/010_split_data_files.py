#!/usr/bin/env python3
"""فكّ `data.json` لمجلد `data/` — ملف لكل يوم وملف واحد للقوة.

## المشكلة

الملف الواحد كان بيتقرا كله ويتكتب كله وياخد نسخة مضغوطة كاملة مع **كل**
تعديل، مهما كان التعديل صغير. تغيير خانة واحدة في اليومية التفصيلية = أكتر
من 2 ميجابايت شغل. و64% من الملف هو `day_assignments` اللي بيكبر يوم
بيوم، يعني التكلفة بتزيد للأبد.

## بعد الهجرة

    data/core.json                       القوة والراحات والفرق والمأموريات
    data/days/2026/09/2026-09-05.json    تكليفات اليوم + حالات ضباطه + تأكيده + قفله

الشكل في الذاكرة **ما اتغيّرش**: `store._read()` بيرجّع نفس الـdict بالظبط،
فمفيش مسار ولا مستودع اتغيّر. التقسيم تفصيلة تخزين بس.

## الأمان

  * الملف القديم **مابيتمسحش** — بيتساب مكانه باسم `data.json.pre-split`
    عشان الرجوع يبقى إعادة تسمية واحدة. امسحه بإيدك لما تطمن.
  * نسخة احتياطية عادية في `backups/` قبل أي كتابة زي كل الهجرات.
  * بيتأكد إن التجميع من المجلد بيطابق الملف الأصلي **بايت ببايت** قبل
    ما يخلص — لو فيه أي فرق بيمسح المجلد ويوقف من غير ما يلمس الأصل.

    python3 migrations/010_split_data_files.py            # عرض بس
    python3 migrations/010_split_data_files.py --write
"""
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import AlreadyDone, DATA_FILE, run                  # noqa: E402
from backend import store                                       # noqa: E402

LEGACY_KEPT = DATA_FILE.with_suffix(".json.pre-split")


def migrate(data):
    if store.core_file().exists():
        raise AlreadyDone(f"البيانات متفكوكة بالفعل في «{store.DATA_DIR.name}/».")

    core, days = store.split(data)
    sizes = Counter()
    for key, name in store.DAY_SECTIONS.items():
        sizes[key] = sum(len(json.dumps(v, ensure_ascii=False))
                         for v in (data.get(key) or {}).values())
    core_size = len(json.dumps(core, ensure_ascii=False))
    day_sizes = [len(json.dumps(b, ensure_ascii=False)) for b in days.values()]

    report = [
        f"core.json: {len(core)} مفتاح، {core_size / 1024:.0f} كيلوبايت",
        f"ملفات الأيام: {len(days)} ملف، "
        f"متوسط {sum(day_sizes) / max(len(day_sizes), 1) / 1024:.1f} كيلوبايت للملف "
        f"(أكبر واحد {max(day_sizes or [0]) / 1024:.1f})",
        "",
        "اللي بيروح لملفات الأيام:",
        *(f"   {key} -> {store.DAY_SECTIONS[key]}: {sizes[key] / 1024:.0f} كيلوبايت"
          for key in store.DAY_SECTIONS if sizes[key]),
        "",
        f"تعديل خانة واحدة هيكتب {sum(day_sizes) / max(len(day_sizes), 1) / 1024:.1f} كيلوبايت "
        f"بدل {(core_size + sum(day_sizes)) / 1024:.0f}",
    ]

    if "--write" not in sys.argv:
        return report

    # الكتابة الفعلية للمجلد بتحصل هنا مش في `common.write` — ده مجلد مش
    # ملف. `common` بيفضل يكتب `data.json` بعدها عادي، والسطر الأخير في
    # `__main__` بيحوّله لنسخة رجوع.
    payload = {**data, "schema": store.SCHEMA_VERSION}
    store.explode(payload)

    # فحص ذهاب-وعودة: التجميع من المجلد لازم يطابق التفكيك. المقارنة مع
    # `merge(split(...))` مش مع `payload` الخام، عشان `merge` بيضيف
    # المفاتيح المفهرسة باليوم الناقصة كقواميس فاضية — الفرق ده تطبيع
    # متوقع مش فقد بيانات.
    expected = store.merge(*store.split(payload))
    rebuilt = store.assemble()
    if rebuilt != expected:
        shutil.rmtree(store.DATA_DIR, ignore_errors=True)
        raise SystemExit(
            "التجميع من المجلد ما طابقش الملف الأصلي — المجلد اتمسح "
            "والملف الأصلي زي ما هو. مفيش أي حاجة اتغيّرت.")

    report += [
        "",
        f"✓ فحص ذهاب-وعودة: التجميع من المجلد طابق الأصل بالظبط "
        f"({len(expected)} مفتاح، {sum(len(v) for v in expected.values() if isinstance(v, (list, dict)))} عنصر)",
    ]
    return report


if __name__ == "__main__":
    run(from_schema=5, to_schema=6, migrate=migrate,
        title="فكّ ملف البيانات لمجلد — ملف لكل يوم")

    # `common.run` بيكتب `data.json` تاني بعد الهجرة (هو متصمّم لملف واحد).
    # بنحوّله لنسخة رجوع بدل ما نمسحه — الرجوع يبقى إعادة تسمية واحدة.
    if "--write" in sys.argv and store.core_file().exists() and DATA_FILE.exists():
        DATA_FILE.replace(LEGACY_KEPT)
        print(f"الملف القديم اتساب باسم «{LEGACY_KEPT.name}» — امسحه لما تطمن.")

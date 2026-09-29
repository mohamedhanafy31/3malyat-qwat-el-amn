#!/usr/bin/env python3
"""شيل قايمة «ضباط العيادة» الثابتة — تشغيل طبية بقى يوم بيوم.

`data["medical_officers"]` كانت قايمة معرّفات ثابتة: ضابط بيتحط فيها مرة
وبيفضل يتحسب «طبية» في **كل يوم جاي للأبد** من غير أي تكليف يدوي — يعني
تشغيله بيتحدد للشهر (والسنة) كله دفعة واحدة بدل يوم بيوم. طلب المستخدم
كان تحديدًا إن التشغيل ده يبقى يوم بيوم من يومية الضباط.

دلوقتي التحديد اليدوي بقى `day_officers[day][officer_id]["medical"]` —
حقل زي `taqseera` بالظبط، بيتحط لليوم ده بس من نموذج «حالة الضابط» في
يومية الضباط. الاكتشاف التلقائي (منصبه الفعّال، أو خدمته لو تصنيفها
«طبية») **فضل زي ما هو** — هو أصلًا يوم بيوم من زمان.

## ليه محتاجة Backfill

الأيام اللي ليها يومية مسجّلة بالفعل كانت بتتحسب «طبية» بسبب القايمة
الثابتة. لو القايمة اتشالت من غير backfill، إعادة فتح يومية قديمة
هتغيّر نتيجتها بأثر رجعي — نفس المشكلة اللي القايمة الثابتة كانت بتعملها
بس بالعكس. فالهجرة دي بتحط `medical: true` صراحةً على كل يوم-ضابط كان
طبية **بسبب القايمة تحديدًا** (مش بسبب منصبه أو خدمته — دول أصلًا هيفضلوا
صح من غيرها)، وبعدين تشيل القايمة.

الأيام الجايه (اللي لسه ملهاش يومية) **مابتاخدش** أي تحديد — ده بالظبط
السلوك الجديد المطلوب: لازم تحديد يدوي لكل يوم بدل ما يتورّث تلقائي.

    python3 migrations/011_daily_medical_flag.py            # عرض بس
    python3 migrations/011_daily_medical_flag.py --write
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import AlreadyDone, run                          # noqa: E402

from backend.assignments import assignments_of                # noqa: E402
from backend.people import effective, officers_on             # noqa: E402
from backend.text import norm                                 # noqa: E402

# نسخة محليّة — `backend.duty.is_medical_post`/`backend.constants.MEDICAL_POSTS`
# اتشالوا لصالح منصب «طبي» في قيادة الإدارة (هجرة لاحقة). الهجرة دي سجل
# تاريخي بيوثّق حالة السيستم وقت ما اتنفّذت، فبتفضل مستقلة عن تطوّر الكود
# بعد كده بدل ما تنكسر لما الدالة تتشال.
_MEDICAL_POSTS = ("العياده الطبيه", "قطاع الخدمات الطبيه", "الخدمات الطبيه")


def _is_medical_post(post):
    flat = norm(post)
    return any(key in flat for key in _MEDICAL_POSTS)


def _set_daily_medical_flag(data, day, officer_id):
    """نسخة محليّة من `backend.assignments.set_officer_state(..., medical=True)`
    بعد ما الحقل ده اتشال من الدالة المشتركة — الهجرة دي بتوثّق شكله وقتها."""
    entry = dict(data.setdefault("day_officers", {}).setdefault(day, {}).get(officer_id) or {})
    entry["medical"] = True
    data["day_officers"][day][officer_id] = entry


def migrate(data):
    if "medical_officers" not in data:
        raise AlreadyDone("مفيش قايمة ضباط عيادة ثابتة — اتشالت قبل كده.")

    medical_ids = set(data.get("medical_officers") or [])
    days = sorted(set(data.get("day_assignments") or {})
                  | set(data.get("day_officers") or {}))

    backfilled = 0
    touched_officers = set()
    for day in days:
        if not medical_ids:
            break
        for officer in officers_on(data, day):
            oid = officer["id"]
            if oid not in medical_ids:
                continue
            eff = effective(officer, day)
            kinds = [(it.get("kind") or "خارجية", it.get("shift", ""))
                     for it in assignments_of(data, day, oid)
                     if it.get("counts_in_summary", True)]
            # لو أصلًا طبية من منصبه أو خدمته النهاردة، مفيش داعي لتحديد
            # يدوي — الاكتشاف التلقائي هيفضل يحسبه صح من غير القايمة.
            if _is_medical_post(eff["post"]) or any(k == "طبية" for k, _ in kinds):
                continue
            _set_daily_medical_flag(data, day, oid)
            backfilled += 1
            touched_officers.add(oid)

    data.pop("medical_officers", None)

    report = [f"اتشالت القايمة الثابتة ({len(medical_ids)} ضابط): "
             f"{', '.join(sorted(medical_ids)) or '—'}."]
    if backfilled:
        report.append(f"اتحط تحديد يدوي «طبية» على {backfilled} يوم-ضابط "
                      f"({len(touched_officers)} ضابط) عشان الأيام المسجّلة "
                      f"تفضل بنفس النتيجة المحسوبة قبل الهجرة.")
    else:
        report.append("مفيش يوم احتاج تحديد يدوي — كل الأيام المسجّلة كانت "
                      "أصلًا طبية من المنصب أو الخدمة.")
    report.append("أي يوم جديد بعد كده محتاج تحديد يدوي من يومية الضباط.")
    return report


if __name__ == "__main__":
    run(from_schema=6, to_schema=6, migrate=migrate,
        title="شيل قايمة ضباط العيادة الثابتة — تشغيل طبية بقى يوم بيوم")

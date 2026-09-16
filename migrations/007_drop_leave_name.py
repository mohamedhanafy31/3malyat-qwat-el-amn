#!/usr/bin/env python3
"""شيل `name` المكرّر من سجلات الراحة.

اسم صاحب الراحة كان متخزّن **جوّه** كل سجل راحة، جنب `person_id` اللي
بيشاور على نفس الشخص. نفس الحقيقة في مكانين، والنتيجة المعروفة: أي تعديل
اسم في صفحة القوة بيسيب كل الراحات القديمة بالاسم القديم.

الكود كان بيعالج ده بكتلة في `PATCH /api/person/<id>` بتمشي على كل راحات
الشخص وتحدّث الاسم فيها. ده علاج للعرض مش للسبب: بيشتغل بس لما التعديل
يعدّي من المسار ده بالظبط، وأي استيراد أو هجرة أو سكربت بيغيّر اسم بيسيب
الراحات قديمة من غير ما حد ياخد باله.

دلوقتي الاسم بيتحلّ من `person_id` وقت القراءة (`LeaveRepo.named`) فهو
صحيح دايمًا بالتعريف، والحقل المخزّن مابقاش له لازمة.

**الواجهة ما بتتغيّرش**: `/api/bootstrap/leaves` وكل نقاط الراحات لسه
بترجّع `name` في الاستجابة — بيتحسب بدل ما يتقرا.

قبل الكتابة بيتأكد إن كل سجل راحة `person_id` بتاعه موجود فعلًا في
القوة، عشان ما يشيلش اسم مالوش بديل يتحلّ منه.

    python3 migrations/007_drop_leave_name.py            # عرض بس
    python3 migrations/007_drop_leave_name.py --write
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import AlreadyDone, run                      # noqa: E402


def migrate(data):
    leaves = data.get("leaves") or []
    carrying = [lv for lv in leaves if "name" in lv]
    if not carrying:
        raise AlreadyDone("مفيش سجل راحة شايل `name` — اتشال قبل كده.")

    people = {p.get("id"): p.get("name", "")
              for cat in ("officers", "personnel")
              for bucket in ("active", "archive")
              for p in (data.get(cat) or {}).get(bucket, [])}

    # أي راحة مالهاش شخص موجود هتفقد الاسم من غير بديل — الهجرة بتقف
    orphans = [lv for lv in carrying if lv.get("person_id") not in people]
    if orphans:
        raise SystemExit(
            f"في {len(orphans)} سجل راحة بيشاور على شخص مش موجود "
            f"({', '.join(lv.get('id', '?') for lv in orphans[:5])}...). "
            f"شغّل tools/check_integrity.py وصلّحهم الأول — من غير كده "
            f"الأسماء دي هتضيع من غير بديل يتحلّ منه."
        )

    stale = 0
    for leave in carrying:
        stored = leave.pop("name", "")
        if stored and stored != people.get(leave.get("person_id"), ""):
            stale += 1

    report = [f"اتشال `name` من {len(carrying)} سجل راحة.",
              f"الاسم بقى بيتحلّ من `person_id` وقت القراءة ({len(people)} شخص في الفهرس)."]
    if stale:
        report.append(f"منهم {stale} سجل كان شايل اسم **قديم** مختلف عن اسم صاحبه "
                      f"الحالي — دول كانوا بيتعرضوا غلط في الصفحة.")
    return report


if __name__ == "__main__":
    run(from_schema=3, to_schema=4, migrate=migrate,
        title="شيل الاسم المكرّر من سجلات الراحة")

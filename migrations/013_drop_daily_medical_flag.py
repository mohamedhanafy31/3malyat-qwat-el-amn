#!/usr/bin/env python3
"""شيل التحديد اليدوي اليومي «طبية» — تشغيل العيادة بقى منصب في قيادة الإدارة.

`day_officers[day][officer_id]["medical"]` كان تحديد يدوي لليوم ده بالذات
(هجرة 011)، جنب فحص نص حر على منصب الضابط (`MEDICAL_POSTS`). الاتنين
اتشالوا لصالح منصب «طبي» الجماعي في قيادة الإدارة — أعضاء ثابتين
(`PATCH /api/command-groups`، أكتر من ضابط ممكن يشيلوه في نفس الوقت) بدل
تحديد يوم بيوم.

الحقل القديم بقى **ميت**: `backend/duty.py::summarise` مابيقراهوش خالص
بعد كده، فبقاؤه في الملف مايأثرش على أي حساب، لكنه بيفضل زبالة بتكبّر
الملف من غير فايدة. الهجرة دي بتشيله بس.

    python3 migrations/013_drop_daily_medical_flag.py            # عرض بس
    python3 migrations/013_drop_daily_medical_flag.py --write
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import AlreadyDone, run                      # noqa: E402


def migrate(data):
    touched_days = 0
    touched_officers = 0
    removed_entries = 0

    for day, states in (data.get("day_officers") or {}).items():
        day_touched = False
        for officer_id, entry in list(states.items()):
            if "medical" not in entry:
                continue
            entry.pop("medical", None)
            touched_officers += 1
            day_touched = True
            if not any((entry.get("taqseera"), entry.get("status"), entry.get("note"))):
                states.pop(officer_id, None)
                removed_entries += 1
        if day_touched:
            touched_days += 1

    if not touched_officers:
        raise AlreadyDone("مفيش حقل «medical» يدوي في أي يوم — اتشال قبل كده.")

    return [
        f"اتشال الحقل اليدوي «medical» من {touched_officers} يوم-ضابط عبر {touched_days} يوم.",
        f"من ضمنهم {removed_entries} سجل يوم-ضابط اتشال بالكامل لأنه بقى فاضي من غير الحقل ده.",
        "تشغيل العيادة الطبية بقى منصب «طبي» في قيادة الإدارة"
        " (كرت «قيادة الإدارة» في صفحة الضباط) — حدّده من هناك.",
    ]


if __name__ == "__main__":
    run(from_schema=6, to_schema=6, migrate=migrate,
        title="شيل التحديد اليدوي اليومي «طبية» — بقى منصب في قيادة الإدارة")

#!/usr/bin/env python3
"""تسمية هدف «السخنة» بالاسم الكامل «كهرباء السخنة».

قايمة الأهداف الثابتة الثمانية (`backend/constants.py::TARGET_NAMES`) بُنيت
من اسم الخدمة زي ما كان مكتوب على اللوحة في الأرشيف — و«السخنة» كان
الاسم المتكرر 93 مرة من غير أي اختلاف. لكن منصب قائد الهدف الثابت مسجّل
«قائد هدف كهرباء السخنة» (وقائد تاني بنفس الاسم بفرق حرف: «كهرباء السخنه»).

الاسمين ما كانوش بيتطابقوا: `_target_commanders` بتقارن اسم اللوحة بعد
شيل «قائد هدف» من المنصب، و«السخنة» ≠ «كهرباء السخنة» — فقائد الهدف كان
بيظهر فاضي دايمًا لهدف السخنة تحديدًا، رغم إن المنصب مسجّل صح.

الهجرة دي بترحّل كل صف قديم اسمه «السخنة» في قسم «الأهداف» للاسم الكامل
«كهرباء السخنة» — نفس التطبيع (`text.norm`) هيقارنه صح بعد كده مع الاتنين
(«كهرباء السخنة» و«كهرباء السخنه») زي أي اختلاف كتابة عربي تاني في النظام.

    python3 migrations/012_rename_sakhna_target.py            # عرض بس
    python3 migrations/012_rename_sakhna_target.py --write
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import AlreadyDone, run                      # noqa: E402
from backend.constants import SECTION_TARGETS            # noqa: E402

OLD_NAME = "السخنة"
NEW_NAME = "كهرباء السخنة"


def migrate(data):
    touched = []
    for day, rows in (data.get("day_assignments") or {}).items():
        for row in rows:
            if row.get("section") == SECTION_TARGETS and row.get("name") == OLD_NAME:
                row["name"] = NEW_NAME
                touched.append(day)

    if not touched:
        raise AlreadyDone(f"مفيش صف باسم «{OLD_NAME}» في قسم الأهداف — اترحّل قبل كده.")

    return [
        f"اتغيّر اسم «{OLD_NAME}» لـ«{NEW_NAME}» في {len(touched)} يوم.",
        "قائد الهدف كان بيظهر فاضي لهدف السخنة تحديدًا لأن الاسمين ما"
        " كانوش متطابقين — دلوقتي هيتطابق صح.",
    ]


if __name__ == "__main__":
    run(from_schema=6, to_schema=6, migrate=migrate,
        title="تسمية هدف «السخنة» بالاسم الكامل «كهرباء السخنة»")

#!/usr/bin/env python3
"""شيل كتالوج الخدمات الميت — 416 سجل، 13% من حجم الملف.

الكتالوج كان جدول تعريفات للخدمات بـ17 حقل، والصفوف في اليومية كانت
بتشاور عليه بـ`service_id`. هجرة 004 فكّت الارتباط ده: الاسم والتصنيف
بقوا مكتوبين على صف التكليف نفسه، وصفحة الكتالوج والمسار بتاعه اتحذفوا.

اللي فضل هو الجدول نفسه: 416 سجل مافيش ولا سطر كود بيقراهم.

    $ grep -rn 'data\\["services"\\]' backend/
    backend/store.py:131:    data.setdefault("services", [])

`ServiceRepo` كان الوحيد اللي بيلفّه، وهو نفسه مالوش مستدعي — بيتشال مع
`models/service.py` في نفس الـcommit.

مش مجرد ترتيب: 187 كيلوبايت بتتسلسل مع **كل** عملية حفظ وبتتنقل في كل
نسخة احتياطية للأبد. وبعد تقسيم التخزين لمجلد (هجرة 010) الحمل ده كان
هيفضل في `core.json` اللي المفروض يبقى أخف ملف في النظام.

لو رجعت تحيي الكتالوج بعدين: التعريفات موجودة في نسخة
`backups/data-*-pre-migration.json` اللي الهجرة دي بتعملها قبل ما تكتب،
وكمان في كل نسخة أقدم من كده.

    python3 migrations/009_drop_service_catalog.py            # عرض بس
    python3 migrations/009_drop_service_catalog.py --write
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import AlreadyDone, run                      # noqa: E402

KEY = "services"


def migrate(data):
    if KEY not in data:
        raise AlreadyDone("الكتالوج مشال من الملف قبل كده.")

    catalog = data[KEY]
    if not isinstance(catalog, list):
        raise SystemExit(f"«{KEY}» مش قايمة — اتوقف من غير ما يتغيّر حاجة.")

    # فحص أمان: لو لسه فيه صف تكليف بيشاور على الكتالوج، الهجرة دي بدري
    still_linked = sum(
        1 for rows in (data.get("day_assignments") or {}).values()
        for row in rows if row.get("service_id"))
    if still_linked:
        raise SystemExit(
            f"لسه فيه {still_linked} صف تكليف عليه `service_id`. "
            f"شغّل migrations/004_inline_service_fields.py الأول.")

    import json
    size = len(json.dumps(catalog, ensure_ascii=False))
    data.pop(KEY)
    return [
        f"اتشال «{KEY}» — {len(catalog)} سجل، {size / 1024:.0f} كيلوبايت.",
        "مفيش أي صف تكليف بيشاور عليه (اتفحص قبل المسح).",
        "التعريفات القديمة موجودة في النسخة الاحتياطية تحت لو احتجتها.",
    ]


if __name__ == "__main__":
    run(from_schema=5, to_schema=5, migrate=migrate,
        title="شيل كتالوج الخدمات الميت")

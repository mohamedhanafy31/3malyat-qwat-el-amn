#!/usr/bin/env python3
"""شيل مفتاح `handovers` الميت من ملف البيانات.

المفتاح ده اتضاف وقت ما كانت فكرة «تسليم واستلام النوبتجية» متخطّط ليها،
وما اتنفذتش. النتيجة: قايمة فاضية بتتقري وتتكتب مع كل عملية حفظ ومفيش ولا
سطر كود بيلمسها — لا في `backend/`، ولا `templates/`، ولا `static/`.

    $ grep -rn "handovers" backend/ templates/ static/
    (مفيش نتايج)

مش مجرد ترتيب: `store._write()` بيسلسل كل مفتاح في الـdict مع كل حفظ،
والمفاتيح الميتة بتفضل تتنقل في كل نسخة احتياطية للأبد، وبتخلي أي حد
بيقرا الملف عشان يفهم البنية يدوّر على الكود اللي بيستخدمها ومايلاقيش.

الشكل مابيتغيّرش (`schema` ثابت على 3) — ده تنضيف بيانات مش هجرة بنية،
فالكود القديم والجديد الاتنين بيشتغلوا على الملف قبل وبعد.

    python3 migrations/006_drop_handovers.py            # عرض بس
    python3 migrations/006_drop_handovers.py --write
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import AlreadyDone, run                      # noqa: E402

DEAD_KEYS = ["handovers"]


def migrate(data):
    found = [k for k in DEAD_KEYS if k in data]
    if not found:
        raise AlreadyDone("مفيش مفاتيح ميتة في الملف — اتشالت قبل كده.")

    report = []
    for key in found:
        value = data.pop(key)
        size = len(value) if isinstance(value, (list, dict)) else "—"
        report.append(f"اتشال المفتاح «{key}» (كان فيه {size} عنصر).")
    return report


if __name__ == "__main__":
    run(from_schema=3, to_schema=3, migrate=migrate,
        title="شيل المفاتيح الميتة من ملف البيانات")

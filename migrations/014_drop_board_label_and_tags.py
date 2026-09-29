#!/usr/bin/env python3
"""شيل «الاسم على اللوحة» (`label_override`) و«الوسوم» (`tags`) من خدمات اليومية.

الحقلين اتشالوا من نافذة الخدمة ومن الكود كله: الخدمة بتتعرض باسمها بس،
ومفيش عناوين فرعية بالوسوم جوّه القسم. الهجرة دي بتشيلهم من كل صف في
`day_assignments` ومن لقطات التأكيد (`day_confirm[day]["rows"]`)، عشان
مايفضلش في الملفات حقل ميت.

وسوم «دليل الخدمات» (`service_catalog[].tags` والقايمة العامة
`service_tags`) حاجة تانية خالص — فلاتر الدليل — ومش بتتلمس هنا.

    python3 migrations/014_drop_board_label_and_tags.py            # عرض بس
    python3 migrations/014_drop_board_label_and_tags.py --write
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import AlreadyDone, run                      # noqa: E402

FIELDS = ("label_override", "tags")


def _strip(rows):
    """-> (عدد الصفوف اللي اتلمست، عدد الصفوف اللي كان فيها قيمة فعلية)."""
    touched = filled = 0
    for row in rows or []:
        present = [key for key in FIELDS if key in row]
        if not present:
            continue
        if any(row.get(key) for key in present):
            filled += 1
        for key in present:
            row.pop(key)
        touched += 1
    return touched, filled


def migrate(data):
    rows = filled = days = 0
    for day_rows in (data.get("day_assignments") or {}).values():
        touched, with_value = _strip(day_rows)
        rows += touched
        filled += with_value
        days += bool(touched)

    snapshot_rows = 0
    for entry in (data.get("day_confirm") or {}).values():
        touched, with_value = _strip((entry or {}).get("rows"))
        snapshot_rows += touched
        filled += with_value

    if not rows and not snapshot_rows:
        raise AlreadyDone("مفيش «label_override» ولا «tags» على أي خدمة — اتشالوا قبل كده.")

    return [
        f"اتشال الحقلين من {rows} خدمة عبر {days} يوم، ومن {snapshot_rows} صف في لقطات التأكيد.",
        f"منهم {filled} صف كان فيه قيمة فعلية (اسم على اللوحة أو وسم).",
        "وسوم دليل الخدمات ماتلمستش.",
    ]


if __name__ == "__main__":
    run(from_schema=6, to_schema=6, migrate=migrate,
        title="شيل الاسم على اللوحة والوسوم من خدمات اليومية")

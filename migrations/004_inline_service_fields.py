#!/usr/bin/env python3
"""بيشيل الاعتماد على كتالوج الخدمات من صفوف اليومية التفصيلية.

القرار (طلب مباشر من المشغّل): الكتالوج معقّد أكتر من اللازم لمرحلة
النظام دي — 17 حقل تعريف لكل خدمة كان شكله متضخّم في الاستخدام الفعلي.
هيتبنى بشكل أبسط لاحقًا، لكن دلوقتي بيتشال من السيستم خالص، واسم الخدمة
بقى نص حر بيكتبه المشغّل على الخانة نفسها في اليومية التفصيلية.

كل صف في `day_assignments` كان بيشاور على خدمة بالـ`service_id`، والاسم
والتصنيف (kind) والتسليح/الانتظام/الجهة الافتراضيين كانوا بييجوا من
الكتالوج وقت العرض بس. الهجرة دي بتاخد أحدث نسخة من كل حقل ده وتكتبها
**مباشرة على الصف نفسه**، عشان الـ2904 صف الحقيقي في الأرشيف يفضلوا
معروضين بنفس الشكل بالظبط بعد ما الكتالوج يتشال من الكود.

`services[]` نفسها **بتفضل في الملف من غير ما تتمسح** — مرجع تاريخي بس،
مفيش كود بيقراها تاني بعد الهجرة دي.

    python3 004_inline_service_fields.py            # عرض بس
    python3 004_inline_service_fields.py --write
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import AlreadyDone, run      # noqa: E402


def migrate(data):
    assignments = data.get("day_assignments") or {}
    any_row = next((a for day in assignments.values() for a in day), None)
    if any_row is not None and "name" in any_row and "service_id" not in any_row:
        raise AlreadyDone("الصفوف متهاجرة بالفعل — مفيش service_id ولا حاجة تتعمل.")

    services = {s["id"]: s for s in data.get("services", [])}
    migrated, orphaned = 0, 0

    for day, rows in assignments.items():
        for row in rows:
            if "service_id" not in row:
                continue
            svc = services.get(row.pop("service_id"))
            if svc:
                name = svc.get("board_label") or svc.get("name") or ""
                if svc.get("sub"):
                    name = f"{name} | {svc['sub']}"
                row["name"] = name
                row["kind"] = svc.get("kind", "خارجية")
                row["counts_in_summary"] = svc.get("counts_in_summary", True)
                row["weapon"] = row.get("weapon") or svc.get("default_weapon", "")
                row["time"] = row.get("time") or svc.get("default_time", "")
                row["party"] = row.get("party") or svc.get("party", "")
            else:
                # نظريًا مايحصلش — حذف خدمة مستخدمة ممنوع أصلًا — بس لو حصل
                # بأي طريقة تانية، الصف يفضل ظاهر باسم واضح بدل ما يختفي
                row["name"] = row.get("name") or "(خدمة غير معروفة)"
                row["kind"] = row.get("kind") or "خارجية"
                row["counts_in_summary"] = True
                orphaned += 1
            row.setdefault("conscript_count", 0)
            migrated += 1

    report = [f"اتهاجر {migrated} صف تكليف من service_id لاسم/تصنيف مباشر."]
    if orphaned:
        report.append(f"تحذير: {orphaned} صف كان بيشاور على خدمة محذوفة من الكتالوج.")
    report.append(f"services[] فضلت في الملف كمرجع تاريخي ({len(services)} خدمة) — مفيش كود بيقراها تاني.")
    return report


if __name__ == "__main__":
    run(from_schema=3, to_schema=3, migrate=migrate,
        title="شيل الاعتماد على كتالوج الخدمات من day_assignments")

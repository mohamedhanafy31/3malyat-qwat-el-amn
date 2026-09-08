#!/usr/bin/env python3
"""هجرة 2 → 3: سجل تكليف واحد بدل سجلّين لنفس الحقيقة.

قبل كده كان فيه مخزنين لنفس الجملة «فلان على الخدمة دي النهاردة»:

    duties[day][officer] = {items:[{service_id, shift}], taqseera, status, note}
    day_services[day]    = [{category, service: "نص", shift, officer_id, officer_name}]

الأول بالـid والتاني باسم الخدمة كنص، ومربوطين بجسر `{اسم: خدمة}` في
sync.py. الأخطاء المقيسة اللي طلعت من ده:
  - إعادة تسمية خدمة كانت تمسح التكليف من يومية التشغيل بالسكوت
  - إزالة تكليف كانت تسيب اسم الضابط ظاهر على اللوحة (officer_name)
  - 128 ضابط بيختفوا من اللوحة في 65 يوم (خانة واحدة لكل اسم+فترة)
  - 1,034 صف خدمات طارئة بقوام أفراد ومجندين مستحيل تمثيلها

بعد الهجرة:

    day_assignments[day] = [{id, section, service_id, shift, officer_ids, ...}]
    day_officers[day][officer] = {taqseera, status, note}

والتاني **مش تكرار** — دي حالة الضابط نفسه، حقيقة مختلفة عن التكليف.

    python3 002_assignments.py           # عرض بس
    python3 002_assignments.py --write
"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.assignments import blank, clean_shift, new_id, resolve_service  # noqa: E402
from backend.constants import SECTION_OCCASIONAL                            # noqa: E402
from common import run                                                      # noqa: E402

LEGACY_KEYS = ("duties", "day_services", "board_categories")


def migrate(data):
    services = {s["id"]: s for s in data["services"]}
    duties = data.get("duties") or {}
    boards = data.get("day_services") or {}

    day_assignments, day_officers = {}, {}
    stats = Counter()
    unresolved = Counter()

    for day in sorted(set(duties) | set(boards)):
        entries = []

        # 1) التكليفات من يومية التشغيل — دي المرجع، مخزّنة بالـid أصلًا
        for officer_id, rec in (duties.get(day) or {}).items():
            for item in rec.get("items") or []:
                svc = services.get(item.get("service_id"))
                if not svc:
                    stats["تكليف لخدمة محذوفة"] += 1
                    continue
                entries.append(blank(
                    new_id(entries), svc["id"], svc.get("section") or SECTION_OCCASIONAL,
                    shift=clean_shift(item.get("shift"), svc),
                    officer_ids=[officer_id],
                ))
                stats["تكليفات من يومية التشغيل"] += 1

            state = {}
            if rec.get("taqseera"):
                state["taqseera"] = True
            if rec.get("status"):
                state["status"] = rec["status"]
            if rec.get("note"):
                state["note"] = rec["note"]
            if state:
                day_officers.setdefault(day, {})[officer_id] = state

        # 2) خانات اللوحة اللي مالهاش تكليف مقابل — خانات شاغرة أو مناصب
        #    إدارية. الشاغرة بتتحول لخانة حقيقية (الخدمة لسه مطلوبة)،
        #    والمناصب الإدارية بتتشال لأنها مش خدمات في الكتالوج.
        taken = {(e["service_id"], e["shift"], (e["officer_ids"] or [None])[0])
                 for e in entries}
        for old in boards.get(day) or []:
            svc = resolve_service(data, old.get("service") or "")
            if not svc:
                unresolved[old.get("service") or ""] += 1
                stats["خانات مناصب إدارية اتشالت"] += 1
                continue
            shift = clean_shift(old.get("shift"), svc)
            officer_id = old.get("officer_id") or None
            if (svc["id"], shift, officer_id) in taken:
                continue
            entries.append(blank(
                new_id(entries), svc["id"],
                svc.get("section") or SECTION_OCCASIONAL,
                shift=shift,
                officer_ids=[officer_id] if officer_id else [],
                tags=list(old.get("tags") or []),
                note=old.get("note", ""),
                conscripts=_requirements_to_conscripts(old.get("requirements")),
            ))
            stats["خانات لوحة زيادة (شاغرة/موسومة)"] += 1

        if entries:
            day_assignments[day] = entries

    data["day_assignments"] = day_assignments
    data["day_officers"] = day_officers
    for key in LEGACY_KEYS:
        data.pop(key, None)

    report = [
        f"أيام: {len(day_assignments)}",
        f"تكليفات: {sum(len(v) for v in day_assignments.values())}",
        f"حالات ضباط (تقصيرة/انتداب/ملاحظة): {sum(len(v) for v in day_officers.values())}",
        "",
    ]
    report += [f"{n:6}  {k}" for k, n in stats.most_common()]
    report.append("")
    report.append(f"اتشال: {', '.join(LEGACY_KEYS)}")
    if unresolved:
        report.append("")
        report.append("أسماء على اللوحة مالهاش خدمة في الكتالوج (مناصب إدارية غالبًا):")
        report += [f"    {n:4}  {name}" for name, n in unresolved.most_common(12)]
    return report


def _requirements_to_conscripts(raw):
    """الاحتياجات القديمة كانت {label, count, note} نص حر — أقرب حاجة ليها
    في النموذج الجديد هي قوام المجندين بالفئة."""
    out = []
    for item in (raw or []):
        label = str(item.get("label", "")).strip()
        try:
            count = int(item.get("count", 0))
        except (TypeError, ValueError):
            count = 0
        if label or count:
            out.append({"class": label, "count": max(count, 0)})
    return out


run(from_schema=2, to_schema=3, migrate=migrate,
    title="دمج duties و day_services في day_assignments")

#!/usr/bin/env python3
"""وحّد `active`/`archive` في قايمة واحدة، و`status` بقى المرجع.

القوة كانت متخزّنة كده:

    "officers": {"active": [{... "status": "active"}, ...],
                 "archive": [{... "status": "archived"}, ...]}

نفس الحقيقة («الشخص ده على القوة ولا لأ») متخزّنة **مرتين**: مرة في
القايمة اللي هو فيها، ومرة في حقل `status` جوّه السجل. محدش كان بيضمن
اتفاقهم، وسجل في `active` بـ`status: "archived"` سلوكه غير معرّف —
بيتعرض في صفحة القوة وبيتحسب متأرشف في حتة تانية.

بعد الهجرة:

    "officers": [{... "status": "active"}, {... "status": "archived"}, ...]

والقايمتين بقوا **عرض محسوب** (`PeopleRepo.bucket`). النقل بين القوة
والأرشيف بقى تغيير حقل واحد بدل تلات خطوات (شيل، ضيف، رتّب).

**الواجهة ما بتتغيّرش**: `/api/bootstrap/officers` و`/api/data` لسه
بيرجّعوا `{"active": [...], "archive": [...]}` زي ما هم.

الترتيب في القايمة الموحّدة: اللي على القوة الأول (بالرتبة للضباط،
بالاسم للأفراد)، بعدين الأرشيف بتاريخ الخروج من الأحدث — نفس الترتيب
اللي القايمتين كانوا بيدّوه.

لو `status` اختلف عن القايمة اللي السجل فيها، **القايمة هي اللي بتكسب**
لأنها هي اللي كانت بتتعرض فعلًا؛ والفرق بيتسجّل في التقرير.

    python3 migrations/008_unify_person_status.py            # عرض بس
    python3 migrations/008_unify_person_status.py --write
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import AlreadyDone, run                          # noqa: E402

from backend.repo.people import PeopleRepo, as_roster        # noqa: E402


def migrate(data):
    if all(isinstance(data.get(cat), list) for cat in ("officers", "personnel")):
        raise AlreadyDone("القوة متخزّنة قايمة واحدة بالفعل — مفيش حاجة تتعمل.")

    report = []
    for category in ("officers", "personnel"):
        holder = data.get(category)
        if isinstance(holder, list):
            continue

        active = holder.get("active") or []
        archive = holder.get("archive") or []
        # التناقضات قبل ما تتحل — القايمة بتكسب على الحقل
        mismatched = ([p for p in active if (p.get("status") or "active") != "active"]
                      + [p for p in archive if p.get("status") != "archived"])

        data[category] = as_roster(holder)
        PeopleRepo(data).sort(category)

        label = "ضابط" if category == "officers" else "فرد"
        report.append(f"{category}: {len(active)} على القوة + {len(archive)} أرشيف "
                      f"⟵ قايمة واحدة فيها {len(data[category])} {label}.")
        if mismatched:
            ids = "، ".join(p.get("id", "?") for p in mismatched[:6])
            report.append(f"  ⚠ {len(mismatched)} سجل كان `status` بتاعه مخالف للقايمة "
                          f"اللي هو فيها ({ids}) — اتاخدت القايمة.")

    report.append("القايمتين بقوا عرض محسوب؛ الواجهة بترجّعهم زي ما هي.")
    return report


if __name__ == "__main__":
    run(from_schema=4, to_schema=5, migrate=migrate,
        title="توحيد القوة في قايمة واحدة بحالة محسوبة")

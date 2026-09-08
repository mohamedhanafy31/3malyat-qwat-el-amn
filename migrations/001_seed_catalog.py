#!/usr/bin/env python3
"""هجرة 1 → 2: الكتالوج المبني من الأرشيف كله بدل الـ43 خدمة المكتوبة بالإيد.

الكتالوج القديم كان 43 خدمة، والقياس على 101 يوم طلّع إن **83 خدمة من الـ94
اللي بتتكرر على اللوحة في 3 أيام أو أكتر مكانتش موجودة فيه** — فـ711 تكليف
ضابط كان بيقع في خانة «الصافي» غلط، وجدول الإجمالي كان بيطلع أرقام مش مطابقة
للورد (خارجية صباحية 32% بس).

الملف ده بيطبّق `import_archive/catalog_seed.json` (اللي بيبنيه
`catalog_build.py`). الضمانة الأهم: **كل أيدي الخدمات القديمة بتفضل زي ما هي** —
أي تغيير في SVC-0xx كان هيكسر كل تكليف مسجّل عليها في الأرشيف.

التغيير الوحيد في المعنى: «ضابط مباحث السجن العسكري» بقى تصنيفه **داخلية**
بدل «بحث». الدليل من يومية 20/8: الضابط كان على الخدمة دي والورد حسبه في
«الداخلية صباحية» ومكتبش «+1 بحث» خالص — بينما كتبها في 14 يوم تاني كان فيهم
على خدمات خارجية عادية. يعني الوسم تابع لجهة تشغيل الضابط مش لنوع الخدمة،
وده بيتظبط في هجرة تالية لما يتضاف `search_attached` على الضابط.

    python3 001_seed_catalog.py           # عرض بس
    python3 001_seed_catalog.py --write
"""
import json
from pathlib import Path

from common import run

SEED = Path(__file__).resolve().parent.parent / "import_archive" / "catalog_seed.json"

# الحقول اللي الكتالوج الجديد بيضيفها لكل خدمة
NEW_FIELDS = ("board_label", "sub", "section", "shifts", "default_strength",
              "default_weapon", "default_time", "party", "needs", "appears_in", "aliases")


def migrate(data):
    if not SEED.exists():
        raise SystemExit(
            f"مافيش {SEED.name}. شغّل الأول:\n"
            f"    cd import_archive && python3 catalog_build.py")

    seed = json.loads(SEED.read_text(encoding="utf-8"))
    old = {s["id"]: s for s in data["services"]}
    new = {s["id"]: s for s in seed}

    # ---- الضمانة: مفيش أيدي بتضيع ----
    lost = sorted(set(old) - set(new))
    if lost:
        raise SystemExit(
            f"!! {len(lost)} خدمة قديمة مش موجودة في الكتالوج الجديد: {lost[:10]}\n"
            f"   كل تكليف مسجّل عليها كان هيتفصل. اتوقف من غير أي تغيير.")

    renamed = [(i, old[i]["name"], new[i]["name"])
               for i in old if old[i]["name"] != new[i]["name"]]
    rekinded = [(i, old[i]["name"], old[i]["kind"], new[i]["kind"])
                for i in old if old[i].get("kind") != new[i]["kind"]]

    # seen_days بيانات تحليل مش بيانات تشغيل — بتتشال قبل الحفظ
    services = [{k: v for k, v in s.items() if k != "seen_days"} for s in seed]
    data["services"] = services

    report = [
        f"الخدمات: {len(old)} -> {len(services)}  (+{len(services) - len(old)} جديدة)",
        f"الأيدي القديمة محفوظة بالكامل: {len(old)}/{len(old)}",
        f"حقول جديدة لكل خدمة: {', '.join(NEW_FIELDS)}",
        "",
        f"تظهر على اللوحة: {sum(1 for s in services if 'board' in s['appears_in'])}",
        f"تظهر في يومية الأفراد: {sum(1 for s in services if 'afrad' in s['appears_in'])}",
    ]
    by_section = {}
    for s in services:
        by_section[s["section"]] = by_section.get(s["section"], 0) + 1
    report.append("")
    report += [f"{n:4}  {sec}" for sec, n in sorted(by_section.items(), key=lambda kv: -kv[1])]

    report.append("")
    report.append(f"أسماء اتغيّرت: {len(renamed)}")
    for i, a, b in renamed:
        report.append(f"    {i}: {a} -> {b}")
    report.append(f"تصنيفات اتغيّرت: {len(rekinded)}")
    for i, name, a, b in rekinded:
        report.append(f"    {i} «{name}»: {a} -> {b}")
    if rekinded:
        report.append("    (خانة «+بحث» في الإجمالي هتفضل صفر لحد ما يتضاف")
        report.append("     search_attached على الضابط في الهجرة الجاية)")
    return report


run(from_schema=1, to_schema=2, migrate=migrate,
    title="كتالوج الخدمات المبني من أرشيف الـ101 يوم")

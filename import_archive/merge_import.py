#!/usr/bin/env python3
"""يستورد أيام جديدة من أرشيف الوورد من غير ما يمسح شغل السيستم.

`build.py` بيعيد بناء الجداول المشتقة من ملفات الوورد بس (الضباط، الأفراد،
الراحات، الخدمات، التشغيل اليومي). لكن السيستم نفسه بيملك حاجات تانية
مالهاش أي أصل في الوورد:

  - `day_services`  لوحة التشغيل المختصرة بكل تعديلاتك اليدوية
  - `command`        مدير/وكيل الإدارة
  - `medical_officers` ضباط العيادة
  - `board_categories` / `service_tags`  التصنيفات والأوسمة اللي اتكوّنت بالاستخدام

فتشغيل build.py مباشرة على data.json الحيّ كان هيمسح ده كله. السكربت ده
بيشغّله على ملف مؤقت، وبعدين بيدمج الجداول المشتقة بس، ويسيب اللي فوق زي
ما هو.

الاستخدام:
    python3 merge_import.py            # يعرض الفرق من غير ما يكتب
    python3 merge_import.py --write    # ينفّذ الدمج فعليًا
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIVE = HERE.parent / "data.json"

# اللي السيستم بيملكه — مابيتلمسش من الاستيراد أبدًا
APP_OWNED = ["day_services", "command", "medical_officers",
             "board_categories", "service_tags"]
# اللي بيتشتق من الوورد — ده اللي بيتحدّث
DERIVED = ["officers", "personnel", "leaves", "services", "duties"]


def run_build(out_path):
    env = {**os.environ, "BUILD_OUT": str(out_path)}
    r = subprocess.run([sys.executable, "build.py"], cwd=HERE, env=env,
                       capture_output=True, text=True)
    sys.stderr.write(r.stderr)
    if r.returncode != 0:
        raise SystemExit("build.py فشل — مفيش حاجة اتغيّرت.")
    return json.loads(out_path.read_text(encoding="utf-8"))


def officer_ids_by_name(data):
    return {p["name"]: p["id"]
            for b in ("active", "archive") for p in data["officers"][b]}


def main():
    write = "--write" in sys.argv
    live = json.loads(LIVE.read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory() as td:
        fresh = run_build(Path(td) / "fresh.json")

    # --- أهم فحص: الأيدي لازم تفضل ثابتة لنفس الشخص ---
    # لو الاستيراد غيّر أيدي ضابط موجود، كل إشارة ليه في اللوحة والتشغيل
    # والقيادة هتبوظ بالسكوت. الاسم هو المرجع المشترك بين النسختين.
    old_ids, new_ids = officer_ids_by_name(live), officer_ids_by_name(fresh)
    moved = {n: (old_ids[n], new_ids[n]) for n in old_ids & new_ids.keys()
             if old_ids[n] != new_ids[n]}
    if moved:
        print("!! أيدي ضباط اتغيّرت — الدمج هيبوّظ الروابط. اتوقف:")
        for n, (a, b) in list(moved.items())[:10]:
            print(f"   {n}: {a} -> {b}")
        raise SystemExit(1)

    print("=== الفرق ===")
    for key in DERIVED:
        if key in ("officers", "personnel"):
            for b in ("active", "archive"):
                a, c = len(live[key][b]), len(fresh[key][b])
                print(f"  {key}.{b:8} {a:4} -> {c:4}  {'(+%d)' % (c - a) if c != a else ''}")
        elif key == "duties":
            a, c = len(live[key]), len(fresh[key])
            new_days = sorted(set(fresh[key]) - set(live[key]))
            print(f"  {key:17} {a:4} -> {c:4}   أيام جديدة: {new_days}")
        else:
            a, c = len(live[key]), len(fresh[key])
            print(f"  {key:17} {a:4} -> {c:4}  {'(+%d)' % (c - a) if c != a else ''}")

    print("\n=== محفوظ زي ما هو (ملك السيستم) ===")
    for key in APP_OWNED:
        v = live.get(key)
        print(f"  {key:18} {len(v) if hasattr(v, '__len__') else v}")

    if not write:
        print("\n(عرض بس — ضيف --write عشان ينفّذ)")
        return

    merged = {**live, **{k: fresh[k] for k in DERIVED}}
    for key in APP_OWNED:                      # صراحةً: مش بتتلمس
        merged[key] = live.get(key, [] if key.endswith("s") else {})

    # أيام التشغيل اللي السيستم عملها ومش موجودة في الأرشيف (تخطيط لأيام
    # جاية مثلًا) بتفضل زي ما هي — الأرشيف مرجع للأيام اللي بيغطيها بس.
    kept = {d: v for d, v in live["duties"].items() if d not in fresh["duties"]}
    merged["duties"] = {**fresh["duties"], **kept}
    if kept:
        print(f"  أيام تشغيل من السيستم اتحافظ عليها: {sorted(kept)}")

    tmp = LIVE.with_suffix(".tmp")
    tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(LIVE)
    print(f"\nاتكتب {LIVE}")


if __name__ == "__main__":
    main()

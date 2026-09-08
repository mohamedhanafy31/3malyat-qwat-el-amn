#!/usr/bin/env python3
"""يستورد الأرشيف من غير ما يمسح شغل السيستم، ويطلع تقرير فرق مفصّل.

`build.py` بيعيد بناء الجداول المشتقة من ملفات الوورد بس (الضباط، الأفراد،
الراحات، الكتالوج، تكليفات اليوم، حالات الضباط). لكن السيستم بيملك حاجات
مالهاش أصل في الوورد:

  - `command`            مدير/وكيل الإدارة
  - `medical_officers`   ضباط العيادة
  - `service_tags`       الأوسمة اللي اتكوّنت بالاستخدام

فتشغيل build.py على data.json الحيّ كان هيمسح ده. السكربت ده بيشغّله على
ملف مؤقت، وبيدمج المشتق بس.

وبيكتب `import_diff.md`: لكل يوم اتغيّر — الخانات اللي اتضافت واتشالت
واتعدّلت، وجدول الإجمالي قبل وبعد وجنبه رقم الوورد لو اليوم فيه جدول.

    python3 merge_import.py            # يعرض الفرق ويكتب التقرير من غير ما يحفظ
    python3 merge_import.py --write    # ينفّذ الدمج فعليًا
"""
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

LIVE = HERE.parent / "data.json"
REPORT = HERE / "import_diff.md"
BACKUP_DIR = HERE.parent / "backups"

# اللي السيستم بيملكه — مابيتلمسش من الاستيراد أبدًا
APP_OWNED = ["command", "medical_officers", "service_tags"]
# اللي بيتشتق من الوورد — ده اللي بيتحدّث
DERIVED = ["officers", "personnel", "leaves", "services",
           "day_assignments", "day_officers"]


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


def _key(row, services):
    svc = services.get(row.get("service_id"), {})
    return (svc.get("name", row.get("service_id")), row.get("shift", ""))


def _describe(row, services, people):
    svc = services.get(row.get("service_id"), {})
    who = [people.get(i, i) for i in row.get("officer_ids") or []]
    who += [people.get(i, i) for i in row.get("personnel_ids") or []]
    cons = ", ".join(f'{c.get("class") or "مجند"}×{c["count"]}' if c.get("count")
                     else (c.get("class") or "مجند") for c in row.get("conscripts") or [])
    bits = [svc.get("name", "?")]
    if row.get("shift"):
        bits.append(row["shift"])
    bits.append("، ".join(who) if who else ("— " + cons if cons else "— شاغرة"))
    if who and cons:
        bits.append(cons)
    return " | ".join(bits)


def day_diff(old_rows, new_rows, services, people):
    old_index = Counter(_key(r, services) for r in old_rows)
    new_index = Counter(_key(r, services) for r in new_rows)
    added = [r for r in new_rows if new_index[_key(r, services)] > old_index[_key(r, services)]]
    removed = [r for r in old_rows if old_index[_key(r, services)] > new_index[_key(r, services)]]
    return added, removed


def summarise_both(live, fresh, day):
    """جدول الإجمالي قبل وبعد — بيتحسب بنفس كود التطبيق."""
    from backend.duty import summarise
    return summarise(live, day)["summary"], summarise(fresh, day)["summary"]


def main():
    write = "--write" in sys.argv
    live = json.loads(LIVE.read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory() as td:
        fresh = run_build(Path(td) / "fresh.json")

    # --- أهم فحص: الأيدي لازم تفضل ثابتة لنفس الشخص ---
    # لو الاستيراد غيّر أيدي ضابط موجود، كل إشارة ليه في التكليفات والقيادة
    # هتبوظ بالسكوت. الاسم هو المرجع المشترك بين النسختين.
    old_ids, new_ids = officer_ids_by_name(live), officer_ids_by_name(fresh)
    moved = {n: (old_ids[n], new_ids[n]) for n in old_ids & new_ids.keys()
             if old_ids[n] != new_ids[n]}
    if moved:
        print("!! أيدي ضباط اتغيّرت — الدمج هيبوّظ الروابط. اتوقف:")
        for n, (a, b) in list(moved.items())[:10]:
            print(f"   {n}: {a} -> {b}")
        raise SystemExit(1)

    services = {s["id"]: s for s in fresh["services"]}
    people = {p["id"]: p["name"] for cat in ("officers", "personnel")
              for b in ("active", "archive") for p in fresh[cat][b]}

    print("=== الفرق الإجمالي ===")
    for key in DERIVED:
        if key in ("officers", "personnel"):
            for b in ("active", "archive"):
                a, c = len(live[key][b]), len(fresh[key][b])
                print(f"  {key}.{b:8} {a:4} -> {c:4}  {'(%+d)' % (c - a) if c != a else ''}")
        elif key in ("day_assignments", "day_officers"):
            a = sum(len(v) for v in live.get(key, {}).values())
            c = sum(len(v) for v in fresh.get(key, {}).values())
            print(f"  {key:17} {a:4} -> {c:4}  {'(%+d)' % (c - a) if c != a else ''}")
        else:
            a, c = len(live[key]), len(fresh[key])
            print(f"  {key:17} {a:4} -> {c:4}  {'(%+d)' % (c - a) if c != a else ''}")

    print("\n=== محفوظ زي ما هو (ملك السيستم) ===")
    for key in APP_OWNED:
        v = live.get(key)
        print(f"  {key:18} {len(v) if hasattr(v, '__len__') else v}")

    merged = {**live, **{k: fresh[k] for k in DERIVED}}
    for key in APP_OWNED:
        merged[key] = live.get(key, [] if key.endswith("s") else {})
    # أيام عملها السيستم ومش موجودة في الأرشيف (تخطيط لأيام جاية) بتفضل
    kept = {d: v for d, v in live.get("day_assignments", {}).items()
            if d not in fresh["day_assignments"]}
    merged["day_assignments"] = {**fresh["day_assignments"], **kept}
    merged["schema"] = fresh.get("schema", live.get("schema"))
    if kept:
        print(f"  أيام من السيستم اتحافظ عليها: {sorted(kept)}")

    write_report(live, merged, services, people)
    print(f"\nتقرير الفرق: {REPORT}")

    if not write:
        print("(عرض بس — ضيف --write عشان ينفّذ)")
        return

    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = BACKUP_DIR / f"data-{stamp}-pre-reimport.json"
    backup.write_text(json.dumps(live, ensure_ascii=False, indent=2), encoding="utf-8")

    tmp = LIVE.with_suffix(".tmp")
    tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(LIVE)
    print(f"نسخة احتياطية: {backup}")
    print(f"اتكتب {LIVE}")


CELLS = [("خارجية", "صباحية"), ("خارجية", "ليلية"), ("خارجية", "بحث"),
         ("داخلية", "صباحية"), ("داخلية", "ليلية"),
         ("طبية", "موجود"), ("طبية", "راحة"),
         ("خوارج", "تقصيرة"), ("خوارج", "راحة"), ("خوارج", "طارئة"),
         ("خوارج", "غياب"), ("خوارج", "مرضي"), ("خوارج", "فرقة"), ("خوارج", "انتداب")]


def write_report(live, merged, services, people):
    from word_summary import word_summaries

    word = word_summaries()
    lines = ["# تقرير إعادة استيراد الأرشيف", "",
             f"اتولّد: {datetime.now().isoformat(timespec='seconds')}", "",
             "لكل يوم اتغيّر: الخانات اللي اتضافت واتشالت، وجدول الإجمالي",
             "قبل وبعد وجنبه رقم الوورد لو اليوم فيه جدول إجمالي مكتوب.", ""]

    days = sorted(set(live.get("day_assignments", {})) | set(merged["day_assignments"]))
    changed = 0
    for day in days:
        old_rows = live.get("day_assignments", {}).get(day, [])
        new_rows = merged["day_assignments"].get(day, [])
        added, removed = day_diff(old_rows, new_rows, services, people)
        before, after = summarise_both(live, merged, day)
        cells_changed = [c for c in CELLS if before[c[0]][c[1]] != after[c[0]][c[1]]]
        if not added and not removed and not cells_changed:
            continue
        changed += 1
        lines.append(f"## {day}")
        lines.append(f"الخانات: {len(old_rows)} → {len(new_rows)}"
                     f"  (+{len(added)} / −{len(removed)})")
        if added:
            lines.append("")
            lines.append("**اتضاف:**")
            lines += [f"- {_describe(r, services, people)}" for r in added[:40]]
            if len(added) > 40:
                lines.append(f"- … و{len(added) - 40} كمان")
        if removed:
            lines.append("")
            lines.append("**اتشال:**")
            lines += [f"- {_describe(r, services, people)}" for r in removed[:40]]
            if len(removed) > 40:
                lines.append(f"- … و{len(removed) - 40} كمان")
        if cells_changed:
            lines.append("")
            head = "| الخانة | قبل | بعد | الوورد |"
            lines += [head, "|---|---|---|---|"]
            for group, sub in cells_changed:
                w = (word.get(day) or {}).get(f"{group}/{sub}")
                lines.append(f"| {group} {sub} | {before[group][sub]} | "
                             f"{after[group][sub]} | {w if w is not None else '—'} |")
        lines.append("")

    lines.insert(4, f"**أيام اتغيّرت: {changed} من {len(days)}**")
    lines.insert(5, "")
    REPORT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()

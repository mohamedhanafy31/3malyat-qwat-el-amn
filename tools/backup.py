#!/usr/bin/env python3
"""عرض واستعادة النسخ الاحتياطية — بدون إنترنت وبدون أي مكتبة خارجية.

النسخ بقت مضغوطة (`data-<وقت>.json.gz`) عشان توفّر ~97% من المساحة، وويندوز
مابيفتحش ملفات .gz من مستكشف الملفات — فالأداة دي هي طريق الاستعادة الرسمي.
بتفهم الشكلين: المضغوط الجديد والعادي القديم (وكمان نسخ ما-قبل-الهجرة).

    python tools/backup.py list                 # كل النسخ وحالتها
    python tools/backup.py restore --latest     # أرجع أحدث نسخة سليمة
    python tools/backup.py restore data-20260910-120000-123456.json.gz
    python tools/backup.py verify               # افحص كل النسخ من غير ما تغيّر حاجة

الاستعادة بتتحقق إن النسخة سليمة **قبل** ما تلمس data.json، وبتاخد لقطة
من الوضع الحالي الأول — فحتى الاستعادة نفسها ليها تراجع.

مهم: اقفل السيستم قبل الاستعادة (اقفل شاشة التشغيل)، وبعدها شغّله تاني.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.store import (            # noqa: E402
    DATA_FILE, DataUnreadable, backup_dir, list_backups, restore_backup,
)


def _kb(n):
    return f"{n / 1024:,.0f} KB"


def cmd_list(_args):
    rows = list_backups()
    if not rows:
        print(f"مافيش نسخ احتياطية في {backup_dir()}")
        return 0
    print(f"النسخ الاحتياطية في {backup_dir()}  (الأحدث أولًا)\n")
    print(f"{'#':<4}{'الاسم':<44}{'الحجم':>10}  {'مضغوطة':<8}{'الحالة'}")
    print("-" * 96)
    for i, r in enumerate(rows, 1):
        state = (f"سليمة — {r['officers']} ضابط، {r['leaves']} راحة"
                 if r["ok"] else f"تالفة: {r['error']}")
        print(f"{i:<4}{r['name']:<44}{_kb(r['size']):>10}  "
              f"{'نعم' if r['compressed'] else 'لأ':<8}{state}")
    bad = [r for r in rows if not r["ok"]]
    print(f"\nالإجمالي: {len(rows)} نسخة، منها {len(bad)} تالفة.")
    total = sum(r["size"] for r in rows)
    print(f"المساحة المستخدمة: {_kb(total)}")
    return 0


def cmd_verify(_args):
    rows = list_backups()
    bad = [r for r in rows if not r["ok"]]
    for r in rows:
        print(f"  [{'سليمة' if r['ok'] else 'تالفة'}] {r['name']}"
              + ("" if r["ok"] else f"  -> {r['error']}"))
    print(f"\n{len(rows) - len(bad)}/{len(rows)} نسخة سليمة.")
    return 1 if bad else 0


def cmd_restore(args):
    rows = list_backups()
    if not rows:
        print("مافيش نسخ احتياطية للاستعادة.")
        return 1

    if "--latest" in args:
        good = [r for r in rows if r["ok"]]
        if not good:
            print("كل النسخ الموجودة تالفة — مفيش حاجة تترجع.")
            return 1
        name = good[0]["name"]
        print(f"أحدث نسخة سليمة: {name}")
    else:
        picked = [a for a in args if not a.startswith("-")]
        if not picked:
            print("حدد اسم النسخة أو استخدم --latest.")
            return 1
        name = picked[0]

    row = next((r for r in rows if r["name"] == name), None)
    if row is None:
        print(f"مافيش نسخة بالاسم «{name}». شغّل: python tools/backup.py list")
        return 1
    if not row["ok"]:
        print(f"النسخة دي تالفة ومش هتترجع:\n  {row['error']}")
        return 1

    print(f"\nهيتم استبدال:  {DATA_FILE}")
    print(f"بالنسخة    :  {name}")
    print(f"محتواها    :  {row['officers']} ضابط، {row['leaves']} راحة، "
          f"بنية {row['schema']}")
    if "--yes" not in args:
        try:
            if input("\nتأكيد الاستعادة؟ اكتب: نعم  > ").strip() not in ("نعم", "y", "yes"):
                print("اتلغت. مفيش حاجة اتغيّرت.")
                return 1
        except (EOFError, KeyboardInterrupt):
            print("\naتلغت. مفيش حاجة اتغيّرت.")
            return 1

    try:
        data = restore_backup(name)
    except DataUnreadable as exc:
        print(f"فشلت الاستعادة: {exc}")
        return 1
    except OSError as exc:
        print(f"فشلت الاستعادة: {exc}\n"
              "لو السيستم شغّال، اقفله الأول وجرّب تاني.")
        return 1

    print(f"\nتمت الاستعادة. data.json فيه دلوقتي "
          f"{len(data['officers']['active'])} ضابط و{len(data['leaves'])} راحة.")
    print("اتاخدت لقطة للوضع القديم قبل الاستبدال، فينفع ترجع فيها.")
    print("شغّل السيستم تاني عشان يقرا البيانات الجديدة.")
    return 0


COMMANDS = {"list": cmd_list, "verify": cmd_verify, "restore": cmd_restore}


def main(argv):
    if not argv or argv[0] not in COMMANDS:
        print(__doc__)
        return 1
    return COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

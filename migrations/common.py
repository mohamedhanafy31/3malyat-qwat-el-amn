#!/usr/bin/env python3
"""العدّة المشتركة لسكربتات الهجرة.

كل سكربت هجرة في المجلد ده لازم يلتزم بأربع قواعد — الدالة `run()` بتفرضها:

1. **`--dry-run` هو الافتراضي.** الكتابة محتاجة `--write` صراحةً.
2. **نسخة احتياطية قبل أي كتابة** في `backups/data-<وقت>.json`.
3. **Idempotent** — لو الملف متهاجر بالفعل يخرج بهدوء من غير ما يلمس حاجة.
4. **تقرير فرق قبل الكتابة** — تشوف إيه اللي هيتغيّر قبل ما يتغيّر.

الاستخدام في سكربت هجرة:

    from common import run

    def migrate(data):
        ...                       # عدّل data في مكانها
        return ["سطر تقرير", ...]  # اللي هيتطبع

    run(from_schema=1, to_schema=2, migrate=migrate,
        title="دمج duties و day_services في day_assignments")
"""
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

class AlreadyDone(Exception):
    """هجرة بيانات اتعملت قبل كده — تُرفع من migrate() للخروج بهدوء."""


HERE = Path(__file__).resolve().parent
DATA_FILE = HERE.parent / "data.json"
BACKUP_DIR = HERE.parent / "backups"


def _store():
    """`backend.store` — بيتستورد كسول عشان الهجرات اللي بتشتغل على ملف
    واحد قديم ما تحتاجش الحزمة كلها."""
    import sys
    if str(HERE.parent) not in sys.path:
        sys.path.insert(0, str(HERE.parent))
    from backend import store
    return store


def split_mode():
    """البيانات متفكوكة لمجلد ولا لسه ملف واحد؟

    هجرة 010 هي الفاصل. اللي قبلها اشتغلت على `data.json`، واللي بعدها
    بتشتغل على `data/` — والفرق ده بيتحدد من اللي موجود فعلًا مش من رقم
    الهجرة، عشان إعادة تشغيل هجرة قديمة على ملف قديم تفضل شغّالة.
    """
    return _store().core_file().exists()


def load():
    if split_mode():
        return _store().assemble()
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def snapshot():
    """نسخة مؤرّخة من البيانات الحالية — بترجّع مسارها."""
    BACKUP_DIR.mkdir(exist_ok=True)
    if split_mode():
        return _store().snapshot_now()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = BACKUP_DIR / f"data-{stamp}-pre-migration.json"
    shutil.copy2(DATA_FILE, path)
    return path


def write(data):
    if split_mode():
        _store().explode(data)
        return
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(DATA_FILE)


def run(from_schema, to_schema, migrate, title):
    """يشغّل هجرة واحدة تحت القواعد الأربعة. `migrate(data)` بترجّع سطور تقرير."""
    write_mode = "--write" in sys.argv

    print(f"=== هجرة {from_schema} → {to_schema}: {title} ===")
    if not split_mode() and not DATA_FILE.exists():
        raise SystemExit(f"مافيش بيانات — لا {DATA_FILE} ولا مجلد data/.")

    data = load()
    found = data.get("schema", 1)

    # هجرة بيانات (مش بنية): الشكل مابيتغيّرش، فـmigrate هي اللي بتحدد
    # إذا كانت اتعملت قبل كده ولا لأ عن طريق AlreadyDone.
    same_shape = from_schema == to_schema
    if found == to_schema and not same_shape:
        print(f"الملف متهاجر بالفعل (schema {found}) — مفيش حاجة تتعمل.")
        return
    if found != from_schema:
        raise SystemExit(
            f"الهجرة دي بتشتغل على schema {from_schema} بس، والملف عليه {found}. "
            f"اتوقف من غير ما يتغيّر أي حاجة."
        )

    try:
        report = migrate(data) or []
    except AlreadyDone as done:
        print(str(done) or "اتعملت قبل كده — مفيش حاجة تتغيّر.")
        return
    data["schema"] = to_schema

    print("\n=== الفرق ===")
    for line in report:
        print(f"  {line}")

    if not write_mode:
        print("\n(عرض بس — ضيف --write عشان ينفّذ)")
        return

    backup = snapshot()
    write(data)
    target = _store().DATA_DIR if split_mode() else DATA_FILE
    print(f"\nنسخة احتياطية: {backup}")
    print(f"اتكتب {target} (schema {to_schema})")

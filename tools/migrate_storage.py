"""ترقية تخزين البيانات للشكل الجديد (مرة واحدة، آمنة، بتتحقق قبل وبعد).

- سجل التغييرات: من داخل core.json لـ `data/changes/log.jsonl` (مع أرشيف التقليم القديم).
- كل يوم: من ملف JSON واحد لمجلد فيه ملف لكل جانب (assignments/officers/confirm/…).

الأداة بتوقف لو السيرفر شغّال، بتاخد نسخة احتياطية كاملة الأول، وبتقارن «كل البيانات مجمّعة»
قبل وبعد بالبصمة — لو اختلفت حرف واحد بتوقف وبتقولك تستعيد النسخة. تشغيل:

    python tools/migrate_storage.py            # فحص بس (مايكتبش حاجة)
    python tools/migrate_storage.py --apply    # تنفيذ

`PERSONNEL_DATA_DIR` بيحدد مجلد البيانات (الافتراضي data/ جنب المشروع).
"""
import argparse
import hashlib
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import store  # noqa: E402


def _digest():
    """بصمة كل البيانات مجمّعة (core + كل الأيام + سجل التغييرات الكامل) بشكل ثابت."""
    data = store.assemble()
    log_file = store.change_log_path()
    history = log_file.read_text(encoding="utf-8") if log_file.exists() else ""
    blob = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest(), len(history.splitlines())


def _legacy_days():
    return [day for day, (anchor, _sig) in store._scan_day_files().items() if anchor.is_file()]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="نفّذ الترقية فعلًا (من غيرها: فحص بس)")
    parser.add_argument("--backup-dir", help="مكان نسخة data/ الكاملة قبل الترقية (الافتراضي: جنب المشروع)")
    args = parser.parse_args()

    if not store.core_file().exists():
        sys.exit(f"مفيش بيانات في {store.DATA_DIR}")
    try:
        store.acquire_process_lock()          # بيفشل لو السيرفر شغّال على نفس المجلد
    except Exception as exc:                  # noqa: BLE001
        sys.exit(f"أوقف السيرفر الأول ({exc})")

    store.recover_journal()
    legacy = _legacy_days()
    core = json.loads(store.core_file().read_text(encoding="utf-8"))
    log_pending = "change_log" in core and not store.change_log_path().exists()
    print(f"مجلد البيانات: {store.DATA_DIR}")
    print(f"أيام بالشكل القديم (ملف واحد): {len(legacy)}")
    print(f"سجل التغييرات لسه داخل core.json: {'نعم' if log_pending else 'لا'}")
    if not legacy and not log_pending:
        print("كل حاجة بالشكل الجديد بالفعل — مفيش حاجة تتعمل.")
        return

    before, log_lines = _digest()
    print(f"بصمة البيانات قبل الترقية: {before[:16]}…")
    if not args.apply:
        print("فحص فقط — شغّل بـ --apply للتنفيذ.")
        return

    target = Path(args.backup_dir) if args.backup_dir else (
        store.DATA_DIR.parent / f"{store.DATA_DIR.name}-pre-storage-{datetime.now():%Y%m%d-%H%M%S}")
    print(f"نسخة كاملة من البيانات قبل أي كتابة → {target}")
    shutil.copytree(store.DATA_DIR, target, ignore=shutil.ignore_patterns("uploads", "source_docs", "ocr_samples",
                                                                           "daily_files", ".lock", "import"))
    started = time.perf_counter()

    # 1) سجل التغييرات: أول حفظ بيحوّله لملفه ويشيله من core.json
    if log_pending:
        store.with_data(lambda data: None, [])
    # 2) كل يوم لمجلده: معاملة واحدة بدفتر المعاملات لكل يوم (يتكمّل بعد أي انقطاع)
    for day in sorted(legacy):
        blob = store.read_day_blob(day)
        plan = store._plan_day_write(day, blob, None)
        ops = [{"action": "replace", "target": rel, "text": text} for rel, text in plan["files"].items()]
        ops += [{"action": "delete", "target": rel} for rel in plan["delete"]]
        store._write_journal(ops)
        store._apply_day_plan(day, plan)
        store._clear_journal()
    store._cache.clear()

    after, _ = _digest()
    left = _legacy_days()
    print(f"اتحوّل {len(legacy)} يوم في {time.perf_counter() - started:.1f} ثانية؛ متبقي بالشكل القديم: {len(left)}")
    if after != before or left:
        print(f"!! البصمة اختلفت ({before[:12]} ≠ {after[:12]}) أو فاضل أيام. استعد النسخة: {target}")
        sys.exit(2)
    print(f"تمام — البيانات مطابقة بالبصمة ({after[:16]}…). النسخة قبل الترقية: {target}")


if __name__ == "__main__":
    main()

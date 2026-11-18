"""احمِ بيانات التشغيل المحلية قبل أول `git pull` بعد ما اليوميات خرجت من git.

لو الجهاز ده فيه data/days و logs متتبّعين، أول سحب لنسخة الكود الجديدة بيمسحهم من الجهاز (لأنهم
اتشالوا من git). الأداة بتنسخ كل بيانات التشغيل لمكان خارج المشروع، وبتطبع الخطوات اللي بعدها:

    python tools/protect_before_pull.py          # قبل السحب
    git pull
    python tools/protect_before_pull.py --restore <مجلد النسخة>
    python tools/migrate_storage.py --apply --legacy-core <مجلد النسخة>/core.json

(الخطوة الأخيرة بتحوّل الأيام للشكل الجديد وبترجّع سجل التغييرات القديم لو core.json اتبدّل بالسحب.)
"""
import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
KEEP = ("core.json", "days", "users.json", "secret_key", "changes", "uploads", "source_docs", "logs")


def backup():
    target = ROOT.parent / f"personnel-data-keep-{datetime.now():%Y%m%d-%H%M%S}"
    target.mkdir(parents=True)
    for name in KEEP:
        source = (ROOT / name) if name == "logs" else (DATA / name)
        if source.is_dir():
            shutil.copytree(source, target / name)
        elif source.is_file():
            shutil.copy2(source, target / name)
    print(f"اتنسخت بيانات التشغيل → {target}")
    print("دلوقتي: git pull  ثم  python tools/protect_before_pull.py --restore", target)
    return target


def restore(folder):
    folder = Path(folder)
    if not (folder / "days").is_dir():
        sys.exit("المجلد ده مش نسخة من الأداة (مفيش days/).")
    for name in ("days", "changes", "uploads", "source_docs"):
        if (folder / name).is_dir():
            shutil.copytree(folder / name, DATA / name, dirs_exist_ok=True)
    for name in ("users.json", "secret_key"):
        if (folder / name).is_file() and not (DATA / name).exists():
            shutil.copy2(folder / name, DATA / name)
    if (folder / "logs").is_dir():
        shutil.copytree(folder / "logs", ROOT / "logs", dirs_exist_ok=True)
    print("اترجعت اليوميات. بعدها:")
    print(f"  python tools/migrate_storage.py --apply --legacy-core {folder / 'core.json'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--restore", metavar="FOLDER")
    args = ap.parse_args()
    restore(args.restore) if args.restore else backup()

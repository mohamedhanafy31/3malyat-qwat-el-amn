"""قياس قراءة وبناء لوحة التشغيل من غير أي كتابة على البيانات.

لنسخة مؤقتة، انسخ `data/core.json` و`data/days/` فقط؛ لا تنسخ أرشيفات
`daily_files` أو `uploads` أو `source_docs` أو عينات OCR أو السجلات.
"""
import argparse
import os
import sys
import time
from datetime import date, timedelta


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("day", nargs="?", default="2026-10-28")
    parser.add_argument("data_dir", nargs="?", help="مجلد data؛ الافتراضي من PERSONNEL_DATA_DIR")
    args = parser.parse_args()
    if args.data_dir:
        os.environ["PERSONNEL_DATA_DIR"] = os.path.abspath(args.data_dir)
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from backend.ops_board import build_ops
    from backend.store import load_data

    day = date.fromisoformat(args.day)
    scope = [(day - timedelta(days=i)).isoformat() for i in range(4)]
    started = time.perf_counter()
    data = load_data(scope)
    loaded = time.perf_counter()
    build_ops(data, args.day)
    built = time.perf_counter()
    print(f"day={args.day}")
    print(f"load={loaded - started:.6f}s")
    print(f"build={built - loaded:.6f}s")
    print(f"total={built - started:.6f}s")


if __name__ == "__main__":
    main()

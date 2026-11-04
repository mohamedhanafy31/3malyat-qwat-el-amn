#!/usr/bin/env python3
"""إضافة سجل دائم للراحات المحذوفة/الملغية مع backfill من change_log.

`change_log` مسقوف وينقل القديم إلى JSONL، لذلك لا يصلح وحده كقاعدة
لاسترجاع الراحة. هذه الهجرة تضيف `leave_history` إلى core.json وتنسخ إليه
كل delete/cancel/stop ما زال موجودًا بلقطته الكاملة.

    python3 migrations/027_leave_history.py
    python3 migrations/027_leave_history.py --write
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import AlreadyDone, run  # noqa: E402
from backend.leaves import backfill_history  # noqa: E402


def migrate(data):
    existed = "leave_history" in data
    rows = data.setdefault("leave_history", [])
    before = len(rows)
    added = backfill_history(data)
    if existed and not added:
        raise AlreadyDone("leave_history موجود بالفعل ومفيش جديد — مفيش حاجة تتغيّر.")
    return [
        "إضافة المفتاح leave_history إلى core.json",
        f"استرجاع {added} بند من change_log الحالي",
        f"إجمالي بنود السجل الدائم: {len(rows)} (كان {before})",
    ]


if __name__ == "__main__":
    run(from_schema=6, to_schema=6, migrate=migrate,
        title="سجل دائم للراحات المحذوفة والملغية")

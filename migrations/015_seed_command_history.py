#!/usr/bin/env python3
"""بذر تاريخ قيادة الإدارة من القيم الحالية.

    python3 migrations/015_seed_command_history.py
    python3 migrations/015_seed_command_history.py --write
"""
import re
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import AlreadyDone, run  # noqa: E402
from backend.constants import COMMAND_ROLES, GROUP_ROLES  # noqa: E402

DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def earliest_day(data):
    found = []
    for value in data.values():
        if isinstance(value, dict):
            found.extend(key for key in value if DAY.match(str(key)))
    if found:
        return min(found)
    joins = [p.get("join_date") for cat in ("officers", "personnel")
             for p in (data.get(cat) or []) if DAY.match(str(p.get("join_date") or ""))]
    return min(joins) if joins else "1970-01-01"


def migrate(data):
    if data.get("command_history"):
        raise AlreadyDone("سجل القيادة المؤرَّخ موجود بالفعل.")
    start = earliest_day(data)
    command = {role: (data.get("command") or {}).get(role) for role in COMMAND_ROLES}
    groups = {role: list((data.get("command_groups") or {}).get(role) or [])
              for role in GROUP_ROLES}
    data["command_history"] = [{"from": start, "command": deepcopy(command),
                                "groups": deepcopy(groups)}]
    return [f"بُذرت نسخة القيادة الحالية سارية من {start}."]


if __name__ == "__main__":
    run(from_schema=6, to_schema=6, migrate=migrate,
        title="بذر سجل قيادة الإدارة المؤرَّخ")

#!/usr/bin/env python3
"""بذر قوائم الأهداف والخدمات الأساسية المؤرَّخة."""
import sys
import re
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import AlreadyDone, run  # noqa: E402
from backend.afraad import BASIC_SERVICES  # noqa: E402
from backend.constants import TARGETS_FIRST, TARGET_NAMES  # noqa: E402
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
    refs = data.get("reference_lists") or {}
    if refs.get("targets") and refs.get("afraad_basic"):
        raise AlreadyDone("القوائم المرجعية المؤرَّخة موجودة بالفعل.")
    start = earliest_day(data)
    refs = data.setdefault("reference_lists", {})
    refs.setdefault("targets", [{"from": start, "names": [TARGETS_FIRST, *TARGET_NAMES]}])
    refs.setdefault("afraad_basic", [{"from": start, "items": deepcopy(BASIC_SERVICES)}])
    return [f"بُذرت قائمتا الأهداف والخدمات الأساسية ساريتين من {start}."]


if __name__ == "__main__":
    run(from_schema=6, to_schema=6, migrate=migrate,
        title="بذر القوائم المرجعية المؤرَّخة")

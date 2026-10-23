#!/usr/bin/env python3
"""Link names that the archive import left as plain text to the people in the system.

Why: a row that only carries the imported text («م.ش/ محمد الشبراخيتي») ignores
every later change to that person (rank, short name, phone) and can't be counted
or searched. Two places hold such text:
  * يومية الأفراد: `day_afraad[day][service]` — `morning_name` / `night_name`
    without `morning_person_id` / `night_person_id`;
  * the detailed log: an assignment whose `source_manning` is a name («رائد/ فلان»)
    but has no `officer_ids` / `personnel_ids`.

The rank is dropped, the rest must be the beginning of exactly ONE person's full
name (spelling folded by `norm_name`). Ambiguous or unknown names are only
reported — a wrong link is worse than a text. Linking only adds the id: the text
stays as written. Dry-run by default; --write needs the system stopped and keeps a
snapshot + pre-image of every touched day file.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import store  # noqa: E402
from backend.repo import PeopleRepo  # noqa: E402
from backend.text import norm_name  # noqa: E402

TRAILING = re.compile(r"(?:حتى|حتي|من)\s+الساعة.*$|\d{6,}.*$|\bفرد\b$")


def name_words(text: str) -> list[str]:
    """Words of the person's name inside «رتبة/ اسم …», without rank/phone/time."""
    text = str(text or "")
    if "/" in text:
        text = text.split("/", 1)[1]
    text = TRAILING.sub(" ", text)
    return norm_name(text).split()


class Matcher:
    def __init__(self, data):
        repo = PeopleRepo(data)
        self.people = {
            category: [(p["id"], norm_name(p.get("name", "")).split()) for p in repo.raw_all(category)]
            for category in ("officers", "personnel")}

    def find(self, text, category):
        words = name_words(text)
        if len(words) < 2:
            return None, "short"
        hits = [pid for pid, full in self.people[category] if full[:len(words)] == words]
        if len(hits) == 1:
            return hits[0], "one"
        return None, "multi" if hits else "none"


def plan(data):
    matcher = Matcher(data)
    changes, unresolved = [], defaultdict(Counter)
    for day, services in sorted((data.get("day_afraad") or {}).items()):
        for service_id, override in services.items():
            for shift in ("morning", "night"):
                text = override.get(f"{shift}_name")
                if not text or override.get(f"{shift}_person_id"):
                    continue
                pid, state = matcher.find(text, "personnel")
                if pid:
                    changes.append({"kind": "afraad", "day": day, "service": service_id,
                                    "field": f"{shift}_person_id", "id": pid, "text": text})
                else:
                    unresolved[state][text] += 1
    for day, rows in sorted((data.get("day_assignments") or {}).items()):
        for row in rows:
            text = (row.get("source_manning") or "").strip()
            if not text or "/" not in text or row.get("officer_ids") or row.get("personnel_ids"):
                continue
            for category, key in (("officers", "officer_ids"), ("personnel", "personnel_ids")):
                pid, state = matcher.find(text, category)
                if pid:
                    changes.append({"kind": "assignment", "day": day, "assignment": row.get("id"),
                                    "field": key, "id": pid, "text": text})
                    break
            else:
                unresolved["none-or-multi"][text] += 1
    return changes, unresolved


def apply(data, changes):
    for change in changes:
        if change["kind"] == "afraad":
            data["day_afraad"][change["day"]][change["service"]][change["field"]] = change["id"]
        else:
            row = next(r for r in data["day_assignments"][change["day"]]
                       if r.get("id") == change["assignment"])
            row[change["field"]] = [change["id"]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    data = store.load_data(store.ALL_DAYS)
    changes, unresolved = plan(data)
    by_text = Counter((c["text"], c["id"]) for c in changes)
    print(f"to link: {len(changes)} rows ({len(by_text)} distinct names)")
    for (text, pid), count in by_text.most_common():
        print(f"  {count:4d}  {text}  ->  {pid}")
    for state, rows in unresolved.items():
        print(f"not linked [{state}]: {sum(rows.values())} rows")
        for text, count in rows.most_common(15):
            print(f"  {count:4d}  {text}")
    if args.report:
        args.report.write_text(json.dumps({"changes": changes,
                                           "unresolved": {k: dict(v) for k, v in unresolved.items()}},
                                          ensure_ascii=False, indent=1), encoding="utf-8")
    if not args.write:
        print("dry-run — add --write to apply.")
        return 0

    store.acquire_process_lock()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    preimage = store.DATA_DIR / "import" / "preimage" / f"link-names-{stamp}"
    for day in sorted({c["day"] for c in changes}):
        source = store.day_path(day)
        if source.exists():
            target = preimage / "files" / source.relative_to(store.DATA_DIR)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    snapshot = store.snapshot_now()
    apply(data, changes)
    store.save_data(data)
    (preimage / "report.json").write_text(json.dumps(
        {"at": datetime.now().isoformat(timespec="seconds"), "snapshot": str(snapshot or ""),
         "changes": changes}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"written={len(changes)} preimage={preimage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Repeatable split-JSON benchmark using an isolated PERSONNEL_DATA_DIR.

Phases (reported separately, p95/median in ms):
  cold     — in-memory cache/index/log window cleared before every load (full index build)
  warm     — repeated scoped loads inside INDEX_RECHECK_SECONDS (no rescan)
  recheck  — INDEX_RECHECK_SECONDS=0, so every load rescans every day folder for external edits
  deepcopy — copy.deepcopy of a warm scoped snapshot (what board/duty routes do per request)

    python tools/benchmark_storage.py --days 1097 --runs 30 --log-entries 5000
"""
import argparse, copy, json, os, statistics, tempfile, time, sys
from datetime import date, timedelta
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--days", type=int, default=1097)
parser.add_argument("--runs", type=int, default=30)
parser.add_argument("--log-entries", type=int, default=5000)
args = parser.parse_args()

root = Path(tempfile.mkdtemp(prefix="personnel-bench-"))
os.environ["PERSONNEL_DATA_DIR"] = str(root / "data")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import store  # noqa: E402

first = date(2024, 1, 1)
days = [(first + timedelta(days=i)).isoformat() for i in range(args.days)]
assert len(set(days)) == args.days
# leave_history explicit: without it _normalise runs the legacy backfill, which reads (unpacks) change_log
store.explode({"schema": store.SCHEMA_VERSION, "officers": [], "personnel": [], "leave_history": [],
               "day_assignments": {day: [{"id": f"AS-{i}", "name": f"خدمة {i}"}]
                                   for i, day in enumerate(days)}})
log_path = store.change_log_path()
log_path.parent.mkdir(parents=True, exist_ok=True)
with open(log_path, "w", encoding="utf-8") as fh:
    for n in range(args.log_entries):
        fh.write(json.dumps({"id": f"CHG-{n:06d}", "ts": "2026-01-01T00:00:00", "entity": "assignment",
                             "entity_id": f"AS-{n}", "action": "update", "day": days[n % len(days)],
                             "text": f"تعديل {n}", "before": {"n": n}, "after": {"n": n + 1},
                             "reason": "", "edited_by": None}, ensure_ascii=False) + "\n")
store._cache.clear()


def ms(fn):
    start = time.perf_counter_ns(); fn(); return (time.perf_counter_ns() - start) / 1e6


def report(phase, scope_name, samples):
    print(json.dumps({"phase": phase, "scope": scope_name, "runs": len(samples),
                      "p95_ms": round(sorted(samples)[max(0, int(.95 * len(samples)) - 1)], 3),
                      "median_ms": round(statistics.median(samples), 3)}, ensure_ascii=False))


print(json.dumps({"unique_days": len(days), "log_entries": args.log_entries, "data_dir": str(root)},
                 ensure_ascii=False))
recheck = store.INDEX_RECHECK_SECONDS
for scope_name, scope in (("1-day", days[-1:]), ("2-day", days[-2:]), ("30-day", days[-30:])):
    cold = []
    for _ in range(args.runs):
        store._cache.clear()
        cold.append(ms(lambda: store.load_data(scope)))
    report("cold", scope_name, cold)
    store.INDEX_RECHECK_SECONDS = 3600.0
    store.load_data(scope)
    report("warm", scope_name, [ms(lambda: store.load_data(scope)) for _ in range(args.runs)])
    store.INDEX_RECHECK_SECONDS = 0
    report("recheck", scope_name, [ms(lambda: store.load_data(scope)) for _ in range(args.runs)])
    store.INDEX_RECHECK_SECONDS = 3600.0
    snapshot = store.load_data(scope)
    assert isinstance(snapshot["change_log"], store.ChangeLogView) and snapshot["change_log"].untouched, \
        "change_log was unpacked during load; deepcopy phase would not reflect a fresh request snapshot"
    report("deepcopy", scope_name, [ms(lambda: copy.deepcopy(snapshot)) for _ in range(args.runs)])
    store.INDEX_RECHECK_SECONDS = recheck

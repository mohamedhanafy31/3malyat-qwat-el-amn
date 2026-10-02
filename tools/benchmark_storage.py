#!/usr/bin/env python3
"""Repeatable split-JSON benchmark using an isolated PERSONNEL_DATA_DIR."""
import argparse, json, os, statistics, tempfile, time, sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--days", type=int, default=1097)
parser.add_argument("--runs", type=int, default=30)
args = parser.parse_args()

root = Path(tempfile.mkdtemp(prefix="personnel-bench-"))
os.environ["PERSONNEL_DATA_DIR"] = str(root / "data")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import store  # noqa: E402

store.explode({"schema": store.SCHEMA_VERSION, "officers": [], "personnel": [],
               "day_assignments": {f"2026-01-{(i % 28) + 1:02d}": [{"id": f"AS-{i}"}]
                                    for i in range(args.days)}})
def timed(scope):
    start = time.perf_counter_ns(); store.load_data(scope); return (time.perf_counter_ns()-start)/1e6

for scope_name, scope in (("1-day", ["2026-01-01"]), ("30-day", [f"2026-01-{i:02d}" for i in range(1, 29)])):
    cold = [timed(scope) for _ in range(args.runs)]
    warm = [timed(scope) for _ in range(args.runs)]
    print(json.dumps({"scope": scope_name, "cold_p95_ms": sorted(cold)[max(0, int(.95*len(cold))-1)],
                      "warm_p95_ms": sorted(warm)[max(0, int(.95*len(warm))-1)],
                      "median_ms": statistics.median(warm), "data_dir": str(root)}, ensure_ascii=False))

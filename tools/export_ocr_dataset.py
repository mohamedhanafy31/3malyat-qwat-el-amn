#!/usr/bin/env python3
"""Export the reviewed OCR samples (data/ocr_samples) as a JSONL training manifest.

One line per sample that has a `final.json` (the operator confirmed the rows):
the image path, the raw cells/OCR text the system produced, and the corrected
labels per row (service + morning/night person, with an `edited` flag where the
operator changed the system's suggestion). Read-only; nothing is modified.

    python3 tools/export_ocr_dataset.py --out /path/ocr-dataset.jsonl [--only-edited]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import ocr_samples  # noqa: E402


def samples():
    base = ocr_samples.root()
    for final_path in sorted(base.glob("*/*/final.json")):
        folder = final_path.parent
        try:
            prediction = json.loads((folder / "prediction.json").read_text(encoding="utf-8"))
            final = json.loads(final_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        yield {
            "sample_id": final["sample_id"], "day": final["day"],
            "image": str((folder / prediction["image"]).relative_to(base)),
            "cells": prediction["prediction"].get("cells"),
            "raw_ocr": prediction["prediction"].get("raw_ocr"),
            "grid": prediction["prediction"].get("grid"),
            "predicted_rows": prediction["prediction"].get("rows"),
            "labels": final["rows"],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only-edited", action="store_true",
                        help="only samples where the operator changed something")
    args = parser.parse_args()
    count = 0
    with args.out.open("w", encoding="utf-8") as handle:
        for item in samples():
            if args.only_edited and not any(row["edited"] for row in item["labels"]):
                continue
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
            count += 1
    print(f"{count} samples -> {args.out}  (images are relative to {ocr_samples.root()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

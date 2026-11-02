#!/usr/bin/env python3
"""قياس الـpipeline مع Indra ومن غيره على عينة معلّمة يدويًا."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.afraad_ocr_pipeline.config import PipelineConfig  # noqa: E402
from backend.afraad_ocr_pipeline.pipeline import TableOCRPipeline  # noqa: E402


def clean(value: str) -> str:
    text = str(value or "")
    text = text.split("/", 1)[1] if "/" in text else text
    text = re.sub(r"\(.*?\)|[().…]+|\d+|[٠-٩۰-۹]+", " ", text)
    text = re.sub(r"[إأآ]", "ا", text).replace("ى", "ي").replace("ة", "ه").replace("ی", "ي")
    text = re.sub(r"[^ء-ي ]", " ", text)
    return " ".join(text.replace("عبد ", "عبد").split())


def score(rows: dict, truth: dict) -> dict:
    exact = similarity = names = noise = 0
    for service_id, (morning, evening) in truth.items():
        row = rows.get(service_id, {})
        for wanted, actual in ((morning, row.get("morning")), (evening, row.get("evening"))):
            wanted, actual = clean(wanted), clean(actual)
            if not wanted:
                noise += bool(actual)
                continue
            names += 1
            exact += wanted == actual
            similarity += SequenceMatcher(None, wanted, actual).ratio()
    return {
        "names": names,
        "exact": exact,
        "exact_pct": round(100 * exact / names, 1),
        "similarity": round(100 * similarity / names, 1),
        "noise_in_empty": noise,
    }


def rows_from_result(cells: list[dict], row_services: dict[int, str]) -> dict:
    rows: dict[str, dict] = {}
    for cell in cells:
        service_id = row_services.get(int(cell["row"]))
        if service_id and cell.get("semantic") in {"morning", "evening"}:
            rows.setdefault(service_id, {})[cell["semantic"]] = cell.get("text", "")
    return rows


def run(image, use_indra: bool, row_services: dict[int, str], truth: dict) -> dict:
    previous = os.environ.get("INDRA_OCR")
    os.environ["INDRA_OCR"] = "1" if use_indra else "0"
    try:
        config = PipelineConfig.from_env()
        started = time.perf_counter()
        result = TableOCRPipeline(config).run(image)
    finally:
        if previous is None:
            os.environ.pop("INDRA_OCR", None)
        else:
            os.environ["INDRA_OCR"] = previous
    elapsed = time.perf_counter() - started
    measured = score(rows_from_result(result.cells, row_services), truth)
    measured["seconds"] = round(elapsed, 2)
    measured["warnings"] = result.warnings
    return measured


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sample", type=Path)
    parser.add_argument("truth", nargs="?", type=Path,
                        default=ROOT / "tests/fixtures/ocr/truth_1019.json")
    args = parser.parse_args()
    image_path = next((args.sample / name for name in ("image.jpeg", "image.png")
                       if (args.sample / name).is_file()), None)
    prediction_path = args.sample / "prediction.json"
    if image_path is None or not prediction_path.is_file():
        parser.error("مجلد العينة لا يحتوي image وprediction.json")
    image = cv2.imread(str(image_path))
    truth = json.loads(args.truth.read_text(encoding="utf-8"))
    prediction = json.loads(prediction_path.read_text(encoding="utf-8"))["prediction"]
    row_services = {int(row["grid_row"]): row.get("service_id") for row in prediction["rows"]}
    output = {
        "INDRA_OCR=0": run(image, False, row_services, truth),
        "INDRA_OCR=1": run(image, True, row_services, truth),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

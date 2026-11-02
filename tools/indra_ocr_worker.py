"""Indra OCR worker; this file runs only inside the isolated Indra venv."""

from __future__ import annotations

import json
import sys
import time

import cv2
import indra_ocr


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: indra_ocr_worker.py INPUT_IMAGE", file=sys.stderr)
        return 2
    image = cv2.imread(sys.argv[1], cv2.IMREAD_GRAYSCALE)
    if image is None:
        print(json.dumps({"lines": [], "error": "صورة غير صالحة"}, ensure_ascii=False))
        return 0

    started = time.perf_counter()
    converter = indra_ocr.load(threads=4)
    page = converter.ocr(image, turn=True)
    payload = {
        "lines": [
            {
                "box": [float(value) for value in line.box],
                "text": str(line.text),
                "conf": float(line.conf),
            }
            for line in page.lines
        ],
        "rotation": float(page.rotation),
        "skew": float(page.skew),
        "ms": round((time.perf_counter() - started) * 1000, 1),
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

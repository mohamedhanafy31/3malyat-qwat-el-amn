"""Indra OCR worker with an optional project-local package target."""

from __future__ import annotations

import argparse
import json
import sys
import time


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-dir")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("input_image", nargs="?")
    args = parser.parse_args(argv)
    if args.site_dir:
        sys.path.insert(0, args.site_dir)

    import cv2
    import indra_ocr

    converter = indra_ocr.load(threads=4)
    if args.check:
        return 0
    if not args.input_image:
        parser.error("INPUT_IMAGE is required unless --check is used")
    image = cv2.imread(args.input_image, cv2.IMREAD_GRAYSCALE)
    if image is None:
        print(json.dumps({"lines": [], "error": "صورة غير صالحة"}, ensure_ascii=False))
        return 0

    started = time.perf_counter()
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

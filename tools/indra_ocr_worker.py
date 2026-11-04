"""Indra OCR worker with an optional project-local package target."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback


def _stage(message: str) -> None:
    """مراحل العامل على stderr — النظام بيسجّلها في ocr.log (ocr.indra.stderr)."""
    print(f"[indra-worker +{time.perf_counter() - _T0:.2f}s] {message}", file=sys.stderr, flush=True)


_T0 = time.perf_counter()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-dir")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("input_image", nargs="?")
    args = parser.parse_args(argv)
    if args.site_dir:
        sys.path.insert(0, args.site_dir)

    _stage(f"start python={sys.version.split()[0]} exe={sys.executable} "
           f"site_dir={args.site_dir} model_dir={os.environ.get('INDRA_OCR_MODEL_DIR')}")
    try:
        import cv2
        _stage(f"import cv2 ok {getattr(cv2, '__version__', '?')}")
        import indra_ocr
        _stage(f"import indra_ocr ok from {getattr(indra_ocr, '__file__', '?')} "
               f"version={getattr(indra_ocr, '__version__', '?')}")
        converter = indra_ocr.load(threads=4)
        _stage("model loaded")
    except BaseException:
        _stage("FAILED during import/model load:")
        traceback.print_exc(file=sys.stderr)
        raise
    if args.check:
        return 0
    if not args.input_image:
        parser.error("INPUT_IMAGE is required unless --check is used")
    image = cv2.imread(args.input_image, cv2.IMREAD_GRAYSCALE)
    _stage(f"image read shape={None if image is None else image.shape}")
    if image is None:
        print(json.dumps({"lines": [], "error": "صورة غير صالحة"}, ensure_ascii=True))
        return 0

    started = time.perf_counter()
    try:
        page = converter.ocr(image, turn=True)
    except BaseException:
        _stage("FAILED during converter.ocr:")
        traceback.print_exc(file=sys.stderr)
        raise
    _stage(f"ocr done lines={len(page.lines)}")
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
    # ASCII-safe: من غير ما نعتمد على ترميز stdout (ويندوز cp1252 كان بيكسر العربي).
    print(json.dumps(payload, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

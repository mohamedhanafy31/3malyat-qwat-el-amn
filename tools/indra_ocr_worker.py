"""Indra OCR worker with an optional project-local package target."""

from __future__ import annotations

import argparse
import faulthandler
import json
import os
import platform
import sys
import time
import traceback
from pathlib import Path


def _stage(message: str) -> None:
    """مراحل العامل على stderr — النظام بيسجّلها في ocr.log (ocr.indra.stderr)."""
    print(f"[indra-worker +{time.perf_counter() - _T0:.2f}s] {message}", file=sys.stderr, flush=True)


_T0 = time.perf_counter()


def _cpu_features() -> str:
    """AVX/AVX2 support: a missing one is the usual reason a worker dies silently."""
    try:
        if os.name == "nt":
            import ctypes
            present = ctypes.windll.kernel32.IsProcessorFeaturePresent
            return (f"AVX={'yes' if present(39) else 'NO'} AVX2={'yes' if present(40) else 'NO'} "
                    f"AVX512F={'yes' if present(41) else 'no'}")
        flags = ""
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                if line.startswith("flags"):
                    flags = line
                    break
        words = set(flags.split())
        return f"AVX={'yes' if 'avx' in words else 'NO'} AVX2={'yes' if 'avx2' in words else 'NO'}"
    except Exception as exc:  # diagnostics must never stop the worker
        return f"unknown ({type(exc).__name__})"


def _memory() -> str:
    try:
        if os.name == "nt":
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                            ("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong),
                            ("page_total", ctypes.c_ulonglong), ("page_free", ctypes.c_ulonglong),
                            ("virt_total", ctypes.c_ulonglong), ("virt_free", ctypes.c_ulonglong),
                            ("ext", ctypes.c_ulonglong)]
            status = Status()
            status.length = ctypes.sizeof(Status)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return f"{status.free / 2**20:.0f} MB free of {status.total / 2**20:.0f} MB"
        values = {}
        with open("/proc/meminfo", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                key, _, rest = line.partition(":")
                values[key] = int(rest.split()[0])
        return f"{values['MemAvailable'] / 1024:.0f} MB free of {values['MemTotal'] / 1024:.0f} MB"
    except Exception as exc:
        return f"unknown ({type(exc).__name__})"


def _resolve_model_dir() -> str:
    """Use the project's models when no folder is configured, and never go online.

    Without this the library tries to download the models from the internet,
    which is what a manual run on an offline PC used to do.
    """
    configured = os.environ.get("INDRA_OCR_MODEL_DIR")
    if configured:
        source = "INDRA_OCR_MODEL_DIR"
        folder = configured
    else:
        local = Path(__file__).resolve().parents[1] / "vendor" / "indra-models"
        if not local.is_dir():
            return "none (the library will try to download models)"
        os.environ["INDRA_OCR_MODEL_DIR"] = folder = str(local)
        source = "project default"
    if Path(folder).is_dir():
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        files = sorted(item for item in Path(folder).iterdir() if item.is_file())
        total = sum(item.stat().st_size for item in files)
        return f"{folder} ({source}; {len(files)} files, {total / 2**20:.0f} MB, offline mode)"
    return f"{folder} ({source}; FOLDER DOES NOT EXIST)"


def _selftest_image():
    """A plain image with Latin text and digits: enough to exercise detection + recognition."""
    import cv2
    import numpy as np
    image = np.full((240, 900), 255, dtype=np.uint8)
    cv2.putText(image, "TEST 2026 123456", (30, 90), cv2.FONT_HERSHEY_SIMPLEX, 1.6, 0, 3)
    cv2.putText(image, "personnel system check", (30, 190), cv2.FONT_HERSHEY_SIMPLEX, 1.4, 0, 3)
    return image


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-dir")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("input_image", nargs="?")
    parser.add_argument("--selftest", action="store_true",
                        help="load the models, then run one real OCR inference on a test image")
    args = parser.parse_args(argv)
    if args.site_dir:
        sys.path.insert(0, args.site_dir)
    # A native crash (illegal instruction, access violation) otherwise leaves no
    # trace at all; this prints the Python stack at the moment it happens.
    try:
        faulthandler.enable(file=sys.stderr)
    except Exception:
        pass

    _stage(f"start python={sys.version.split()[0]} exe={sys.executable} site_dir={args.site_dir}")
    _stage(f"system {platform.system()} {platform.release()} {platform.machine()}; "
           f"cpu {_cpu_features()}; memory {_memory()}")
    _stage(f"model_dir={_resolve_model_dir()}")
    try:
        import cv2
        _stage(f"import cv2 ok {getattr(cv2, '__version__', '?')}")
        import indra_ocr
        _stage(f"import indra_ocr ok from {getattr(indra_ocr, '__file__', '?')} "
               f"version={getattr(indra_ocr, '__version__', '?')}")
        try:
            import onnxruntime
            _stage(f"onnxruntime {onnxruntime.__version__} providers={onnxruntime.get_available_providers()}")
        except Exception as exc:
            _stage(f"onnxruntime not inspected ({type(exc).__name__}: {exc})")
        _stage("loading models (a native crash here leaves no Python error)")
        converter = indra_ocr.load(threads=4)
        _stage("model loaded")
    except BaseException:
        _stage("FAILED during import/model load:")
        traceback.print_exc(file=sys.stderr)
        raise
    if args.selftest:
        started = time.perf_counter()
        try:
            page = converter.ocr(_selftest_image(), turn=True)
        except BaseException:
            _stage("FAILED during the self-test inference:")
            traceback.print_exc(file=sys.stderr)
            raise
        texts = [str(line.text) for line in page.lines][:4]
        _stage(f"self-test inference ok: {len(page.lines)} lines in "
               f"{(time.perf_counter() - started) * 1000:.0f} ms {texts}")
        return 0
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

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np

from .config import PipelineConfig
from .models import OCRResult


def find_python(config: PipelineConfig) -> Path | None:
    root = Path(__file__).resolve().parents[2]
    candidates = []
    if config.paddle_python:
        candidates.append(Path(config.paddle_python))
    candidates.extend([
        root / ".venv-paddle/bin/python",
        Path("/tmp/arabic-ocr-paddle-env/bin/python"),
    ])
    return next((path for path in candidates if path.is_file()), None)


def recognize(image: np.ndarray, config: PipelineConfig) -> OCRResult:
    python = find_python(config)
    if python is None:
        return OCRResult(engine="paddle", error="PaddleOCR غير مثبت.")

    worker = Path(__file__).resolve().parents[2] / "tools" / "afraad_ocr_worker.py"
    with tempfile.TemporaryDirectory(prefix="ocr-paddle-") as temp_dir:
        input_path = Path(temp_dir) / "cell.png"
        output_path = Path(temp_dir) / "result.json"
        if not cv2.imwrite(str(input_path), image):
            return OCRResult(engine="paddle", error="تعذر حفظ خلية PaddleOCR المؤقتة.")
        env = {
            **os.environ,
            "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True",
            "PADDLE_PDX_MODEL_SOURCE": os.environ.get("PADDLE_PDX_MODEL_SOURCE", "huggingface"),
        }
        try:
            completed = subprocess.run(
                [str(python), str(worker), str(input_path), str(output_path)],
                capture_output=True,
                text=True,
                timeout=config.paddle_timeout,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return OCRResult(engine="paddle", error="انتهت مهلة PaddleOCR.")
        if completed.returncode != 0 or not output_path.exists():
            detail = completed.stderr.strip().splitlines()
            return OCRResult(engine="paddle", error=detail[-1] if detail else "فشل PaddleOCR.")
        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return OCRResult(engine="paddle", error=f"نتيجة PaddleOCR غير صالحة: {exc}")
        return OCRResult(
            text=" ".join(str(payload.get("text", "")).split()),
            confidence=float(payload.get("confidence", 0.0) or 0.0),
            engine="paddle",
            data=payload.get("items", []),
        )


def recognize_many(images: list[np.ndarray], config: PipelineConfig) -> list[OCRResult]:
    """Run one Paddle process for all fallback cells so the model loads once."""
    python = find_python(config)
    if python is None or not images:
        return [OCRResult(engine="paddle", error="PaddleOCR غير مثبت.") for _ in images]
    worker = Path(__file__).resolve().parents[2] / "tools" / "afraad_ocr_worker.py"
    with tempfile.TemporaryDirectory(prefix="ocr-paddle-batch-") as temp_dir:
        root = Path(temp_dir) / "inputs"
        root.mkdir()
        output_path = Path(temp_dir) / "result.json"
        for index, image in enumerate(images):
            if not cv2.imwrite(str(root / f"{index:04d}.png"), image):
                return [OCRResult(engine="paddle", error="تعذر حفظ خلايا PaddleOCR المؤقتة.") for _ in images]
        env = {
            **os.environ,
            "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True",
            "PADDLE_PDX_MODEL_SOURCE": os.environ.get("PADDLE_PDX_MODEL_SOURCE", "huggingface"),
        }
        try:
            completed = subprocess.run(
                [str(python), str(worker), str(root), str(output_path)],
                capture_output=True,
                text=True,
                timeout=config.paddle_timeout,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return [OCRResult(engine="paddle", error="انتهت مهلة PaddleOCR.") for _ in images]
        if completed.returncode != 0 or not output_path.exists():
            detail = completed.stderr.strip().splitlines()
            error = detail[-1] if detail else "فشل PaddleOCR."
            return [OCRResult(engine="paddle", error=error) for _ in images]
        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return [OCRResult(engine="paddle", error=f"نتيجة PaddleOCR غير صالحة: {exc}") for _ in images]
        results = []
        for item in payload.get("results", []):
            results.append(OCRResult(
                text=" ".join(str(item.get("text", "")).split()),
                confidence=float(item.get("confidence", 0.0) or 0.0),
                engine="paddle",
                data=item.get("items", []),
            ))
        while len(results) < len(images):
            results.append(OCRResult(engine="paddle", error="نتيجة خلية مفقودة."))
        return results[: len(images)]



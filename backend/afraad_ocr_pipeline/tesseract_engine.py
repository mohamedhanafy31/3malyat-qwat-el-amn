from __future__ import annotations

import shutil
import os
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .config import PipelineConfig
from .models import OCRResult


def _available() -> bool:
    return _command() is not None


def _command() -> str | None:
    configured = os.environ.get("TESSERACT_CMD", "").strip()
    bundled = Path(__file__).resolve().parents[2] / "tools" / "tesseract" / "tesseract.exe"
    if configured and Path(configured).is_file():
        return configured
    if bundled.is_file():
        return str(bundled)
    return shutil.which("tesseract")


def _configure(pytesseract):
    command = _command()
    if command:
        pytesseract.pytesseract.tesseract_cmd = command


def _clean(text: str) -> str:
    return " ".join(text.replace("\u200f", " ").replace("\u200e", " ").split()).strip()


def _mean_confidence(data: dict[str, list[Any]]) -> float:
    values = []
    for value, text in zip(data.get("conf", []), data.get("text", [])):
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            continue
        if str(text).strip() and confidence >= 0:
            values.append(confidence)
    return sum(values) / len(values) if values else 0.0


def recognize(image: np.ndarray, config: PipelineConfig, multiline: bool = False) -> OCRResult:
    if not _available():
        return OCRResult(error="Tesseract غير مثبت.")
    try:
        import pytesseract
        from pytesseract import TesseractError, TesseractNotFoundError

        _configure(pytesseract)
        psm = config.tesseract_multiline_psm if multiline else config.tesseract_cell_psm
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        data = pytesseract.image_to_data(
            rgb,
            lang=config.tesseract_lang,
            config=f"--oem 1 --psm {psm}",
            timeout=config.tesseract_timeout,
            output_type=pytesseract.Output.DICT,
        )
        text = _clean(" ".join(str(item) for item in data.get("text", []) if str(item).strip()))
        return OCRResult(text=text, confidence=_mean_confidence(data), engine="tesseract", data=[data])
    except (TesseractError, TesseractNotFoundError, RuntimeError, OSError) as exc:
        return OCRResult(engine="tesseract", error=f"فشل Tesseract: {exc}")


def recognize_raw(image: np.ndarray, config: PipelineConfig) -> OCRResult:
    if not _available():
        return OCRResult(error="Tesseract غير مثبت.")
    try:
        import pytesseract
        from pytesseract import TesseractError, TesseractNotFoundError

        _configure(pytesseract)
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        data = pytesseract.image_to_data(
            rgb,
            lang=config.tesseract_lang,
            config=f"--oem 1 --psm {config.tesseract_raw_psm}",
            timeout=config.tesseract_timeout,
            output_type=pytesseract.Output.DICT,
        )
        text = _clean(" ".join(str(item) for item in data.get("text", []) if str(item).strip()))
        return OCRResult(text=text, confidence=_mean_confidence(data), engine="tesseract-raw", data=[data])
    except (TesseractError, TesseractNotFoundError, RuntimeError, OSError) as exc:
        return OCRResult(engine="tesseract-raw", error=f"فشل OCR الخام: {exc}")



from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .config import PipelineConfig


@dataclass(frozen=True)
class IndraLine:
    box: tuple[float, float, float, float]
    text: str
    confidence: float


@dataclass
class IndraPage:
    lines: list[IndraLine] = field(default_factory=list)
    rotation: int | float = 0
    skew: float = 0.0
    ms: float = 0.0
    error: str | None = None

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines if line.text)

    @property
    def confidence(self) -> float:
        values = [line.confidence for line in self.lines if line.text]
        return sum(values) / len(values) if values else 0.0


def find_python(config: PipelineConfig) -> Path | None:
    root = Path(__file__).resolve().parents[2]
    candidates = []
    if config.indra_python:
        candidates.append(Path(config.indra_python).expanduser())
    if os.environ.get("INDRA_PYTHON"):
        candidates.append(Path(os.environ["INDRA_PYTHON"]).expanduser())
    candidates.extend([
        root / ".venv-indra" / "bin" / "python",
        root / ".venv-indra" / "Scripts" / "python.exe",
        Path("~/.venvs/indra-ocr/bin/python").expanduser(),
    ])
    return next((path for path in candidates if path.is_file()), None)


def _error(message: str) -> IndraPage:
    return IndraPage(error=message)


def recognize_page(image: np.ndarray, config: PipelineConfig) -> IndraPage:
    """يشغّل Indra في بيئته المعزولة، ولا يرمي أخطاء للـpipeline."""
    try:
        return _recognize_page(image, config)
    except Exception as exc:  # المحرك الاحتياطي لازم يكمّل مهما حصل.
        return _error(f"تعذر تشغيل Indra OCR: {exc}")


def _recognize_page(image: np.ndarray, config: PipelineConfig) -> IndraPage:
    python = find_python(config)
    if python is None:
        return _error("Indra OCR غير مثبت أو مسار Python غير مضبوط.")
    if image is None or image.size == 0:
        return _error("صورة Indra OCR فارغة أو غير صالحة.")

    root = Path(__file__).resolve().parents[2]
    worker = root / "tools" / "indra_ocr_worker.py"
    with tempfile.TemporaryDirectory(prefix="ocr-indra-") as temp_dir:
        input_path = Path(temp_dir) / "page.png"
        try:
            saved = cv2.imwrite(str(input_path), image)
        except (cv2.error, OSError) as exc:
            return _error(f"تعذر حفظ صورة Indra OCR المؤقتة: {exc}")
        if not saved:
            return _error("تعذر حفظ صورة Indra OCR المؤقتة.")
        env = dict(os.environ)
        local_models = root / "vendor" / "indra-models"
        if not env.get("INDRA_OCR_MODEL_DIR") and local_models.is_dir():
            env["INDRA_OCR_MODEL_DIR"] = str(local_models)
        try:
            completed = subprocess.run(
                [str(python), str(worker), str(input_path)],
                capture_output=True,
                text=True,
                timeout=config.indra_timeout,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return _error("انتهت مهلة Indra OCR.")
        except OSError as exc:
            return _error(f"تعذر تشغيل Indra OCR: {exc}")
        if completed.returncode != 0:
            detail = (completed.stderr or "").strip().splitlines()
            suffix = f": {detail[-1]}" if detail else ""
            return _error(f"فشل Indra OCR{suffix}")
        try:
            payload: dict[str, Any] = json.loads(completed.stdout)
            lines = []
            for item in payload.get("lines", []):
                box = tuple(float(value) for value in item.get("box", []))
                if len(box) != 4:
                    continue
                text = " ".join(str(item.get("text", "")).split())
                if text:
                    lines.append(IndraLine(box, text, float(item.get("conf", 0.0) or 0.0)))
            return IndraPage(
                lines=lines,
                rotation=payload.get("rotation", 0) or 0,
                skew=float(payload.get("skew", 0.0) or 0.0),
                ms=float(payload.get("ms", 0.0) or 0.0),
                error=str(payload.get("error") or "") or None,
            )
        except (AttributeError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return _error(f"نتيجة Indra OCR غير صالحة: {exc}")

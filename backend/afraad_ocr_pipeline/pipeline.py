from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from .config import PipelineConfig
from .grid import detect_grid
from .models import OCRResult, PipelineResult
from .paddle_engine import recognize_many as paddle_recognize_many
from .tesseract_engine import recognize as tess_recognize, recognize_raw


class TableOCRPipeline:
    def __init__(self, config: PipelineConfig | None = None):
        self.config = config or PipelineConfig.from_env()

    def run(self, image: np.ndarray) -> PipelineResult:
        grid = detect_grid(image, self.config)
        warnings = list(grid.warnings)
        if not grid.ok:
            raw = recognize_raw(image, self.config)
            if self.config.use_paddle_fallback:
                paddle_raw = paddle_recognize_many([image], self.config)[0]
                if paddle_raw.text and not raw.text:
                    raw = paddle_raw
                    warnings.append("تم استخدام PaddleOCR كنص خام احتياطي.")
            warnings.append("تم استخدام OCR الخام لأن ثقة شبكة الجدول غير كافية.")
            return PipelineResult(False, "raw-fallback", grid, [], raw, warnings, None)

        cells: list[dict[str, Any]] = []
        crops: list[np.ndarray] = []
        tess_results: list[OCRResult] = []
        cell_refs: list[Any] = []
        for cell in grid.cells:
            crop = grid.processed_image[cell.y1 : cell.y2, cell.x1 : cell.x2]
            if crop.size == 0:
                continue
            multiline = cell.height > cell.width * 0.55
            result = tess_recognize(crop, self.config, multiline=multiline)
            tess_results.append(result)
            crops.append(crop)
            cell_refs.append(cell)

        paddle_results: dict[int, OCRResult] = {}
        # Perspective-distorted photos need a second recognizer even when
        # Tesseract reports high confidence. Blank cells remain skipped.
        perspective = grid.method.startswith("perspective+")
        candidates = [index for index, result in enumerate(tess_results)
                      if result.error or (result.text and (perspective or result.confidence < 42))]
        if self.config.use_paddle_fallback and candidates:
            fallback = paddle_recognize_many([crops[index] for index in candidates], self.config)
            paddle_results = dict(zip(candidates, fallback))

        for index, (cell, result) in enumerate(zip(cell_refs, tess_results)):
            fallback_used = False
            paddle = paddle_results.get(index)
            alternatives = [{"engine": result.engine, "text": result.text, "confidence": round(result.confidence, 2)}]
            if paddle:
                alternatives.append({"engine": paddle.engine, "text": paddle.text,
                                     "confidence": round(paddle.confidence * 100, 2), "error": paddle.error})
            # These confidence scores are not calibrated across engines.
            if paddle and paddle.text and (not result.text or (paddle.confidence >= .8 and (perspective or result.confidence < 42))):
                result = paddle
                fallback_used = True
            cells.append({
                "row": cell.row,
                "col": cell.col,
                "semantic": cell.semantic,
                "bbox": [cell.x1, cell.y1, cell.x2, cell.y2],
                "text": result.text,
                "confidence": round(result.confidence * (100 if result.engine == "paddle" else 1), 2),
                "engine": result.engine,
                "fallback": fallback_used,
                "error": result.error,
                "alternatives": alternatives,
            })

        if not cells:
            raw = recognize_raw(image, self.config)
            warnings.append("تعذر OCR للخلايا؛ تم إرجاع النص الخام.")
            return PipelineResult(False, "raw-fallback", grid, [], raw, warnings, None)
        if perspective:
            warnings.append("الصورة ذات منظور قوي؛ راجع النصوص يدويًا، خصوصًا الأسماء والأرقام.")
        return PipelineResult(True, "cell-grid", grid, cells, None, warnings, None)

    def raw(self, image: np.ndarray) -> OCRResult:
        return recognize_raw(image, self.config)



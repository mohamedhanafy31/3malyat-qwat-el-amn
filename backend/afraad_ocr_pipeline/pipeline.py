from __future__ import annotations

from typing import Any

import numpy as np

from .config import PipelineConfig
from .grid import detect_grid
from .indra_engine import IndraLine, IndraPage, recognize_page as indra_recognize_page
from .models import Cell, OCRResult, PipelineResult
from .paddle_engine import recognize_many as paddle_recognize_many
from .tesseract_engine import recognize as tess_recognize, recognize_raw


def _confidence_100(value: float) -> float:
    value = float(value or 0.0)
    return value * 100 if 0 <= value <= 1 else value


def _assign_indra_lines(lines: list[IndraLine], cells: list[Cell]) -> dict[tuple[int, int], list[IndraLine]]:
    """يربط كل سطر بالخلية اللي جواها مركز الـbox."""
    assigned: dict[tuple[int, int], list[IndraLine]] = {}
    for line in lines:
        x1, y1, x2, y2 = line.box
        centre_x = (x1 + x2) / 2
        centre_y = (y1 + y2) / 2
        for cell in cells:
            if cell.x1 <= centre_x <= cell.x2 and cell.y1 <= centre_y <= cell.y2:
                assigned.setdefault((cell.row, cell.col), []).append(line)
                break
    for cell_lines in assigned.values():
        cell_lines.sort(key=lambda item: (item.box[1], item.box[0]))
    return assigned


def _indra_result(lines: list[IndraLine]) -> OCRResult:
    text = " ".join(line.text for line in lines if line.text)
    values = [_confidence_100(line.confidence) for line in lines if line.text]
    return OCRResult(
        text=text,
        confidence=sum(values) / len(values) if values else 0.0,
        engine="indra",
        data=[{"box": list(line.box), "text": line.text, "confidence": line.confidence}
              for line in lines],
    )


def _alternative(result: OCRResult) -> dict[str, Any]:
    confidence = _confidence_100(result.confidence) if result.engine == "paddle" else result.confidence
    return {
        "engine": result.engine,
        "text": result.text,
        "confidence": round(confidence, 2),
        **({"error": result.error} if result.error else {}),
    }


class TableOCRPipeline:
    def __init__(self, config: PipelineConfig | None = None):
        self.config = config or PipelineConfig.from_env()

    def _run_indra(self, image: np.ndarray, warnings: list[str]) -> IndraPage | None:
        if not self.config.use_indra:
            return None
        page = indra_recognize_page(image, self.config)
        if page.error:
            warnings.append(f"Indra OCR غير متاح؛ تم الرجوع للمحرك الاحتياطي. {page.error}")
        return page

    def _raw_fallback(self, image: np.ndarray, grid, warnings: list[str]) -> PipelineResult:
        page = self._run_indra(image, warnings)
        if page and not page.error and page.text:
            raw = OCRResult(
                text=page.text,
                confidence=round(_confidence_100(page.confidence), 2),
                engine="indra",
                data=[{"box": list(line.box), "text": line.text, "confidence": line.confidence}
                      for line in page.lines],
            )
        else:
            raw = recognize_raw(image, self.config)
            if self.config.use_paddle_fallback:
                paddle_raw = paddle_recognize_many([image], self.config)[0]
                if paddle_raw.text and not raw.text:
                    raw = paddle_raw
                    warnings.append("تم استخدام PaddleOCR كنص خام احتياطي.")
        warnings.append("تم استخدام OCR الخام لأن ثقة شبكة الجدول غير كافية.")
        return PipelineResult(False, "raw-fallback", grid, [], raw, warnings, None)

    def run(self, image: np.ndarray) -> PipelineResult:
        grid = detect_grid(image, self.config)
        warnings = list(grid.warnings)
        if not grid.ok:
            return self._raw_fallback(image, grid, warnings)

        page = self._run_indra(grid.processed_image, warnings)
        indra_ok = bool(page is not None and not page.error)
        assigned = _assign_indra_lines(page.lines, grid.cells) if indra_ok and page else {}

        records: list[tuple[Cell, np.ndarray, list[IndraLine]]] = []
        for cell in grid.cells:
            crop = grid.processed_image[cell.y1:cell.y2, cell.x1:cell.x2]
            if crop.size:
                records.append((cell, crop, assigned.get((cell.row, cell.col), [])))

        # Indra بيقرأ الصفحة مرة؛ Tesseract للخلايا الفاضية بس.
        tess_results: dict[int, OCRResult] = {}
        for index, (cell, crop, lines) in enumerate(records):
            if lines:
                continue
            multiline = cell.height > cell.width * 0.55
            tess_results[index] = tess_recognize(crop, self.config, multiline=multiline)

        perspective = grid.method.startswith("perspective+")
        candidates = [
            index for index, result in tess_results.items()
            if result.error or (result.text and (perspective or result.confidence < 42))
        ]
        paddle_results: dict[int, OCRResult] = {}
        if self.config.use_paddle_fallback and candidates:
            fallback = paddle_recognize_many([records[index][1] for index in candidates], self.config)
            paddle_results = dict(zip(candidates, fallback))

        cells: list[dict[str, Any]] = []
        for index, (cell, _crop, lines) in enumerate(records):
            alternatives: list[dict[str, Any]] = []
            fallback_used = False
            if lines:
                result = _indra_result(lines)
                alternatives.append(_alternative(result))
            else:
                tess = tess_results[index]
                if indra_ok:
                    alternatives.append(_alternative(_indra_result([])))
                alternatives.append(_alternative(tess))
                result = tess
                paddle = paddle_results.get(index)
                if paddle:
                    alternatives.append(_alternative(paddle))
                    if paddle.text and (not tess.text or (
                        paddle.confidence >= .8 and (perspective or tess.confidence < 42)
                    )):
                        result = paddle
                # فراغ Indra موثوق؛ نشيل نوش Tesseract الضعيف.
                if indra_ok and result.engine == "tesseract" and result.text and result.confidence < 60:
                    result = _indra_result([])
                elif indra_ok and not result.text:
                    result = _indra_result([])
                fallback_used = result.engine != "indra"

            confidence = _confidence_100(result.confidence) if result.engine == "paddle" else result.confidence
            cells.append({
                "row": cell.row,
                "col": cell.col,
                "semantic": cell.semantic,
                "bbox": [cell.x1, cell.y1, cell.x2, cell.y2],
                "text": result.text,
                "confidence": round(confidence, 2),
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
        page = indra_recognize_page(image, self.config) if self.config.use_indra else None
        if page and not page.error and page.text:
            return OCRResult(page.text, round(_confidence_100(page.confidence), 2), "indra")
        return recognize_raw(image, self.config)

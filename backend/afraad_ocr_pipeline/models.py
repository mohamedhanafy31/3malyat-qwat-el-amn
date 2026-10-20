from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True)
class Line:
    position: int
    start: int
    end: int
    strength: float


@dataclass(frozen=True)
class Cell:
    row: int
    col: int
    x1: int
    y1: int
    x2: int
    y2: int
    semantic: str | None = None

    @property
    def width(self) -> int:
        return max(0, self.x2 - self.x1)

    @property
    def height(self) -> int:
        return max(0, self.y2 - self.y1)


@dataclass
class OCRResult:
    text: str = ""
    confidence: float = 0.0
    engine: str = "none"
    error: str | None = None
    data: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class GridResult:
    ok: bool
    confidence: float
    method: str
    width: int
    height: int
    horizontal: list[Line] = field(default_factory=list)
    vertical: list[Line] = field(default_factory=list)
    cells: list[Cell] = field(default_factory=list)
    table_bbox: tuple[int, int, int, int] | None = None
    overlay_png: bytes | None = None
    warnings: list[str] = field(default_factory=list)
    # Cell coordinates refer to this image, not necessarily the uploaded image.
    processed_image: Any = field(default=None, repr=False)


@dataclass
class PipelineResult:
    ok: bool
    mode: str
    grid: GridResult
    cells: list[dict[str, Any]] = field(default_factory=list)
    raw_ocr: OCRResult | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "grid": {
                "ok": self.grid.ok,
                "confidence": round(self.grid.confidence, 3),
                "method": self.grid.method,
                "width": self.grid.width,
                "height": self.grid.height,
                "table_bbox": self.grid.table_bbox,
                "horizontal_lines": [line.position for line in self.grid.horizontal],
                "vertical_lines": [line.position for line in self.grid.vertical],
                "cell_count": len(self.grid.cells),
                "warnings": self.grid.warnings,
            },
            "cells": self.cells,
            "raw_ocr": None if self.raw_ocr is None else {
                "text": self.raw_ocr.text,
                "confidence": round(self.raw_ocr.confidence, 2),
                "engine": self.raw_ocr.engine,
                "error": self.raw_ocr.error,
            },
            "warnings": self.warnings,
            "error": self.error,
        }



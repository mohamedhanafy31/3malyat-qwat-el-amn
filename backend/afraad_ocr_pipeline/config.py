from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class PipelineConfig:
    # The current form is expected to have five logical columns. Change this
    # order only when the physical layout is confirmed from a real table image.
    semantic_columns: list[str] = field(
        default_factory=lambda: ["schedule", "evening", "morning", "service", "code"]
    )
    min_lines: int = 3
    min_cell_width: int = 18
    min_cell_height: int = 14
    line_merge_tolerance: int = 6
    line_gap_ratio: float = 0.18
    min_intersection_ratio: float = 0.45
    min_grid_confidence: float = 0.45
    crop_padding: int = 4
    max_image_pixels: int = 20_000_000
    max_upload_bytes: int = 10 * 1024 * 1024
    tesseract_timeout: int = 20
    paddle_timeout: int = 180
    tesseract_lang: str = "ara"
    tesseract_cell_psm: int = 7
    tesseract_multiline_psm: int = 6
    tesseract_raw_psm: int = 3
    use_paddle_fallback: bool = True
    paddle_python: str | None = None

    @classmethod
    def from_env(cls) -> "PipelineConfig":
        config = cls()
        config.paddle_python = os.environ.get("PADDLE_PYTHON") or None
        config.use_paddle_fallback = os.environ.get(
            "OCR_DISABLE_PADDLE", "0"
        ).lower() not in {"1", "true", "yes"}
        return config



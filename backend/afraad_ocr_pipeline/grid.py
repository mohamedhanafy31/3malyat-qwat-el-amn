from __future__ import annotations

import math

import cv2
import numpy as np

from .config import PipelineConfig
from .image_ops import line_masks, prepare_image, projection_peaks
from .models import Cell, GridResult, Line


def _merge_positions(values: list[tuple[int, int, int, float]], tolerance: int) -> list[Line]:
    if not values:
        return []
    values = sorted(values)
    merged: list[list[tuple[int, int, int, float]]] = []
    for item in values:
        if not merged or item[0] - merged[-1][-1][0] > tolerance:
            merged.append([item])
        else:
            merged[-1].append(item)
    lines = []
    for group in merged:
        weight = sum(max(item[3], 1.0) for item in group)
        position = round(sum(item[0] * max(item[3], 1.0) for item in group) / weight)
        lines.append(
            Line(
                position=position,
                start=min(item[1] for item in group),
                end=max(item[2] for item in group),
                strength=min(1.0, max(item[3] for item in group) / 255.0),
            )
        )
    return lines


def _recover_spans(mask: np.ndarray, lines: list[Line], horizontal: bool) -> list[Line]:
    """Recover the perpendicular span; projection grouping only knows thickness."""
    height, width = mask.shape[:2]
    result = []
    for line in lines:
        radius = max(2, (line.end - line.start) // 2 + 1)
        if horizontal:
            band = mask[max(0, line.position - radius) : min(height, line.position + radius + 1), :]
            coordinates = np.where(band > 0)[1]
            start, end = (int(coordinates.min()), int(coordinates.max())) if coordinates.size else (0, width - 1)
        else:
            band = mask[:, max(0, line.position - radius) : min(width, line.position + radius + 1)]
            coordinates = np.where(band > 0)[0]
            start, end = (int(coordinates.min()), int(coordinates.max())) if coordinates.size else (0, height - 1)
        result.append(Line(line.position, start, end, line.strength))
    return result


def _keep_spaced(lines: list[Line], minimum: int) -> list[Line]:
    result: list[Line] = []
    for line in lines:
        if not result or line.position - result[-1].position >= minimum:
            result.append(line)
        elif line.strength > result[-1].strength:
            result[-1] = line
    return result


def _intersection_ratio(horizontal: list[Line], vertical: list[Line], shape: tuple[int, int]) -> float:
    height, width = shape
    if not horizontal or not vertical:
        return 0.0
    hits = 0
    possible = len(horizontal) * len(vertical)
    for h_line in horizontal:
        for v_line in vertical:
            if h_line.start <= v_line.position <= h_line.end and v_line.start <= h_line.position <= v_line.end:
                hits += 1
    span_score = min(1.0, sum(max(0, line.end - line.start) for line in horizontal) / (len(horizontal) * width))
    span_score += min(1.0, sum(max(0, line.end - line.start) for line in vertical) / (len(vertical) * height))
    return 0.7 * (hits / possible) + 0.3 * (span_score / 2)


def _table_bbox(horizontal: list[Line], vertical: list[Line], width: int, height: int) -> tuple[int, int, int, int] | None:
    if len(horizontal) < 2 or len(vertical) < 2:
        return None
    x1, x2 = vertical[0].position, vertical[-1].position
    y1, y2 = horizontal[0].position, horizontal[-1].position
    if x2 <= x1 or y2 <= y1:
        return None
    if (x2 - x1) < width * 0.15 or (y2 - y1) < height * 0.08:
        return None
    return (x1, y1, x2, y2)


def _make_cells(horizontal: list[Line], vertical: list[Line], config: PipelineConfig) -> list[Cell]:
    cells: list[Cell] = []
    column_names = config.semantic_columns
    for row, (top, bottom) in enumerate(zip(horizontal, horizontal[1:])):
        for col, (left, right) in enumerate(zip(vertical, vertical[1:])):
            x1 = left.position + config.crop_padding
            y1 = top.position + config.crop_padding
            x2 = right.position - config.crop_padding
            y2 = bottom.position - config.crop_padding
            if x2 - x1 < config.min_cell_width or y2 - y1 < config.min_cell_height:
                continue
            semantic = column_names[col] if col < len(column_names) else None
            cells.append(Cell(row, col, x1, y1, x2, y2, semantic))
    return cells


def _overlay(image: np.ndarray, horizontal: list[Line], vertical: list[Line], cells: list[Cell]) -> bytes:
    canvas = image.copy()
    for line in horizontal:
        cv2.line(canvas, (line.start, line.position), (line.end, line.position), (0, 180, 255), 2)
    for line in vertical:
        cv2.line(canvas, (line.position, line.start), (line.position, line.end), (255, 100, 0), 2)
    for cell in cells:
        cv2.rectangle(canvas, (cell.x1, cell.y1), (cell.x2, cell.y2), (0, 220, 0), 1)
        cv2.putText(canvas, f"{cell.row},{cell.col}", (cell.x1 + 2, cell.y1 + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 220), 1)
    ok, encoded = cv2.imencode(".png", canvas)
    return encoded.tobytes() if ok else b""


def _grid_roi(horizontal_mask: np.ndarray, vertical_mask: np.ndarray) -> tuple[int, int, int, int] | None:
    """Locate a connected ruled table before measuring line coverage.

    Measuring projection against the entire camera frame rejects small or
    off-centre tables even when their own lines are complete.
    """
    height, width = horizontal_mask.shape
    joined = cv2.bitwise_or(horizontal_mask, vertical_mask)
    joined = cv2.morphologyEx(joined, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(joined, 8)
    candidates = []
    for x, y, w, h, area in stats[1:count]:
        if w < width * 0.18 or h < height * 0.10 or w * h < width * height * 0.025:
            continue
        h_pixels = cv2.countNonZero(horizontal_mask[y:y+h, x:x+w])
        v_pixels = cv2.countNonZero(vertical_mask[y:y+h, x:x+w])
        if min(h_pixels, v_pixels) < 0.5 * min(w, h):
            continue
        candidates.append((min(h_pixels, v_pixels), int(x), int(y), int(w), int(h)))
    if not candidates:
        return None
    _, x, y, w, h = max(candidates)
    pad = 3
    return max(0, x-pad), max(0, y-pad), min(width, x+w+pad), min(height, y+h+pad)


def _fill_missing_rows(gray: np.ndarray, horizontal: list[Line], vertical: list[Line], config: PipelineConfig) -> list[Line]:
    """Use long Hough segments only inside suspiciously large row gaps."""
    if len(horizontal) < 4 or len(vertical) < 2:
        return horizontal
    gaps = np.diff([line.position for line in horizontal])
    normal = float(np.median(gaps))
    large = [(a.position, b.position) for a, b in zip(horizontal, horizontal[1:])
             if b.position - a.position > max(2.2 * normal, 80)]
    if not large:
        return horizontal
    x1, x2 = vertical[0].position, vertical[-1].position
    minimum = max(80, int((x2-x1) * .45))
    segments = cv2.HoughLinesP(cv2.Canny(gray, 50, 150), 1, math.pi/720,
                               threshold=40, minLineLength=minimum, maxLineGap=40)
    if segments is None:
        return horizontal
    additions = []
    for ax, ay, bx, by in segments[:, 0]:
        dx, dy = bx-ax, by-ay
        if abs(dx) < minimum or abs(dy) > abs(dx) * .07:
            continue
        y = round((ay+by)/2)
        if any(top + normal*.4 < y < bottom - normal*.4 for top, bottom in large):
            additions.append((y, min(ax, bx), max(ax, bx), float(abs(dx))))
    if not additions:
        return horizontal
    combined = [(line.position, line.start, line.end, line.strength*255) for line in horizontal] + additions
    return _keep_spaced(_merge_positions(combined, config.line_merge_tolerance), config.min_cell_height)


def detect_grid(image: np.ndarray, config: PipelineConfig | None = None, _deskew: bool = False, _perspective: bool = False) -> GridResult:
    config = config or PipelineConfig()
    prepared = prepare_image(image, deskew=_deskew, perspective=_perspective)
    height, width = prepared.gray.shape[:2]
    horizontal_mask, vertical_mask = line_masks(prepared.binary)
    roi = _grid_roi(horizontal_mask, vertical_mask)
    if roi:
        x1, y1, x2, y2 = roi
        raw_h = [(p+y1, a+y1, b+y1, s) for p, a, b, s in projection_peaks(horizontal_mask[y1:y2, x1:x2], axis=1, min_coverage=0.30)]
        raw_v = [(p+x1, a+x1, b+x1, s) for p, a, b, s in projection_peaks(vertical_mask[y1:y2, x1:x2], axis=0, min_coverage=0.30)]
    else:
        raw_h = projection_peaks(horizontal_mask, axis=1, min_coverage=0.30)
        raw_v = projection_peaks(vertical_mask, axis=0, min_coverage=0.30)
    horizontal = _keep_spaced(_merge_positions(raw_h, config.line_merge_tolerance), config.min_cell_height)
    vertical = _keep_spaced(_merge_positions(raw_v, config.line_merge_tolerance), config.min_cell_width)
    horizontal = _recover_spans(horizontal_mask, horizontal, horizontal=True)
    vertical = _recover_spans(vertical_mask, vertical, horizontal=False)

    # A line may be broken by text or compression. Hough fallback contributes
    # only long near-horizontal/near-vertical segments.
    if len(horizontal) < config.min_lines or len(vertical) < config.min_lines:
        edges = cv2.Canny(prepared.gray, 50, 150, apertureSize=3)
        segments = cv2.HoughLinesP(edges, 1, math.pi / 180, threshold=max(25, min(width, height) // 8), minLineLength=max(40, min(width, height) // 5), maxLineGap=max(8, min(width, height) // 80))
        h_extra: list[tuple[int, int, int, float]] = []
        v_extra: list[tuple[int, int, int, float]] = []
        if segments is not None:
            for x1, y1, x2, y2 in segments[:, 0]:
                dx, dy = x2 - x1, y2 - y1
                length = float(math.hypot(dx, dy))
                if abs(dy) <= max(3, abs(dx) * 0.05):
                    h_extra.append((round((y1 + y2) / 2), min(x1, x2), max(x1, x2), length))
                elif abs(dx) <= max(3, abs(dy) * 0.05):
                    v_extra.append((round((x1 + x2) / 2), min(y1, y2), max(y1, y2), length))
        horizontal = _keep_spaced(_merge_positions([(line.position, line.start, line.end, line.strength * 255) for line in horizontal] + h_extra, config.line_merge_tolerance), config.min_cell_height)
        vertical = _keep_spaced(_merge_positions([(line.position, line.start, line.end, line.strength * 255) for line in vertical] + v_extra, config.line_merge_tolerance), config.min_cell_width)

    horizontal = _fill_missing_rows(prepared.gray, horizontal, vertical, config)

    bbox = _table_bbox(horizontal, vertical, width, height)
    intersection = _intersection_ratio(horizontal, vertical, (height, width))
    expected_cols = len(config.semantic_columns)
    structure_score = min(1.0, len(vertical) / max(expected_cols + 1, 1))
    confidence = 0.55 * intersection + 0.30 * structure_score + 0.15 * min(1.0, len(horizontal) / 4)
    cells = _make_cells(horizontal, vertical, config)
    warnings: list[str] = []
    if len(horizontal) >= 4:
        gaps = np.diff([line.position for line in horizontal])
        if max(gaps) > max(2.2 * float(np.median(gaps)), 80):
            warnings.append("قد توجد صفوف غير مكتشفة في فجوة كبيرة بين خطوط الجدول.")
    if len(vertical) - 1 != expected_cols:
        warnings.append(f"تم اكتشاف {max(0, len(vertical)-1)} أعمدة، والمتوقع {expected_cols}.")
    if not bbox:
        warnings.append("لم يتم العثور على إطار جدول صالح.")
    if len(cells) == 0:
        warnings.append("لم يتم إنشاء أي خلية صالحة.")
    ok = bbox is not None and confidence >= config.min_grid_confidence and len(cells) >= expected_cols and len(vertical) - 1 == expected_cols
    method = "localized-morphology+projection" if roi else ("morphology+projection" if raw_h and raw_v else "hough-fallback")
    if _deskew:
        method = "deskew+" + method
    if _perspective:
        method = "perspective+" + method
    overlay = _overlay(prepared.original, horizontal, vertical, cells)
    result = GridResult(ok, confidence, method, width, height, horizontal, vertical, cells, bbox, overlay, warnings, prepared.original)
    if not _deskew and not _perspective and not result.ok:
        alternative = detect_grid(image, config, _deskew=True)
        if alternative.ok or (len(alternative.vertical) > len(result.vertical) and alternative.confidence > result.confidence):
            return alternative
        perspective = detect_grid(image, config, _perspective=True)
        if perspective.ok:
            return perspective
    return result



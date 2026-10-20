from __future__ import annotations

from dataclasses import dataclass
import math

import cv2
import numpy as np


@dataclass
class PreparedImage:
    original: np.ndarray
    gray: np.ndarray
    binary: np.ndarray
    scale: float


def _order_quad(points: np.ndarray) -> np.ndarray:
    ordered = np.zeros((4, 2), dtype=np.float32)
    sums = points.sum(axis=1)
    diffs = np.diff(points, axis=1).reshape(-1)
    ordered[0] = points[np.argmin(sums)]
    ordered[2] = points[np.argmax(sums)]
    ordered[1] = points[np.argmin(diffs)]
    ordered[3] = points[np.argmax(diffs)]
    return ordered


def rectify_quad(image: np.ndarray) -> np.ndarray:
    """Rectify a dominant quadrilateral only when evidence is strong."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    height, width = gray.shape
    image_area = float(height * width)
    candidates: list[tuple[float, np.ndarray]] = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < image_area * 0.25 or area > image_area * 0.98:
            continue
        perimeter = cv2.arcLength(contour, True)
        polygon = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        if len(polygon) == 4 and cv2.isContourConvex(polygon):
            candidates.append((area, polygon.reshape(4, 2).astype(np.float32)))
    if not candidates:
        return image
    _, quad = max(candidates, key=lambda item: item[0])
    source = _order_quad(quad)
    # Do not resample an already axis-aligned table; preserving pixel geometry
    # is important when several thin grid lines are close together.
    top_slope = abs(source[1, 1] - source[0, 1]) / max(1.0, np.linalg.norm(source[1] - source[0]))
    bottom_slope = abs(source[2, 1] - source[3, 1]) / max(1.0, np.linalg.norm(source[2] - source[3]))
    left_slope = abs(source[3, 0] - source[0, 0]) / max(1.0, np.linalg.norm(source[3] - source[0]))
    right_slope = abs(source[2, 0] - source[1, 0]) / max(1.0, np.linalg.norm(source[2] - source[1]))
    if max(top_slope, bottom_slope, left_slope, right_slope) < 0.04:
        return image
    target_width = max(int(np.linalg.norm(source[1] - source[0])), int(np.linalg.norm(source[2] - source[3])))
    target_height = max(int(np.linalg.norm(source[3] - source[0])), int(np.linalg.norm(source[2] - source[1])))
    if target_width < 200 or target_height < 100:
        return image
    target = np.array([[0, 0], [target_width - 1, 0], [target_width - 1, target_height - 1], [0, target_height - 1]], dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(source, target)
    return cv2.warpPerspective(image, matrix, (target_width, target_height), borderValue=(255, 255, 255))


def deskew_lines(image: np.ndarray) -> np.ndarray:
    """Estimate page skew from long near-horizontal/vertical ruled lines."""
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    minimum = max(65, min(width, height) // 10)
    segments = cv2.HoughLinesP(edges, 1, np.pi / 720, threshold=45,
                               minLineLength=minimum, maxLineGap=15)
    if segments is None:
        return image
    angles = []
    weights = []
    for x1, y1, x2, y2 in segments[:, 0]:
        length = math.hypot(x2-x1, y2-y1)
        angle = math.degrees(math.atan2(y2-y1, x2-x1))
        normalized = (angle + 45) % 90 - 45
        if length >= minimum and abs(normalized) <= 18:
            angles.append(normalized)
            weights.append(length)
    if len(angles) < 4 or sum(weights) < 2 * max(width, height):
        return image
    order = np.argsort(angles)
    cumulative = np.cumsum(np.asarray(weights)[order])
    skew = float(np.asarray(angles)[order][np.searchsorted(cumulative, cumulative[-1] / 2)])
    if abs(skew) < 1 or abs(skew) > 15:
        return image
    rotation = cv2.getRotationMatrix2D((width / 2, height / 2), skew, 1.0)
    sine, cosine = abs(rotation[0, 1]), abs(rotation[0, 0])
    new_width = int(height * sine + width * cosine)
    new_height = int(height * cosine + width * sine)
    rotation[0, 2] += (new_width-width) / 2
    rotation[1, 2] += (new_height-height) / 2
    return cv2.warpAffine(image, rotation, (new_width, new_height),
                          borderValue=(255, 255, 255))


def rectify_outer_lines(image: np.ndarray) -> np.ndarray:
    """Conservative perspective fallback using the four outer ruled edges."""
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    segments = cv2.HoughLinesP(cv2.Canny(gray, 50, 150), 1, np.pi / 720,
                               threshold=70, minLineLength=max(100, min(width, height) // 5),
                               maxLineGap=40)
    if segments is None:
        return image
    horizontal, vertical = [], []
    for x1, y1, x2, y2 in segments[:, 0]:
        dx, dy = x2-x1, y2-y1
        if abs(dx) >= width * .55 and abs(dy) < abs(dx) * .27:
            y_middle = y1 + (width / 2 - x1) * dy / dx
            horizontal.append((y_middle, np.array([x1, y1, x2, y2], dtype=float)))
        if abs(dy) >= height * .24 and abs(dx) < abs(dy) * .27:
            x_middle = x1 + (height / 2 - y1) * dx / dy
            vertical.append((x_middle, np.array([x1, y1, x2, y2], dtype=float)))
    if len(horizontal) < 2 or len(vertical) < 2:
        return image
    top, bottom = min(horizontal, key=lambda item: item[0])[1], max(horizontal, key=lambda item: item[0])[1]
    left, right = min(vertical, key=lambda item: item[0])[1], max(vertical, key=lambda item: item[0])[1]

    def intersection(a: np.ndarray, b: np.ndarray) -> np.ndarray | None:
        x1, y1, x2, y2 = a
        x3, y3, x4, y4 = b
        direction = np.array([[x2-x1, x3-x4], [y2-y1, y3-y4]], dtype=float)
        if abs(np.linalg.det(direction)) < 1e-5:
            return None
        t, _ = np.linalg.solve(direction, np.array([x3-x1, y3-y1]))
        return np.array([x1+t*(x2-x1), y1+t*(y2-y1)], dtype=np.float32)

    corners = [intersection(top, left), intersection(top, right),
               intersection(bottom, right), intersection(bottom, left)]
    if any(point is None for point in corners):
        return image
    quad = np.asarray(corners, dtype=np.float32)
    if (np.any(quad[:, 0] < -width*.2) or np.any(quad[:, 0] > width*1.2)
            or np.any(quad[:, 1] < -height*.2) or np.any(quad[:, 1] > height*1.2)
            or cv2.contourArea(quad) < width*height*.15):
        return image
    target_width = int(max(np.linalg.norm(quad[1]-quad[0]), np.linalg.norm(quad[2]-quad[3])))
    target_height = int(max(np.linalg.norm(quad[3]-quad[0]), np.linalg.norm(quad[2]-quad[1])))
    if min(target_width, target_height) < 200:
        return image
    target = np.array([[0, 0], [target_width-1, 0], [target_width-1, target_height-1], [0, target_height-1]], dtype=np.float32)
    return cv2.warpPerspective(image, cv2.getPerspectiveTransform(quad, target),
                               (target_width, target_height), borderValue=(255, 255, 255))


def prepare_image(image: np.ndarray, max_side: int = 2400, deskew: bool = False, perspective: bool = False) -> PreparedImage:
    if image is None or image.size == 0:
        raise ValueError("الصورة فارغة أو غير صالحة")

    original = image.copy()
    scale = 1.0
    h, w = image.shape[:2]
    if max(h, w) > max_side:
        scale = max_side / max(h, w)
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    rectified = rectify_quad(rectify_outer_lines(image) if perspective else (deskew_lines(image) if deskew else image))
    gray = cv2.cvtColor(rectified, cv2.COLOR_BGR2GRAY)
    gray = cv2.medianBlur(gray, 3)

    # Adaptive threshold is more stable for phone photos; Otsu is used as a
    # clean fallback for screenshots and evenly lit scans.
    adaptive = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        15,
    )
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    binary = adaptive if cv2.countNonZero(adaptive) < gray.size * 0.55 else otsu
    return PreparedImage(original=rectified, gray=gray, binary=binary, scale=scale)


def remove_border(mask: np.ndarray, border: int = 2) -> np.ndarray:
    result = mask.copy()
    result[:border, :] = 0
    result[-border:, :] = 0
    result[:, :border] = 0
    result[:, -border:] = 0
    return result


def line_masks(binary: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    height, width = binary.shape[:2]
    horizontal_len = max(20, width // 18)
    vertical_len = max(20, height // 18)
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (horizontal_len, 1))
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, vertical_len))
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, h_kernel)
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, v_kernel)
    close_h = cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, width // 120), 3))
    close_v = cv2.getStructuringElement(cv2.MORPH_RECT, (3, max(3, height // 120)))
    horizontal = cv2.morphologyEx(horizontal, cv2.MORPH_CLOSE, close_h)
    vertical = cv2.morphologyEx(vertical, cv2.MORPH_CLOSE, close_v)
    return remove_border(horizontal), remove_border(vertical)


def projection_peaks(mask: np.ndarray, axis: int, min_coverage: float) -> list[tuple[int, int, int, float]]:
    projection = (mask > 0).sum(axis=axis)
    # Summing axis=1 produces one value per row and therefore measures
    # horizontal coverage across width; summing axis=0 measures vertical
    # coverage across height.
    required = int(mask.shape[axis] * min_coverage)
    active = projection >= max(2, required)
    groups: list[tuple[int, int]] = []
    start: int | None = None
    for index, is_active in enumerate(active):
        if is_active and start is None:
            start = index
        elif not is_active and start is not None:
            groups.append((start, index - 1))
            start = None
    if start is not None:
        groups.append((start, len(active) - 1))
    return [
        (round((start + end) / 2), start, end, float(projection[start : end + 1].max()))
        for start, end in groups
    ]



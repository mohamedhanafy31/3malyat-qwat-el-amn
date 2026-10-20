"""Optional PaddleOCR worker. It loads the model once per batch."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
from paddleocr import PaddleOCR


def run_one(ocr: PaddleOCR, path: Path) -> dict:
    image = cv2.imread(str(path))
    if image is None:
        return {"text": "", "confidence": 0.0, "items": [], "error": "صورة غير صالحة"}
    result = ocr.predict(str(path))[0].json["res"]
    texts = result.get("rec_texts", [])
    scores = result.get("rec_scores", [])
    boxes = result.get("rec_boxes", [])
    items = []
    ordered = sorted(
        zip(boxes, texts, scores),
        key=lambda item: ((item[0][1] + item[0][3]) / 2, -(item[0][0] + item[0][2]) / 2),
    )
    for box, text, score in ordered:
        if str(text).strip():
            items.append({"text": str(text).strip(), "score": round(float(score), 3), "box": list(map(float, box))})
    clean = [item for item in items if item["score"] >= 0.35]
    return {
        "text": "\n".join(item["text"] for item in clean),
        "confidence": sum(item["score"] for item in clean) / len(clean) if clean else 0.0,
        "items": clean,
    }


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: paddle_worker.py INPUT_FILE_OR_DIRECTORY OUTPUT_JSON", file=sys.stderr)
        return 2
    source = Path(sys.argv[1])
    destination = Path(sys.argv[2])
    paths = sorted(source.glob("*.png")) if source.is_dir() else [source]
    ocr = PaddleOCR(
        device="cpu",
        cpu_threads=4,
        enable_mkldnn=False,
        text_detection_model_name="PP-OCRv5_mobile_det",
        text_recognition_model_name="arabic_PP-OCRv5_mobile_rec",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )
    results = [run_one(ocr, path) for path in paths]
    payload = {"results": results} if source.is_dir() else results[0]
    destination.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



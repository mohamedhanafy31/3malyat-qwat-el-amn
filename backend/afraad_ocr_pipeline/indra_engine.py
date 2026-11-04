from __future__ import annotations

import json
import logging
import os
import platform
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .. import tech_log
from .config import PipelineConfig

LOG = logging.getLogger(__name__)


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


_ENV_LOGGED = False


def _path_info(path: Path) -> dict[str, Any]:
    try:
        return {"exists": path.exists(), "is_file": path.is_file(), "is_dir": path.is_dir()}
    except OSError as exc:
        return {"error": str(exc)}


def _log_stderr(stderr: str | None, stage: str, limit: int = 25, level: int = logging.WARNING) -> None:
    """آخر سطور stderr بتاع العامل، سطر لكل حدث (الحقل الواحد بيتقصّ عند 300 حرف)."""
    lines = [line for line in (stderr or "").splitlines() if line.strip()]
    if not lines:
        return
    skipped = max(0, len(lines) - limit)
    for index, line in enumerate(lines[-limit:], skipped + 1):
        tech_log.ocr_event("ocr.indra.stderr", level=level, stage=stage,
                           line_no=index, of=len(lines), text=line)


def _log_environment_once(config: PipelineConfig) -> None:
    """صورة كاملة لبيئة تشغيل Indra: أول مرة في كل تشغيل للنظام بس."""
    global _ENV_LOGGED
    if _ENV_LOGGED:
        return
    _ENV_LOGGED = True
    try:
        root = Path(__file__).resolve().parents[2]
        site_dir = root / "vendor" / "indra-site"
        models = root / "vendor" / "indra-models"
        worker = root / "tools" / "indra_ocr_worker.py"
        versions = {}
        for module in ("cv2", "numpy"):
            try:
                versions[module] = getattr(__import__(module), "__version__", "?")
            except Exception as exc:  # noqa: BLE001
                versions[module] = f"import-failed: {exc}"
        model_files = []
        if models.is_dir():
            for item in sorted(models.rglob("*"))[:40]:
                if item.is_file():
                    model_files.append(f"{item.relative_to(models)}={item.stat().st_size}")
        tech_log.ocr_event(
            "ocr.indra.env", platform=platform.platform(), machine=platform.machine(),
            python=sys.version.split()[0], executable=sys.executable,
            use_indra=config.use_indra, timeout_s=config.indra_timeout,
            config_indra_python=config.indra_python,
            env_INDRA_PYTHON=os.environ.get("INDRA_PYTHON"),
            env_INDRA_OCR=os.environ.get("INDRA_OCR"),
            env_INDRA_OCR_MODEL_DIR=os.environ.get("INDRA_OCR_MODEL_DIR"),
            root=str(root), worker=_path_info(worker), site_dir=_path_info(site_dir),
            models_dir=_path_info(models), cpu_count=os.cpu_count(),
            cv2=versions["cv2"], numpy=versions["numpy"],
            locale_encoding=sys.getfilesystemencoding(), stdout_encoding=getattr(sys.stdout, "encoding", None),
        )
        tech_log.ocr_event("ocr.indra.env.models", count=len(model_files),
                           files=", ".join(model_files) or "none")
        if site_dir.is_dir():
            packages = sorted(item.name for item in site_dir.iterdir())[:40]
            tech_log.ocr_event("ocr.indra.env.site", count=len(packages),
                               packages=", ".join(packages))
        else:
            tried = []
            for path in (config.indra_python, os.environ.get("INDRA_PYTHON"),
                         root / ".venv-indra" / "bin" / "python",
                         root / ".venv-indra" / "Scripts" / "python.exe",
                         "~/.venvs/indra-ocr/bin/python"):
                if path:
                    candidate = Path(path).expanduser()
                    tried.append(f"{candidate}:{'ok' if candidate.is_file() else 'missing'}")
            tech_log.ocr_event("ocr.indra.env.python_candidates", tried=" | ".join(tried))
    except Exception:  # التشخيص ما يكسرش الـOCR أبدًا
        tech_log.ocr_event("ocr.indra.env_failed", level=logging.WARNING, exc_info=True)


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
    started = time.perf_counter()
    _log_environment_once(config)
    try:
        page = _recognize_page(image, config)
    except Exception as exc:  # المحرك الاحتياطي لازم يكمّل مهما حصل.
        tech_log.ocr_event("ocr.indra.exception", level=logging.ERROR, exc_info=True,
                           error_type=type(exc).__name__)
        page = _error(f"تعذر تشغيل Indra OCR: {exc}")
    # توافر Indra أهم معلومة تشخيصية: لو page.error فالـpipeline رجع للمحرك الاحتياطي
    tech_log.ocr_event("ocr.indra", available=not page.error,
                       lines=len(page.lines or []), error=page.error,
                       rotation=page.rotation, skew=page.skew, worker_ms=page.ms,
                       duration_ms=tech_log.ms_since(started),
                       level=logging.WARNING if page.error else logging.INFO)
    return page


def _recognize_page(image: np.ndarray, config: PipelineConfig) -> IndraPage:
    root = Path(__file__).resolve().parents[2]
    site_dir = root / "vendor" / "indra-site"
    if site_dir.is_dir():
        python = Path(sys.executable)
    else:
        python = find_python(config)
    if python is None:
        tech_log.ocr_event("ocr.indra.no_python", level=logging.ERROR, site_dir_exists=site_dir.is_dir())
        return _error("Indra OCR غير مثبت أو مسار Python غير مضبوط.")
    if image is None or image.size == 0:
        tech_log.ocr_event("ocr.indra.bad_image", level=logging.ERROR, image_none=image is None)
        return _error("صورة Indra OCR فارغة أو غير صالحة.")

    worker = root / "tools" / "indra_ocr_worker.py"
    with tempfile.TemporaryDirectory(prefix="ocr-indra-") as temp_dir:
        input_path = Path(temp_dir) / "page.png"
        try:
            saved = cv2.imwrite(str(input_path), image)
        except (cv2.error, OSError) as exc:
            tech_log.ocr_event("ocr.indra.temp_write_failed", level=logging.ERROR, exc_info=True,
                               temp_dir=temp_dir)
            return _error(f"تعذر حفظ صورة Indra OCR المؤقتة: {exc}")
        if not saved:
            tech_log.ocr_event("ocr.indra.temp_write_failed", level=logging.ERROR, temp_dir=temp_dir,
                               saved=False)
            return _error("تعذر حفظ صورة Indra OCR المؤقتة.")
        env = dict(os.environ)
        # ويندوز: الـstdout الافتراضي cp1252 بيفشل مع الحروف العربية — نفرض UTF-8.
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        local_models = root / "vendor" / "indra-models"
        if not env.get("INDRA_OCR_MODEL_DIR") and local_models.is_dir():
            env["INDRA_OCR_MODEL_DIR"] = str(local_models)
        try:
            command = [str(python), str(worker)]
            if site_dir.is_dir():
                command.extend(["--site-dir", str(site_dir)])
            command.append(str(input_path))
            tech_log.ocr_event(
                "ocr.indra.spawn", python=str(python), python_exists=python.is_file(),
                worker=str(worker), site_dir=str(site_dir) if site_dir.is_dir() else None,
                model_dir=env.get("INDRA_OCR_MODEL_DIR"), timeout_s=config.indra_timeout,
                image_shape="x".join(str(v) for v in image.shape), image_dtype=str(image.dtype),
                image_bytes=input_path.stat().st_size)
            spawned = time.perf_counter()
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=config.indra_timeout,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            tech_log.ocr_event("ocr.indra.timeout", level=logging.ERROR, timeout_s=config.indra_timeout,
                               duration_ms=tech_log.ms_since(spawned))
            partial = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else exc.stderr
            _log_stderr(partial, "timeout")
            return _error("انتهت مهلة Indra OCR.")
        except OSError as exc:
            tech_log.ocr_event("ocr.indra.spawn_failed", level=logging.ERROR, exc_info=True,
                               errno=exc.errno, python=str(python))
            return _error(f"تعذر تشغيل Indra OCR: {exc}")
        tech_log.ocr_event(
            "ocr.indra.finished", returncode=completed.returncode,
            duration_ms=tech_log.ms_since(spawned), stdout_chars=len(completed.stdout or ""),
            stderr_chars=len(completed.stderr or ""),
            level=logging.INFO if completed.returncode == 0 else logging.ERROR)
        # stderr فيه مراحل العامل (استيراد/تحميل النموذج/القراءة) حتى لو نجح.
        _log_stderr(completed.stderr, "worker", limit=25 if completed.returncode else 8,
                    level=logging.WARNING if completed.returncode else logging.INFO)
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
            tech_log.ocr_event("ocr.indra.bad_json", level=logging.ERROR, exc_info=True,
                               stdout_head=(completed.stdout or "")[:200],
                               stdout_tail=(completed.stdout or "")[-100:])
            return _error(f"نتيجة Indra OCR غير صالحة: {exc}")

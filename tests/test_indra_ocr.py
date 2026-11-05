import json
import os
import sys
from types import SimpleNamespace

import numpy as np

from backend.afraad_ocr_pipeline import indra_engine, pipeline
from backend.afraad_ocr_pipeline.config import PipelineConfig
from backend.afraad_ocr_pipeline.indra_engine import IndraLine, IndraPage
from backend.afraad_ocr_pipeline.models import Cell, GridResult, OCRResult
from tools import indra_ocr_worker


def _grid(ok=True, cells=None):
    image = np.full((80, 220, 3), 255, dtype=np.uint8)
    cells = cells if cells is not None else [Cell(0, 0, 10, 10, 100, 60, "morning")]
    return GridResult(ok, .9 if ok else .1, "morphology+projection", 220, 80,
                      cells=cells, processed_image=image)


def test_line_centres_are_assigned_and_joined_top_to_bottom():
    cells = [Cell(0, 0, 0, 0, 100, 100, "morning"),
             Cell(0, 1, 100, 0, 200, 100, "evening")]
    lines = [IndraLine((10, 50, 50, 70), "الثاني", .8),
             IndraLine((120, 10, 150, 30), "يمين", .9),
             IndraLine((10, 10, 50, 30), "الأول", .95)]

    assigned = pipeline._assign_indra_lines(lines, cells)

    assert [line.text for line in assigned[(0, 0)]] == ["الأول", "الثاني"]
    assert [line.text for line in assigned[(0, 1)]] == ["يمين"]


def test_indra_has_priority_and_blank_suppresses_weak_tesseract(monkeypatch):
    cells = [Cell(0, 0, 10, 10, 100, 60, "morning"),
             Cell(0, 1, 110, 10, 200, 60, "evening")]
    monkeypatch.setattr(pipeline, "detect_grid", lambda image, config: _grid(cells=cells))
    monkeypatch.setattr(pipeline, "indra_recognize_page", lambda image, config: IndraPage(
        [IndraLine((20, 20, 80, 40), "محمد نصار", .974)]
    ))
    calls = []

    def tess(image, config, multiline=False):
        calls.append(image.shape)
        return OCRResult("نوش", 40, "tesseract")

    monkeypatch.setattr(pipeline, "tess_recognize", tess)
    config = PipelineConfig(use_paddle_fallback=False)

    result = pipeline.TableOCRPipeline(config).run(np.zeros((80, 220, 3), np.uint8))

    assert len(calls) == 1
    assert result.cells[0]["engine"] == "indra"
    assert result.cells[0]["text"] == "محمد نصار"
    assert result.cells[0]["confidence"] == 97.4
    assert result.cells[1]["engine"] == "indra" and result.cells[1]["text"] == ""
    assert any(item["engine"] == "tesseract" and item["text"] == "نوش"
               for item in result.cells[1]["alternatives"])


def test_unavailable_indra_uses_tesseract_and_adds_warning(monkeypatch):
    monkeypatch.setattr(pipeline, "detect_grid", lambda image, config: _grid())
    monkeypatch.setattr(pipeline, "indra_recognize_page",
                        lambda image, config: IndraPage(error="Indra OCR غير مثبت."))
    monkeypatch.setattr(pipeline, "tess_recognize",
                        lambda image, config, multiline=False: OCRResult("بديل", 45, "tesseract"))
    config = PipelineConfig(use_paddle_fallback=False)

    result = pipeline.TableOCRPipeline(config).run(np.zeros((80, 220, 3), np.uint8))

    assert result.cells[0]["text"] == "بديل"
    assert result.cells[0]["engine"] == "tesseract"
    assert any("Indra OCR غير متاح" in warning for warning in result.warnings)


def test_raw_fallback_prefers_indra_page_text(monkeypatch):
    monkeypatch.setattr(pipeline, "detect_grid", lambda image, config: _grid(ok=False, cells=[]))
    monkeypatch.setattr(pipeline, "indra_recognize_page", lambda image, config: IndraPage([
        IndraLine((0, 0, 20, 10), "سطر أول", .9),
        IndraLine((0, 20, 20, 30), "سطر ثاني", .8),
    ]))
    monkeypatch.setattr(pipeline, "recognize_raw",
                        lambda image, config: (_ for _ in ()).throw(AssertionError("Tesseract ran")))

    result = pipeline.TableOCRPipeline(PipelineConfig()).run(np.zeros((80, 220, 3), np.uint8))

    assert result.mode == "raw-fallback"
    assert result.raw_ocr.engine == "indra"
    assert result.raw_ocr.text == "سطر أول\nسطر ثاني"
    assert result.raw_ocr.confidence == 85


def test_indra_ocr_zero_disables_engine(monkeypatch):
    monkeypatch.setenv("INDRA_OCR", "0")
    config = PipelineConfig.from_env()
    assert config.use_indra is False

    monkeypatch.setattr(pipeline, "detect_grid", lambda image, current: _grid())
    monkeypatch.setattr(pipeline, "indra_recognize_page",
                        lambda image, current: (_ for _ in ()).throw(AssertionError("Indra ran")))
    monkeypatch.setattr(pipeline, "tess_recognize",
                        lambda image, current, multiline=False: OCRResult("بديل", 50, "tesseract"))
    config.use_paddle_fallback = False
    result = pipeline.TableOCRPipeline(config).run(np.zeros((80, 220, 3), np.uint8))
    assert result.cells[0]["engine"] == "tesseract"


def test_indra_engine_reads_worker_json_and_passes_model_dir(tmp_path, monkeypatch):
    fake_python = tmp_path / "python"
    fake_python.write_text("", encoding="utf-8")
    monkeypatch.setattr(indra_engine, "find_python", lambda config: fake_python)
    monkeypatch.setenv("INDRA_OCR_MODEL_DIR", str(tmp_path / "models"))
    seen = {}

    def run(command, **kwargs):
        seen.update(kwargs)
        payload = {"lines": [{"box": [1, 2, 3, 4], "text": "اسم", "conf": .91}],
                   "rotation": 0, "skew": .2, "ms": 300}
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(indra_engine.subprocess, "run", run)
    result = indra_engine.recognize_page(np.zeros((10, 10), np.uint8), PipelineConfig())

    assert result.lines[0].text == "اسم"
    assert result.lines[0].box == (1.0, 2.0, 3.0, 4.0)
    assert seen["env"]["INDRA_OCR_MODEL_DIR"] == str(tmp_path / "models")
    assert seen["timeout"] == 60


def test_indra_engine_passes_project_site_to_worker(tmp_path, monkeypatch):
    fake_module = tmp_path / "backend" / "afraad_ocr_pipeline" / "indra_engine.py"
    fake_module.parent.mkdir(parents=True)
    fake_module.write_text("", encoding="ascii")
    site = tmp_path / "vendor" / "indra-site"
    site.mkdir(parents=True)
    seen = {}

    def run(command, **kwargs):
        seen["command"] = command
        return SimpleNamespace(returncode=0, stdout='{"lines": []}', stderr="")

    monkeypatch.setattr(indra_engine, "__file__", str(fake_module))
    monkeypatch.setattr(indra_engine.subprocess, "run", run)
    indra_engine.recognize_page(np.zeros((10, 10), np.uint8), PipelineConfig())

    command = seen["command"]
    assert command[0] == sys.executable
    assert command[2:4] == ["--site-dir", str(site)]


def test_worker_inserts_site_before_importing_indra(tmp_path, monkeypatch):
    monkeypatch.setenv("INDRA_OCR_MODEL_DIR", str(tmp_path))
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    loaded = []
    fake_indra = SimpleNamespace(load=lambda threads: loaded.append(threads) or object())
    monkeypatch.setitem(sys.modules, "indra_ocr", fake_indra)
    monkeypatch.setitem(sys.modules, "cv2", SimpleNamespace())

    assert indra_ocr_worker.main(["--site-dir", str(tmp_path), "--check"]) == 0

    assert sys.path[0] == str(tmp_path)
    assert loaded == [4]
    sys.path.pop(0)


def test_worker_uses_project_models_and_stays_offline_when_unconfigured(tmp_path, monkeypatch):
    models = tmp_path / "vendor" / "indra-models"
    models.mkdir(parents=True)
    (models / "det.onnx").write_bytes(b"x")
    monkeypatch.setattr(indra_ocr_worker, "__file__", str(tmp_path / "tools" / "indra_ocr_worker.py"))
    monkeypatch.delenv("INDRA_OCR_MODEL_DIR", raising=False)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)

    described = indra_ocr_worker._resolve_model_dir()

    assert os.environ["INDRA_OCR_MODEL_DIR"] == str(models)
    assert os.environ["HF_HUB_OFFLINE"] == "1"
    assert "project default" in described and "offline mode" in described
    monkeypatch.delenv("INDRA_OCR_MODEL_DIR")
    monkeypatch.delenv("HF_HUB_OFFLINE")


def test_worker_selftest_runs_a_real_inference(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("INDRA_OCR_MODEL_DIR", str(tmp_path))
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    seen = []
    page = SimpleNamespace(lines=[SimpleNamespace(text="TEST")])
    converter = SimpleNamespace(ocr=lambda image, turn: seen.append(image.shape) or page)
    monkeypatch.setitem(sys.modules, "indra_ocr", SimpleNamespace(load=lambda threads: converter))

    assert indra_ocr_worker.main(["--site-dir", str(tmp_path), "--selftest"]) == 0
    sys.path.pop(0)

    assert seen == [(240, 900)]
    assert "self-test inference ok: 1 lines" in capsys.readouterr().err


def test_engine_explains_a_silent_native_crash(tmp_path, monkeypatch):
    fake_python = tmp_path / "python"
    fake_python.write_text("", encoding="utf-8")
    monkeypatch.setattr(indra_engine, "find_python", lambda config: fake_python)
    stderr = "[indra-worker +4.66s] import indra_ocr ok from vendor/indra-site/indra_ocr/__init__.py version=1.1.2"

    def run(command, **kwargs):
        return SimpleNamespace(returncode=0xC000001D, stdout="", stderr=stderr)

    monkeypatch.setattr(indra_engine.subprocess, "run", run)
    result = indra_engine.recognize_page(np.zeros((10, 10), np.uint8), PipelineConfig())

    assert "0xC000001D" in result.error and "AVX" in result.error
    assert "import indra_ocr ok" in result.error  # the last worker line is still shown

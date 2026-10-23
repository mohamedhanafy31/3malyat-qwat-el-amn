import os

from backend.afraad_ocr_pipeline import tesseract_engine


class _PytesseractModule:
    class pytesseract:
        tesseract_cmd = ""


def test_configure_uses_project_local_arabic_language_data(tmp_path, monkeypatch):
    tessdata = tmp_path / "tessdata"
    tessdata.mkdir()
    (tessdata / "ara.traineddata").write_bytes(b"model")
    executable = tmp_path / "tesseract.exe"
    executable.write_bytes(b"exe")

    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
    monkeypatch.setenv("TESSERACT_CMD", str(executable))
    monkeypatch.setattr(tesseract_engine, "PROJECT_TESSDATA", tessdata)

    module = _PytesseractModule()
    tesseract_engine._configure(module)

    assert os.environ["TESSDATA_PREFIX"] == str(tessdata)
    assert module.pytesseract.tesseract_cmd == str(executable)

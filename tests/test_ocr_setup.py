from pathlib import Path
from types import SimpleNamespace

from tools import ocr_setup


def test_explicit_tesseract_is_honoured_and_project_arabic_data_is_used(tmp_path):
    executable = tmp_path / "custom" / "tesseract.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"exe")
    model = tmp_path / "tools" / "offline_installers" / "ara.traineddata"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"arabic")
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs["env"]))
        return SimpleNamespace(returncode=0, stdout="List of available languages:\nara\n")

    info = ocr_setup.status(tmp_path, {"TESSERACT_CMD": str(executable)},
                            which=lambda _name: None, run=run)

    assert info["ready"] is True
    assert Path(info["path"]) == executable
    assert calls[0][1]["TESSDATA_PREFIX"].endswith("tools/tesseract/tessdata")


def test_missing_ocr_is_optional_and_descriptive(tmp_path):
    info = ocr_setup.status(tmp_path, {}, which=lambda _name: None)
    assert info["ready"] is False
    assert "not found" in ocr_setup.describe(info)


def test_indra_offline_setup_uses_isolated_env_wheels_and_local_models(tmp_path):
    (tmp_path / "requirements-indra-ocr.txt").write_text("indra-ocr==1.1.2\n")
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    info = ocr_setup.setup_indra(
        root=tmp_path,
        python="host-python",
        offline=True,
        run=run,
    )

    assert info["ready"] is True
    assert calls[0][0] == ["host-python", "-m", "venv", str(tmp_path / ".venv-indra")]
    assert "--no-index" in calls[1][0]
    assert str(tmp_path / "wheels") in calls[1][0]
    assert calls[2][1]["env"]["INDRA_OCR_MODEL_DIR"] == str(tmp_path / "vendor/indra-models")
    assert calls[2][1]["env"]["HF_HUB_OFFLINE"] == "1"

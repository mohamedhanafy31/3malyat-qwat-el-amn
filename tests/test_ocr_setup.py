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


def test_indra_offline_setup_uses_target_wheels_and_local_models(tmp_path):
    (tmp_path / "requirements-indra-ocr.txt").write_text("indra-ocr==1.1.2\n")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "indra_ocr_worker.py").write_text("", encoding="ascii")
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
    install = calls[0][0]
    assert install[:4] == ["host-python", "-m", "pip", "install"]
    assert "--ignore-installed" in install
    assert "--no-index" in install
    assert str(tmp_path / "wheels/indra") in install
    assert install[install.index("--target") + 1] == str(tmp_path / "vendor/indra-site")
    assert calls[1][0] == [
        "host-python", str(tmp_path / "tools/indra_ocr_worker.py"),
        "--site-dir", str(tmp_path / "vendor/indra-site"), "--check",
    ]
    assert calls[1][1]["env"]["INDRA_OCR_MODEL_DIR"] == str(tmp_path / "vendor/indra-models")
    assert calls[1][1]["env"]["HF_HUB_OFFLINE"] == "1"


def test_status_reports_indra_readiness(tmp_path):
    site = tmp_path / "vendor" / "indra-site" / "indra_ocr"
    site.mkdir(parents=True)
    models = tmp_path / "vendor" / "indra-models"
    models.mkdir()
    for name in ocr_setup.INDRA_MODEL_FILES:
        (models / name).write_bytes(b"model")

    info = ocr_setup.indra_status(tmp_path, python="runtime-python")

    assert info["ready"] is True
    assert info["python"] == "runtime-python"
    assert "vendor/indra-site" in ocr_setup.describe_indra(info)


def test_exit_codes_are_explained_in_plain_english():
    assert "AVX" in ocr_setup.describe_exit_code(0xC000001D)
    assert "AVX" in ocr_setup.describe_exit_code(-1073741795)  # the same code as cmd shows it
    assert "access violation" in ocr_setup.describe_exit_code(0xC0000005)
    assert "SIGILL" in ocr_setup.describe_exit_code(-4)
    assert "Python error" in ocr_setup.describe_exit_code(1)
    assert ocr_setup.describe_exit_code(0) == "success"


def _indra_tree(tmp_path, models=True, wheel=True):
    (tmp_path / "requirements-indra-ocr.txt").write_text("indra-ocr==1.1.2\n")
    if wheel:
        (tmp_path / "wheels" / "indra").mkdir(parents=True)
        (tmp_path / "wheels" / "indra" / "indra_ocr-1.1.2-py3-none-any.whl").write_bytes(b"w")
    if models:
        folder = tmp_path / "vendor" / "indra-models"
        folder.mkdir(parents=True)
        for name in ocr_setup.INDRA_MODEL_FILES:
            (folder / name).write_bytes(b"m")


def test_indra_preflight_names_every_missing_file(tmp_path, capsys):
    _indra_tree(tmp_path)
    (tmp_path / "vendor" / "indra-models" / "rec_rtl.onnx").unlink()
    (tmp_path / "vendor" / "indra-models" / "script.onnx").write_bytes(b"")

    problems = ocr_setup.indra_preflight(tmp_path)

    assert problems == ["model file rec_rtl.onnx is missing", "model file script.onnx is empty"]
    output = capsys.readouterr().out
    assert "model rec_rtl.onnx: MISSING" in output
    assert "model script.onnx: EMPTY" in output
    assert ocr_setup.indra_preflight(tmp_path / "nowhere")  # nothing installed at all


def test_indra_check_runs_load_then_inference_and_reports_a_crash(tmp_path, capsys):
    _indra_tree(tmp_path, wheel=False)
    (tmp_path / "vendor" / "indra-site" / "indra_ocr").mkdir(parents=True)
    calls = []

    def run(command, **kwargs):
        calls.append(command[-1])
        return SimpleNamespace(returncode=0xC000001D if command[-1] == "--selftest" else 0)

    ready, reason = ocr_setup.check_indra(tmp_path, python="py", run=run)

    assert calls == ["--check", "--selftest"]
    assert ready is False
    assert "inference failed" in reason and "AVX" in reason


def test_indra_check_reports_a_missing_install_without_running_anything(tmp_path):
    _indra_tree(tmp_path, wheel=False)

    ready, reason = ocr_setup.check_indra(tmp_path, python="py", run=lambda *a, **k: 1 / 0)

    assert ready is False
    assert "vendor/indra-site is not installed" in reason

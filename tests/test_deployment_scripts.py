import ssl
import subprocess
import json
from pathlib import Path

from tools import offline_env, prepare_offline_bundle


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    "PREPARE_ONLINE.bat",
    "SETUP_OFFLINE.bat",
    "START_SYSTEM.bat",
    "BACKUPS.bat",
    "run_windows.bat",
    "STOP_SYSTEM.bat",
    "SETUP_PHONE_ACCESS.bat",
    "tools/deploy_console.bat",
)
GUI_LAUNCHERS = ("OPEN_SYSTEM.vbs", "CLOSE_SYSTEM.vbs")


def test_deployment_batch_files_are_ascii_only():
    for name in SCRIPTS:
        raw = (ROOT / name).read_bytes()
        raw.decode("ascii")


def test_deployment_batch_files_use_windows_line_endings():
    for name in SCRIPTS:
        raw = (ROOT / name).read_bytes()
        assert b"\n" not in raw.replace(b"\r\n", b"")


def test_gui_launchers_are_ascii_windows_scripts():
    for name in GUI_LAUNCHERS:
        raw = (ROOT / name).read_bytes()
        raw.decode("ascii")
        assert b"\n" not in raw.replace(b"\r\n", b"")


def test_gui_launchers_hide_cmd_and_surface_failures():
    start = (ROOT / "OPEN_SYSTEM.vbs").read_text(encoding="ascii")
    stop = (ROOT / "CLOSE_SYSTEM.vbs").read_text(encoding="ascii")
    assert 'shell.Run(Quoted(batchFile), 0, True)' in start
    assert 'shell.Run(Quoted(batchFile), 0, True)' in stop
    assert 'PERSONNEL_NO_PAUSE' in start
    assert 'PERSONNEL_NO_PAUSE' in stop
    assert 'START_SYSTEM.bat' in start and 'start-system.log' in start
    assert 'STOP_SYSTEM.bat' in stop and 'stop-system.log' in stop
    assert 'notepad.exe' in start and 'notepad.exe' in stop


def test_deployment_scripts_are_relocatable_and_logged():
    prepare = (ROOT / "PREPARE_ONLINE.bat").read_text(encoding="ascii")
    start = (ROOT / "START_SYSTEM.bat").read_text(encoding="ascii")
    setup = (ROOT / "SETUP_OFFLINE.bat").read_text(encoding="ascii")
    assert 'set "ROOT=%~dp0"' in start
    assert 'cd /d "%ROOT%"' in start
    assert '"%ROOT%serve.py"' in start
    assert "logs\\server-console.log" in start
    assert 'call "%ROOT%SETUP_OFFLINE.bat"' in start
    assert "First launch detected" in start
    assert "AUTO_SETUP_ATTEMPTED" in start
    assert "choose-port" in start
    assert "logs\\server.port" in start
    assert "saved-port" in (ROOT / "STOP_SYSTEM.bat").read_text(encoding="ascii")
    assert "--bind-first" in (ROOT / "STOP_SYSTEM.bat").read_text(encoding="ascii")
    assert "--trace" in start
    assert "LSS 30" in start
    assert start.index('if "!READY_RESULT!"=="12" goto port_failed') > start.index("LSS 30")
    launch = start.index('start "" /b "%PYW%"')
    step4 = start.index('[4/5] Starting production server')
    assert 'deploy_check.py" ready' not in start[step4:launch]
    assert '"20" set "SERVER_STATE=ready"' in start
    assert '"21" set "SERVER_STATE=unavailable"' in start
    assert start.index("goto port_selection_failed") < start.index("set /p PORT")
    assert "PERSONNEL_SETUP_FROM_START" in setup
    assert 'call "%ROOT%SETUP_OFFLINE.bat"' in prepare
    assert "PERSONNEL_SETUP_FROM_PREPARE" in prepare
    assert "preflight --mode prepare" in prepare
    assert "host-python" in prepare

    assert "if not defined PERSONNEL_NO_PAUSE" in start
    assert "if not defined PERSONNEL_NO_PAUSE if not defined PERSONNEL_SETUP_FROM_START if not defined PERSONNEL_SETUP_FROM_PREPARE" in setup
    for script in (prepare, start, setup):
        assert "Press any key to close this window" in script
        assert 'info "Details: %DEPLOY_LOG%"' in script

    for name in SCRIPTS:
        text = (ROOT / name).read_text(encoding="ascii")
        assert "deploy_console.bat" in text or name in {"run_windows.bat", "tools/deploy_console.bat"}

    helper = (ROOT / "tools/deploy_console.bat").read_text(encoding="ascii")
    assert "%date% %time%" in helper
    assert "WT_SESSION" in helper


def test_offline_dependency_and_ocr_contract_is_complete():
    prepare = (ROOT / "PREPARE_ONLINE.bat").read_text(encoding="ascii")
    setup = (ROOT / "SETUP_OFFLINE.bat").read_text(encoding="ascii")
    start = (ROOT / "START_SYSTEM.bat").read_text(encoding="ascii")

    assert "prepare_offline_bundle.py" in prepare
    assert "verify_offline_assets.py" in setup
    assert "openpyxl" in offline_env.REQUIRED
    assert "openpyxl" in setup
    assert "openpyxl" in start
    assert "ocr_setup.py" in setup
    assert "ocr_setup.py" in start
    assert 'if exist "%ROOT%tools\\tesseract\\tessdata\\ara.traineddata"' in start
    assert 'set "TESSDATA_PREFIX=%ROOT%tools\\tesseract\\tessdata"' in start
    assert "optional" in setup.lower()
    assert "setup-indra --offline" in setup
    assert "wheels\\indra\\indra_ocr-*.whl" in setup
    assert "vendor\\indra-models\\det.onnx" in setup
    assert "photo import falls back to Tesseract" in setup
    assert setup.index("setup-indra --offline") < setup.index('[6/8] Verifying dependencies')
    indra_failure = setup.index(":indra_failed")
    assert "goto show_failure" not in setup[indra_failure:setup.index(":verify", indra_failure)]


def test_startup_uses_application_readiness_marker_not_root_http():
    start = (ROOT / "START_SYSTEM.bat").read_text(encoding="ascii")
    stop = (ROOT / "STOP_SYSTEM.bat").read_text(encoding="ascii")
    for text in (start, stop):
        assert "deploy_check.py\" ready" in text
        assert "urlopen('%URL%'" not in text
    assert "Nothing was killed" in stop


def test_supported_release_does_not_include_background_autostart():
    names = {path.relative_to(ROOT).as_posix() for path in prepare_offline_bundle.release_files()}
    assert "OPEN_SYSTEM.vbs" in names
    assert "CLOSE_SYSTEM.vbs" in names
    assert "INSTALL_AUTOSTART.bat" not in names
    assert "tools/autostart.py" not in names
    assert "retire-autostart" in (ROOT / "PREPARE_ONLINE.bat").read_text(encoding="ascii")


def test_offline_release_excludes_secrets_and_large_archives():
    relative = {path.relative_to(ROOT).as_posix() for path in prepare_offline_bundle.release_files()}

    assert "data/core.json" in relative
    assert any(path.startswith("data/days/") for path in relative)
    assert "data/users.json" not in relative
    assert "data/secret_key" not in relative
    assert not any(path.startswith("data/source_docs/") for path in relative)
    assert not any(path.startswith("data/daily_files/") for path in relative)
    assert not any(path.startswith("data/import/") for path in relative)


def test_windows_download_falls_back_to_verified_system_curl(tmp_path, monkeypatch):
    target = tmp_path / "asset.bin"
    calls = []

    def fail_python_https(*args, **kwargs):
        raise ssl.SSLCertVerificationError("unable to get local issuer certificate")

    def find_windows_tool(name):
        return r"C:\Windows\System32\curl.exe" if name == "curl.exe" else None

    def run_curl(command, **kwargs):
        calls.append(command)
        output = Path(command[command.index("--output") + 1])
        output.write_bytes(b"verified-download")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(prepare_offline_bundle, "IS_WINDOWS", True)
    monkeypatch.setattr(prepare_offline_bundle.urllib.request, "urlopen", fail_python_https)
    monkeypatch.setattr(prepare_offline_bundle.shutil, "which", find_windows_tool)
    monkeypatch.setattr(prepare_offline_bundle.subprocess, "run", run_curl)

    prepare_offline_bundle.download("https://example.test/asset.bin", target)

    assert target.read_bytes() == b"verified-download"
    assert len(calls) == 1
    assert "--fail" in calls[0]
    assert "--insecure" not in calls[0]
    assert "-k" not in calls[0]


def test_asset_directory_swap_can_roll_back(tmp_path):
    target = tmp_path / "runtime"
    source = tmp_path / "new-runtime"
    target.mkdir()
    source.mkdir()
    (target / "version.txt").write_text("old", encoding="ascii")
    (source / "version.txt").write_text("new", encoding="ascii")

    kept = prepare_offline_bundle.activate_directory(source, target)
    assert (target / "version.txt").read_text(encoding="ascii") == "new"
    prepare_offline_bundle.rollback_directories([(target, kept)])
    assert (target / "version.txt").read_text(encoding="ascii") == "old"


def test_indra_model_snapshot_uses_pinned_api_and_exact_default_files(tmp_path):
    calls = []

    def download(url, target):
        calls.append((url, target))
        if url == prepare_offline_bundle.indra_blobs_url():
            target.write_text(json.dumps({"siblings": [
                {"rfilename": name}
                for name in (*prepare_offline_bundle.INDRA_MODEL_FILES, "mathcls.onnx")
            ]}), encoding="utf-8")
        else:
            target.write_bytes(b"model")

    prepare_offline_bundle.prepare_indra_models(tmp_path, downloader=download)

    assert calls[0][0] == (
        "https://huggingface.co/api/models/datalab-to/indra-ocr/revision/v1.1.0?blobs=true"
    )
    assert prepare_offline_bundle.indra_api_url().endswith("/revision/v1.1.0")
    downloaded = {target.name for _url, target in calls[1:]}
    assert downloaded == set(prepare_offline_bundle.INDRA_MODEL_FILES)
    assert all("/resolve/v1.1.0/" in url for url, _target in calls[1:])
    assert "mathcls.onnx" not in downloaded


def _snapshot_downloader(tmp_path, payloads, served):
    """Fake model host: `payloads` maps file name -> bytes it publishes (size + SHA-256);
    `served` maps file name -> list of byte strings returned on successive downloads."""
    import hashlib
    calls = []

    def download(url, target):
        calls.append(url)
        if url == prepare_offline_bundle.indra_blobs_url():
            target.write_text(json.dumps({"siblings": [
                {"rfilename": name, "size": len(data),
                 "lfs": {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}}
                for name, data in payloads.items()
            ]}), encoding="utf-8")
            return
        name = url.rsplit("/", 1)[1]
        target.write_bytes(served[name].pop(0))

    return download, calls


def test_indra_models_are_checked_against_published_size_and_sha256(tmp_path):
    names = prepare_offline_bundle.INDRA_MODEL_FILES
    payloads = {name: f"good-{name}".encode() for name in names}
    # det.onnx arrives truncated once, then correct: it must be fetched again.
    served = {name: [data] for name, data in payloads.items()}
    served["det.onnx"] = [b"good-de", payloads["det.onnx"]]
    download, calls = _snapshot_downloader(tmp_path, payloads, served)

    prepare_offline_bundle.prepare_indra_models(tmp_path, downloader=download)

    assert sum(url.endswith("/det.onnx") for url in calls) == 2
    assert (tmp_path / "indra-models" / "det.onnx").read_bytes() == payloads["det.onnx"]


def test_indra_model_that_never_matches_fails_with_the_file_name(tmp_path):
    import pytest
    names = prepare_offline_bundle.INDRA_MODEL_FILES
    payloads = {name: f"good-{name}".encode() for name in names}
    served = {name: [data] for name, data in payloads.items()}
    # Same size, different bytes: only the SHA-256 can catch this.
    served["rec.onnx"] = [b"x" * len(payloads["rec.onnx"])] * prepare_offline_bundle.MODEL_FETCH_ATTEMPTS
    download, _calls = _snapshot_downloader(tmp_path, payloads, served)

    with pytest.raises(RuntimeError, match="rec.onnx failed verification"):
        prepare_offline_bundle.prepare_indra_models(tmp_path, downloader=download)


def test_connectivity_check_reports_unreachable_hosts(monkeypatch, capsys):
    def resolve(host, *args, **kwargs):
        if host == "huggingface.co":
            raise OSError("getaddrinfo failed")
        return [(0, 0, 0, "", ("203.0.113.9", 443))]

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(prepare_offline_bundle.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(prepare_offline_bundle.socket, "create_connection",
                        lambda *args, **kwargs: Connection())
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        monkeypatch.delenv(name, raising=False)

    failed = prepare_offline_bundle.check_connectivity()

    output = capsys.readouterr().out
    assert failed == 1
    assert "huggingface.co (Indra OCR models): DNS lookup failed - getaddrinfo failed" in output
    assert "www.python.org (embedded Python runtime): reachable" in output


def test_prepare_reports_the_failing_stage_as_an_x_line(tmp_path, monkeypatch, capsys):
    log = tmp_path / "prepare.log"
    monkeypatch.setenv("DEPLOY_LOG", str(log))
    monkeypatch.setattr(prepare_offline_bundle, "ROOT", tmp_path)
    monkeypatch.setattr(prepare_offline_bundle, "check_connectivity", lambda: 0)

    def broken(work):
        raise RuntimeError("The Indra model API returned invalid metadata")

    monkeypatch.setattr(prepare_offline_bundle, "prepare_runtime", lambda work: None)
    monkeypatch.setattr(prepare_offline_bundle, "prepare_wheels", lambda work: None)
    monkeypatch.setattr(prepare_offline_bundle, "prepare_ocr", lambda work: None)
    monkeypatch.setattr(prepare_offline_bundle, "prepare_indra_models", broken)

    assert prepare_offline_bundle.main([]) == 1

    logged = log.read_text(encoding="utf-8")
    assert "[X] Stage 5/6 (Indra OCR models" in logged
    assert "invalid metadata" in logged
    assert "[X] Stage 5/6" in capsys.readouterr().out
    assert list(tmp_path.glob(".offline-build-*")) == []


def test_release_files_include_prepared_indra_models_and_site(tmp_path, monkeypatch):
    (tmp_path / "vendor" / "indra-models").mkdir(parents=True)
    (tmp_path / "vendor" / "indra-site" / "indra_ocr").mkdir(parents=True)
    (tmp_path / "vendor" / "indra-models" / "det.onnx").write_bytes(b"model")
    (tmp_path / "vendor" / "indra-site" / "indra_ocr" / "__init__.py").write_text("")
    monkeypatch.setattr(prepare_offline_bundle, "ROOT", tmp_path)

    names = {path.relative_to(tmp_path).as_posix()
             for path in prepare_offline_bundle.release_files()}

    assert "vendor/indra-models/det.onnx" in names
    assert "vendor/indra-site/indra_ocr/__init__.py" in names

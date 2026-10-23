from pathlib import Path

from tools import offline_env, prepare_offline_bundle


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    "PREPARE_ONLINE.bat",
    "SETUP_OFFLINE.bat",
    "START_SYSTEM.bat",
    "BACKUPS.bat",
    "run_windows.bat",
    "INSTALL_AUTOSTART.bat",
    "STOP_SYSTEM.bat",
    "SETUP_PHONE_ACCESS.bat",
    "tools/deploy_console.bat",
)


def test_deployment_batch_files_are_ascii_only():
    for name in SCRIPTS:
        raw = (ROOT / name).read_bytes()
        raw.decode("ascii")


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
    assert "PERSONNEL_SETUP_FROM_START" in setup
    assert 'call "%ROOT%SETUP_OFFLINE.bat"' in prepare
    assert "PERSONNEL_SETUP_FROM_PREPARE" in prepare
    assert "--archive" not in prepare

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
    assert "ara.traineddata" in setup
    assert "TESSERACT_CMD" in start


def test_offline_release_excludes_secrets_and_large_archives():
    relative = {path.relative_to(ROOT).as_posix() for path in prepare_offline_bundle.release_files()}

    assert "data/core.json" in relative
    assert any(path.startswith("data/days/") for path in relative)
    assert "data/users.json" not in relative
    assert "data/secret_key" not in relative
    assert not any(path.startswith("data/source_docs/") for path in relative)
    assert not any(path.startswith("data/daily_files/") for path in relative)
    assert not any(path.startswith("data/import/") for path in relative)

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    "PREPARE_ONLINE.bat",
    "SETUP_OFFLINE.bat",
    "START_SYSTEM.bat",
    "BACKUPS.bat",
    "run_windows.bat",
    "tools/deploy_console.bat",
)


def test_deployment_batch_files_are_ascii_only():
    for name in SCRIPTS:
        raw = (ROOT / name).read_bytes()
        raw.decode("ascii")


def test_deployment_scripts_are_relocatable_and_logged():
    start = (ROOT / "START_SYSTEM.bat").read_text(encoding="ascii")
    assert 'set "ROOT=%~dp0"' in start
    assert 'cd /d "%ROOT%"' in start
    assert '"%ROOT%serve.py"' in start

    for name in SCRIPTS:
        text = (ROOT / name).read_text(encoding="ascii")
        assert "deploy_console.bat" in text or name in {"run_windows.bat", "tools/deploy_console.bat"}

    helper = (ROOT / "tools/deploy_console.bat").read_text(encoding="ascii")
    assert "%date% %time%" in helper
    assert "WT_SESSION" in helper

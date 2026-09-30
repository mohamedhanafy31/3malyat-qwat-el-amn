import os
import subprocess
import sys
from pathlib import Path


def test_absolute_environment_override_controls_derived_paths(tmp_path):
    target = tmp_path / "relocated"
    env = {**os.environ, "PERSONNEL_DATA_DIR": str(target)}
    code = (
        "from backend import store, clock; from backend import service_catalog; "
        "from backend import changes; "
        "print(store.DATA_DIR); print(store.core_file()); print(store.days_dir()); "
        "print(service_catalog.images_dir()); print(store.backup_dir()); "
        "print(clock._marker_path()); print(changes._archive_path())"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).parent.parent,
                            env=env, text=True, capture_output=True, check=True)
    paths = [Path(line) for line in result.stdout.splitlines()]
    assert paths[0] == target
    assert paths[1] == target / "core.json"
    assert paths[2] == target / "days"
    assert paths[3] == target / "uploads" / "service_catalog"
    assert paths[4] == target.parent / "backups"
    assert paths[5] == target / ".clock_seen"
    assert paths[6] == target / "logs" / "change_log_archive.jsonl"


def test_relative_environment_override_is_rejected(tmp_path):
    env = {**os.environ, "PERSONNEL_DATA_DIR": "relative/data"}
    result = subprocess.run([sys.executable, "-c", "import backend.store"], cwd=tmp_path,
                            env={**env, "PYTHONPATH": str(Path(__file__).parent.parent)},
                            text=True, capture_output=True)
    assert result.returncode != 0
    assert "absolute path" in result.stderr

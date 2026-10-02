import os
from pathlib import Path

from tools import offline_env


def test_embedded_pth_includes_project_root_and_site_packages(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "python311._pth").write_text(
        "python311.zip\n.\n#import site\n", encoding="utf-8"
    )
    project = tmp_path / "Camp System"
    project.mkdir()
    monkeypatch.setattr(offline_env, "ROOT", project)
    monkeypatch.setattr(offline_env.sys, "prefix", str(runtime))

    assert offline_env._enable_site_packages() is True
    lines = (runtime / "python311._pth").read_text(encoding="utf-8").splitlines()
    root_entries = [line for line in lines if line not in {"python311.zip", ".", r"Lib\site-packages", "import site"}]
    assert len(root_entries) == 1
    assert (runtime / root_entries[0].replace("\\", os.sep)).resolve() == project.resolve()
    assert r"Lib\site-packages" in lines
    assert "import site" in lines

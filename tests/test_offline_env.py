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


def test_install_activates_target_in_current_process(tmp_path, monkeypatch):
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    package = wheels / "example-1.0-py3-none-any.whl"
    import zipfile
    with zipfile.ZipFile(package, "w") as bundle:
        bundle.writestr("offline_example/__init__.py", "READY = True\n")
    target = tmp_path / "site-packages"
    monkeypatch.setattr(offline_env, "WHEELS", wheels)
    monkeypatch.setattr(offline_env, "ROOT", tmp_path)
    monkeypatch.setattr(offline_env, "verify", lambda quiet=False: 0)

    assert offline_env.install(target=target, quiet=True) == 0
    assert str(target) in offline_env.sys.path


def test_failed_install_restores_packages_and_embedded_pth(tmp_path, monkeypatch):
    import zipfile

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    pth = runtime / "python311._pth"
    original_pth = b"python311.zip\n.\n#import site\n"
    pth.write_bytes(original_pth)
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    with zipfile.ZipFile(wheels / "example-1.0-py3-none-any.whl", "w") as bundle:
        bundle.writestr("new_package/__init__.py", "")
    target = runtime / "Lib" / "site-packages"
    target.mkdir(parents=True)
    (target / "old.txt").write_text("old", encoding="ascii")
    monkeypatch.setattr(offline_env, "WHEELS", wheels)
    monkeypatch.setattr(offline_env, "ROOT", tmp_path)
    monkeypatch.setattr(offline_env.sys, "prefix", str(runtime))
    monkeypatch.setattr(offline_env, "verify", lambda quiet=False: 1)

    assert offline_env.install(target=target, quiet=True) == 1
    assert (target / "old.txt").read_text(encoding="ascii") == "old"
    assert pth.read_bytes() == original_pth


def test_verify_accepts_auth_protection_on_fresh_install(monkeypatch):
    monkeypatch.setattr(offline_env, "_missing", lambda names: [])

    # The repository app has authentication enabled.  This exercises the real
    # login/protected-route contract instead of a mock that could drift.
    assert offline_env.verify(quiet=True) == 0


def test_wheel_extraction_rejects_path_traversal(tmp_path):
    import zipfile

    wheel = tmp_path / "bad.whl"
    with zipfile.ZipFile(wheel, "w") as bundle:
        bundle.writestr("../outside.txt", "bad")

    assert "outside" in offline_env._extract_wheel(wheel, tmp_path / "target")
    assert not (tmp_path / "outside.txt").exists()

import hashlib
from pathlib import Path

from tools import verify_offline_assets


def test_verify_offline_assets_accepts_valid_manifest(tmp_path, monkeypatch):
    assets = {
        "runtime/python.exe": b"python",
        "runtime/pythonw.exe": b"pythonw",
        "runtime/python311.dll": b"dll",
        "wheels/example.whl": b"wheel",
    }
    for relative, content in assets.items():
        asset = tmp_path / relative
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_bytes(content)
    manifest = tmp_path / "OFFLINE_ASSETS.sha256"
    manifest.write_text("".join(
        f"{hashlib.sha256(content).hexdigest()}  {relative}\n"
        for relative, content in assets.items()), encoding="ascii")
    monkeypatch.setattr(verify_offline_assets, "ROOT", tmp_path)
    monkeypatch.setattr(verify_offline_assets, "MANIFEST", manifest)

    assert verify_offline_assets.verify(quiet=True) == 0


def test_verify_offline_assets_rejects_changed_asset(tmp_path, monkeypatch):
    asset = tmp_path / "runtime" / "python.exe"
    asset.parent.mkdir()
    asset.write_bytes(b"changed")
    manifest = tmp_path / "OFFLINE_ASSETS.sha256"
    manifest.write_text(f"{'0' * 64}  runtime/python.exe\n", encoding="ascii")
    monkeypatch.setattr(verify_offline_assets, "ROOT", tmp_path)
    monkeypatch.setattr(verify_offline_assets, "MANIFEST", manifest)

    assert verify_offline_assets.verify(quiet=True) == 1


def test_manifest_rejects_traversal_and_unlisted_wheel(tmp_path, monkeypatch):
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    (wheels / "extra.whl").write_bytes(b"extra")
    manifest = tmp_path / "OFFLINE_ASSETS.sha256"
    manifest.write_text(f"{'0' * 64}  runtime/../escape.exe\n", encoding="ascii")
    monkeypatch.setattr(verify_offline_assets, "ROOT", tmp_path)
    monkeypatch.setattr(verify_offline_assets, "MANIFEST", manifest)

    assert verify_offline_assets.verify(quiet=True) == 1

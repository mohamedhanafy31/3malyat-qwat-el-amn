import hashlib
from pathlib import Path

from tools import verify_offline_assets


def test_verify_offline_assets_accepts_valid_manifest(tmp_path, monkeypatch):
    asset = tmp_path / "wheels" / "example.whl"
    asset.parent.mkdir()
    asset.write_bytes(b"wheel")
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    manifest = tmp_path / "OFFLINE_ASSETS.sha256"
    manifest.write_text(f"{digest}  wheels/example.whl\n", encoding="ascii")
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

#!/usr/bin/env python3
"""Write logs/deployment-manifest.txt with support facts available locally.

Contains no secrets and no account or personnel data: only versions, paths,
the asset-manifest hash, OCR status, and whether the data passed validation.
ASCII output so it reads the same in any editor and in cmd.exe.

    python tools/deploy_manifest.py [--mode offline]
"""
from __future__ import annotations

import argparse
import os
import platform
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TARGET_NAME = "deployment-manifest.txt"


def _git_dir(root):
    marker = Path(root) / ".git"
    if marker.is_dir():
        return marker
    if marker.is_file():                      # worktree / submodule pointer file
        text = marker.read_text(encoding="utf-8", errors="replace").strip()
        if text.startswith("gitdir:"):
            path = Path(text.split(":", 1)[1].strip())
            return path if path.is_absolute() else (Path(root) / path).resolve()
    return None


def discover_revision(root=None):
    """Application revision without running git: REVISION file, else .git files."""
    root = Path(root or ROOT)
    for name in ("REVISION", "VERSION"):
        path = root / name
        if path.is_file():
            value = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
            if value and value[0].strip():
                return value[0].strip()[:80]
    git = _git_dir(root)
    if git is None:
        return "unknown"
    try:
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref:"):
            return head[:40] or "unknown"
        ref = head.split(":", 1)[1].strip()
        # Worktrees keep refs in the common git dir.
        common = git
        pointer = git / "commondir"
        if pointer.is_file():
            common = (git / pointer.read_text(encoding="utf-8").strip()).resolve()
        for base in (git, common):
            ref_file = base / ref
            if ref_file.is_file():
                return ref_file.read_text(encoding="utf-8").strip()[:40]
        packed = common / "packed-refs"
        if packed.is_file():
            for line in packed.read_text(encoding="utf-8").splitlines():
                if line.endswith(" " + ref) and not line.startswith(("#", "^")):
                    return line.split(" ", 1)[0][:40]
        return f"unknown ({ref})"
    except OSError:
        return "unknown"


def _ascii(value):
    return str(value).encode("ascii", "backslashreplace").decode("ascii")


def collect(root=None, mode="offline", environ=None):
    from tools import ocr_setup, offline_env, verify_offline_assets

    root = Path(root or ROOT)
    env = os.environ if environ is None else environ
    runtime_python = root / "runtime" / "python.exe"
    try:
        embedded = runtime_python.exists() and Path(sys.executable).samefile(runtime_python)
    except OSError:
        embedded = False
    info, error = offline_env.validate_data()
    if error:
        data_status = "FAILED (" + _ascii(error.splitlines()[0]) + ")"
    elif info["status"] == "fresh":
        data_status = "ok (empty data folder; created on first use)"
    else:
        data_status = f"ok (schema {info['schema']}, {info['days']} day files)"
    asset_hash = ""
    try:
        manifest = root / "OFFLINE_ASSETS.sha256"
        if manifest.is_file():
            asset_hash = verify_offline_assets.sha256(manifest)
    except OSError:
        pass
    ocr = ocr_setup.status(root, env)
    port = (env.get("PORT") or "5000").strip()
    facts = [
        ("setup_completed_utc", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")),
        ("mode", mode),
        ("runtime", "embedded (runtime\\)" if embedded else "venv fallback"),
        ("application_revision", discover_revision(root)),
        ("installation_root", root),
        ("port", port),
        ("windows", platform.platform()),
        ("os_architecture", env.get("PROCESSOR_ARCHITEW6432") or env.get("PROCESSOR_ARCHITECTURE")
         or platform.machine()),
        ("python_version", platform.python_version()),
        ("python_architecture", f"{struct.calcsize('P') * 8}-bit {platform.machine()}"),
        ("python_executable", sys.executable),
        ("asset_manifest_sha256", asset_hash or "not available"),
        ("tesseract_status", "ready" if ocr["ready"] else "unavailable (optional; image OCR disabled)"),
        ("tesseract_path", ocr["path"] or "not found"),
        ("tesseract_detail", ocr_setup.describe(ocr)),
        ("data_validation", data_status),
    ]
    return facts


def write(root=None, mode="offline", environ=None):
    root = Path(root or ROOT)
    facts = collect(root, mode, environ)
    text = "".join(f"{key}={_ascii(value)}\n" for key, value in facts)
    target = root / "logs" / TARGET_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".tmp")
    partial.write_text(text, encoding="ascii")
    os.replace(partial, target)
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", default="offline")
    args = parser.parse_args(argv)
    print(f"[OK] Wrote {write(mode=args.mode)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

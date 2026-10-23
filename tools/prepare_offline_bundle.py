#!/usr/bin/env python3
"""Build a complete, checksummed Windows x64 offline deployment bundle.

The builder itself needs internet.  The resulting ZIP does not: it contains
embedded CPython, all Windows wheels, the Tesseract installer, Arabic OCR data,
the application, and the current operational JSON data (but never users or the
Flask session secret).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import verify_offline_assets                      # noqa: E402
from tools.deploy_check import MIN_HOST_PYTHON               # noqa: E402

IS_WINDOWS = os.name == "nt"
PYTHON_VERSION = "3.11.9"
PYTHON_ARCHIVE = f"python-{PYTHON_VERSION}-embed-amd64.zip"
PYTHON_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/{PYTHON_ARCHIVE}"
TESSERACT_VERSION = "5.5.0.20241111"
TESSERACT_INSTALLER = f"tesseract-ocr-w64-setup-{TESSERACT_VERSION}.exe"
TESSERACT_URL = (
    "https://github.com/tesseract-ocr/tesseract/releases/download/5.5.0/"
    + TESSERACT_INSTALLER
)
ARABIC_MODEL_URL = (
    "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/ara.traineddata"
)

TOP_LEVEL_FILES = {
    "app.py", "serve.py", "requirements.txt", "README.md", "DEPLOYMENT.md",
    "START_SYSTEM.bat", "STOP_SYSTEM.bat", "SETUP_OFFLINE.bat", "BACKUPS.bat",
    "INSTALL_AUTOSTART.bat", "SETUP_PHONE_ACCESS.bat", "run_windows.bat",
    "personnel-system.service.example",
}
INCLUDE_DIRS = ("backend", "templates", "static", "importer", "migrations", "tools", "wheels", "runtime", "data")
EXCLUDED_PARTS = {
    "__pycache__", ".pytest_cache", "import", "source_docs", "daily_files",
    "ocr_samples", "logs", "backups",
}
EXCLUDED_DATA_FILES = {"users.json", "secret_key", ".lock", ".clock_seen"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _windows_system_download(url: str, partial: Path) -> None:
    """Download with the Windows certificate store without weakening TLS."""
    curl = shutil.which("curl.exe")
    if curl:
        print("Python HTTPS verification failed; retrying with Windows curl...")
        result = subprocess.run(
            [curl, "--fail", "--location", "--retry", "3", "--retry-delay", "2",
             "--connect-timeout", "30", "--output", str(partial), url],
            check=False,
        )
        if result.returncode == 0 and partial.is_file() and partial.stat().st_size:
            return
        partial.unlink(missing_ok=True)

    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if powershell:
        print("Windows curl failed; retrying with the Windows certificate store...")
        env = os.environ.copy()
        env["PERSONNEL_DOWNLOAD_URL"] = url
        env["PERSONNEL_DOWNLOAD_TARGET"] = str(partial)
        script = (
            "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; "
            "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; "
            "Invoke-WebRequest -UseBasicParsing -Uri $env:PERSONNEL_DOWNLOAD_URL "
            "-OutFile $env:PERSONNEL_DOWNLOAD_TARGET"
        )
        result = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
            env=env,
            check=False,
        )
        if result.returncode == 0 and partial.is_file() and partial.stat().st_size:
            return
        partial.unlink(missing_ok=True)

    raise RuntimeError(
        "Secure HTTPS download failed with Python, Windows curl, and PowerShell"
    )


def download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    partial.unlink(missing_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "personnel-system-offline-builder/1"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
    except Exception:
        partial.unlink(missing_ok=True)
        if not IS_WINDOWS:
            raise
        _windows_system_download(url, partial)
    if partial.stat().st_size == 0:
        raise RuntimeError(f"Downloaded an empty file: {url}")
    os.replace(partial, target)


def prepare_runtime(work: Path) -> None:
    archive = work / PYTHON_ARCHIVE
    download(PYTHON_URL, archive)
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None or "python.exe" not in bundle.namelist():
            raise RuntimeError("The embedded Python archive is invalid")
        target = work / "runtime"
        target.mkdir()
        bundle.extractall(target)


def prepare_wheels(work: Path) -> None:
    target = work / "wheels"
    target.mkdir()
    command = [
        sys.executable, "-m", "pip", "download", "--only-binary=:all:",
        "--platform", "win_amd64", "--python-version", "3.11",
        "--implementation", "cp", "--abi", "cp311", "--dest", str(target),
        "-r", str(ROOT / "requirements.txt"),
    ]
    subprocess.run(command, check=True)
    wheels = list(target.glob("*.whl"))
    if not wheels:
        raise RuntimeError("pip did not produce any wheels")
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as bundle:
            if bundle.testzip() is not None:
                raise RuntimeError(f"Corrupt wheel: {wheel.name}")


def prepare_ocr(work: Path) -> None:
    target = work / "offline_installers"
    download(TESSERACT_URL, target / TESSERACT_INSTALLER)
    download(ARABIC_MODEL_URL, target / "ara.traineddata")


def activate_directory(source: Path, target: Path) -> Path | None:
    """Move `source` into place, keeping the previous folder as a rollback.

    Returns the retained previous folder (or None when there was none).  The
    caller deletes it with `commit_directories` once the whole set is verified,
    or restores it with `rollback_directories`.
    """
    old = target.with_name(target.name + ".old-offline-build")
    if old.exists():
        shutil.rmtree(old)
    kept = None
    if target.exists():
        target.rename(old)
        kept = old
    try:
        source.rename(target)
    except Exception:
        if kept is not None and not target.exists():
            kept.rename(target)
        raise
    return kept


def rollback_directories(done: list) -> None:
    """Undo `activate_directory` calls, newest first."""
    for target, kept in reversed(done):
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        if kept is not None and kept.exists():
            kept.rename(target)


def commit_directories(done: list) -> None:
    for _target, kept in done:
        if kept is not None and kept.exists():
            shutil.rmtree(kept, ignore_errors=True)


def install_assets(work: Path) -> list:
    """Activate runtime, wheels and installers as one unit. -> rollback records.

    If any step fails, everything already activated is restored, so a failed
    preparation never leaves a half-replaced runtime next to old wheels.
    """
    readme = ROOT / "wheels" / "README.txt"
    if readme.is_file():
        shutil.copy2(readme, work / "wheels" / "README.txt")
    done = []
    try:
        for name, target in (("runtime", ROOT / "runtime"), ("wheels", ROOT / "wheels"),
                             ("offline_installers", ROOT / "tools" / "offline_installers")):
            done.append((target, activate_directory(work / name, target)))
    except Exception:
        rollback_directories(done)
        raise
    return done


def release_files():
    for name in sorted(TOP_LEVEL_FILES):
        path = ROOT / name
        if path.is_file():
            yield path
    for directory in INCLUDE_DIRS:
        base = ROOT / directory
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            rel = path.relative_to(ROOT)
            if any(part in EXCLUDED_PARTS for part in rel.parts):
                continue
            if rel.parts[0] == "data" and path.name in EXCLUDED_DATA_FILES:
                continue
            if path.suffix in {".pyc", ".part", ".tmp"}:
                continue
            yield path


def write_asset_manifest() -> Path:
    manifest = ROOT / "OFFLINE_ASSETS.sha256"
    assets = [*sorted((ROOT / "wheels").glob("*.whl")),
              *sorted((ROOT / "runtime").glob("*")),
              *sorted((ROOT / "tools" / "offline_installers").glob("*"))]
    # python311._pth is deliberately rewritten by SETUP_OFFLINE.bat to enable
    # the project and site-packages.  It must not make a second setup look like
    # asset corruption.
    files = [path for path in assets if path.is_file() and not path.name.endswith("._pth")]
    manifest.write_text("".join(f"{sha256(path)}  {path.relative_to(ROOT).as_posix()}\n" for path in files),
                        encoding="ascii")
    return manifest


def build_archive() -> Path:
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    target = dist / f"personnel-system-offline-{date.today().isoformat()}.zip"
    partial = target.with_suffix(".zip.part")
    files = list(dict.fromkeys([*release_files(), ROOT / "OFFLINE_ASSETS.sha256"]))
    with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6,
                         allowZip64=True) as bundle:
        for path in files:
            bundle.write(path, (Path("personnel-system") / path.relative_to(ROOT)).as_posix())
    with zipfile.ZipFile(partial) as bundle:
        if bundle.testzip() is not None:
            raise RuntimeError("Generated release ZIP failed integrity validation")
    os.replace(partial, target)
    target.with_suffix(".zip.sha256").write_text(f"{sha256(target)}  {target.name}\n", encoding="ascii")
    return target


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", action="store_true", help="also create the final transfer ZIP")
    args = parser.parse_args(argv)
    # Keep the staging directory on the project volume so the final directory
    # swaps are atomic even when the system /tmp lives on another filesystem.
    if sys.version_info[:2] < MIN_HOST_PYTHON:
        print(f"[X] Python {MIN_HOST_PYTHON[0]}.{MIN_HOST_PYTHON[1]} or newer is required "
              f"on the preparation PC (found {sys.version.split()[0]}).")
        return 1
    manifest_path = ROOT / "OFFLINE_ASSETS.sha256"
    old_manifest = manifest_path.read_bytes() if manifest_path.is_file() else None
    with tempfile.TemporaryDirectory(prefix=".offline-build-", dir=ROOT) as raw:
        work = Path(raw)
        prepare_runtime(work)
        prepare_wheels(work)
        prepare_ocr(work)
        done = install_assets(work)
        # Validate the activated set before discarding the previous one.
        try:
            manifest = write_asset_manifest()
            if verify_offline_assets.verify(quiet=True) != 0:
                raise RuntimeError("The newly prepared assets failed verification")
        except Exception:
            rollback_directories(done)
            if old_manifest is None:
                manifest_path.unlink(missing_ok=True)
            else:
                manifest_path.write_bytes(old_manifest)
            print("[X] Preparation failed; the previous runtime and wheels were restored.")
            raise
        commit_directories(done)
    print(f"Asset manifest: {manifest}")
    if args.archive:
        archive = build_archive()
        print(f"Offline ZIP: {archive}")
        print(f"SHA-256: {sha256(archive)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request
import zipfile
from datetime import date
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import deploy_log, verify_offline_assets          # noqa: E402
from tools.deploy_check import MIN_HOST_PYTHON               # noqa: E402

emit = deploy_log.emit

IS_WINDOWS = os.name == "nt"
PYTHON_VERSION = "3.11.9"
PYTHON_ARCHIVE = f"python-{PYTHON_VERSION}-embed-amd64.zip"
PYTHON_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/{PYTHON_ARCHIVE}"
PIP_VERSION = "24.3.1"
TESSERACT_VERSION = "5.5.0.20241111"
TESSERACT_INSTALLER = f"tesseract-ocr-w64-setup-{TESSERACT_VERSION}.exe"
TESSERACT_URL = (
    "https://github.com/tesseract-ocr/tesseract/releases/download/5.5.0/"
    + TESSERACT_INSTALLER
)
ARABIC_MODEL_URL = (
    "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/ara.traineddata"
)
DOWNLOAD_ATTEMPTS = 3
INDRA_HF_REPO = "datalab-to/indra-ocr"
INDRA_HF_REVISION = "v1.1.0"
INDRA_MODEL_FILES = (
    "det.onnx",
    "lm.npz",
    "lm_cjk.npz",
    "lm_world.npz",
    "meta.json",
    "order.onnx",
    "orient.onnx",
    "rec.onnx",
    "rec_cjk.onnx",
    "rec_rtl.onnx",
    "rec_world.onnx",
    "script.onnx",
)

TOP_LEVEL_FILES = {
    "app.py", "serve.py", "requirements.txt", "requirements-indra-ocr.txt", "README.md", "DEPLOYMENT.md",
    "OPEN_SYSTEM.vbs", "CLOSE_SYSTEM.vbs",
    "START_SYSTEM.bat", "STOP_SYSTEM.bat", "SETUP_OFFLINE.bat", "BACKUPS.bat",
    "SETUP_PHONE_ACCESS.bat", "run_windows.bat",
    "personnel-system.service.example",
}
INCLUDE_DIRS = ("backend", "templates", "static", "importer", "migrations", "tools", "wheels", "runtime", "vendor", "data")
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
        emit("Python HTTPS download failed; retrying with Windows curl (system certificates).", "WARN")
        result = subprocess.run(
            [curl, "--fail", "--location", "--retry", "3", "--retry-delay", "2",
             "--connect-timeout", "30", "--output", str(partial), url],
            check=False,
        )
        if result.returncode == 0 and partial.is_file() and partial.stat().st_size:
            emit(f"Windows curl succeeded ({deploy_log.human_size(partial.stat().st_size)}).", "INFO")
            return
        emit(f"Windows curl failed with exit code {result.returncode}.", "WARN")
        partial.unlink(missing_ok=True)

    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if powershell:
        emit("Retrying with PowerShell Invoke-WebRequest (Windows certificate store).", "WARN")
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
            emit(f"PowerShell succeeded ({deploy_log.human_size(partial.stat().st_size)}).", "INFO")
            return
        emit(f"PowerShell failed with exit code {result.returncode}.", "WARN")
        partial.unlink(missing_ok=True)

    raise RuntimeError(
        "Secure HTTPS download failed with Python, Windows curl, and PowerShell"
    )


def _copy_with_progress(response, output, label: str) -> int:
    """Copy a response to disk, logging progress roughly every 5 seconds."""
    total = int(response.headers.get("Content-Length") or 0)
    copied, last_report, started = 0, time.monotonic(), time.monotonic()
    while True:
        chunk = response.read(1024 * 1024)
        if not chunk:
            break
        output.write(chunk)
        copied += len(chunk)
        now = time.monotonic()
        if now - last_report >= 5 and (total >= 5 * 1024 * 1024 or now - started >= 15):
            percent = f" ({copied * 100 // total}%)" if total else ""
            speed = copied / max(now - started, 0.1)
            emit(f"  {label}: {deploy_log.human_size(copied)}"
                 f"{' of ' + deploy_log.human_size(total) if total else ''}{percent}, "
                 f"{deploy_log.human_size(speed)}/s", "INFO")
            last_report = now
    if total and copied != total:
        raise RuntimeError(f"Incomplete download: got {copied} of {total} bytes")
    return copied


def download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    partial.unlink(missing_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "personnel-system-offline-builder/1"})
    started = time.monotonic()
    emit(f"Downloading {target.name} from {url}", "INFO")
    # Slow links stall mid-file; retry a few times before the Windows fallbacks.
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as output:
                _copy_with_progress(response, output, target.name)
            break
        except Exception as exc:
            partial.unlink(missing_ok=True)
            emit(f"{target.name}: attempt {attempt}/{DOWNLOAD_ATTEMPTS} failed - "
                 f"{type(exc).__name__}: {exc}", "WARN")
            if attempt < DOWNLOAD_ATTEMPTS:
                time.sleep(2 * attempt)
                continue
            if not IS_WINDOWS:
                raise
            _windows_system_download(url, partial)
    if partial.stat().st_size == 0:
        raise RuntimeError(f"Downloaded an empty file: {url}")
    size = partial.stat().st_size
    os.replace(partial, target)
    seconds = max(time.monotonic() - started, 0.01)
    emit(f"Downloaded {target.name}: {deploy_log.human_size(size)} in {seconds:.1f}s "
         f"({deploy_log.human_size(size / seconds)}/s)", "OK")


# Hosts the preparation needs.  A failure here is only a warning: the download
# that needs the host reports its own precise error, but this tells the operator
# up front that the PC cannot reach it (DNS, firewall, proxy).
REQUIRED_HOSTS = (
    ("www.python.org", "embedded Python runtime"),
    ("pypi.org", "Python package index"),
    ("files.pythonhosted.org", "Python wheels"),
    ("github.com", "Tesseract installer"),
    ("raw.githubusercontent.com", "Arabic OCR data"),
    ("huggingface.co", "Indra OCR models"),
)


def check_connectivity(hosts=REQUIRED_HOSTS) -> int:
    """DNS + TCP 443 check for each host. -> number of unreachable hosts."""
    proxy = next((os.environ[name] for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")
                  if os.environ.get(name)), "")
    if proxy:
        emit(f"A proxy is configured ({proxy}); direct host checks are informational only.", "INFO")
    failed = 0
    for host, purpose in hosts:
        started = time.monotonic()
        try:
            address = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)[0][4][0]
        except OSError as exc:
            failed += 1
            emit(f"{host} ({purpose}): DNS lookup failed - {exc}", "WARN")
            continue
        try:
            with socket.create_connection((host, 443), timeout=8):
                pass
        except OSError as exc:
            failed += 1
            emit(f"{host} ({purpose}): resolved to {address} but connecting to port 443 failed - {exc}", "WARN")
            continue
        emit(f"{host} ({purpose}): reachable ({address}, {(time.monotonic() - started) * 1000:.0f} ms)", "OK")
    if failed:
        emit(f"{failed} of {len(hosts)} required hosts are unreachable. Downloads from them will fail: "
             "check the internet connection, DNS, firewall, antivirus web protection, or proxy.", "WARN")
    return failed


def prepare_runtime(work: Path) -> None:
    archive = work / PYTHON_ARCHIVE
    download(PYTHON_URL, archive)
    emit(f"Checking the {PYTHON_ARCHIVE} archive and extracting it", "INFO")
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None or "python.exe" not in bundle.namelist():
            raise RuntimeError("The embedded Python archive is invalid")
        target = work / "runtime"
        target.mkdir()
        bundle.extractall(target)
    emit(f"Embedded Python {PYTHON_VERSION} extracted ({len(list(target.iterdir()))} files)", "OK")


def _pip_download(label: str, extra: list, dest: Path) -> None:
    command = [
        sys.executable, "-m", "pip", "download", "--only-binary=:all:",
        "--platform", "win_amd64", "--python-version", "3.11",
        "--implementation", "cp", "--abi", "cp311", *extra, "--dest", str(dest),
    ]
    result = deploy_log.stream_run(command, label=f"pip download ({label})")
    if result.returncode != 0:
        last = result.tail[-1] if result.tail else "no output"
        raise RuntimeError(f"pip download for {label} failed with exit code {result.returncode}: {last}")


def prepare_wheels(work: Path) -> None:
    target = work / "wheels"
    target.mkdir()
    _pip_download("application requirements", ["-r", str(ROOT / "requirements.txt")], target)
    _pip_download(f"pip {PIP_VERSION}", ["--no-deps", f"pip=={PIP_VERSION}"], target)
    indra_target = target / "indra"
    indra_target.mkdir()
    _pip_download("Indra OCR", ["-r", str(ROOT / "requirements-indra-ocr.txt")], indra_target)
    wheels = list(target.rglob("*.whl"))
    if not wheels:
        raise RuntimeError("pip did not produce any wheels")
    emit(f"Checking the integrity of {len(wheels)} wheel files", "INFO")
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as bundle:
            if bundle.testzip() is not None:
                raise RuntimeError(f"Corrupt wheel: {wheel.name}")
    total = sum(wheel.stat().st_size for wheel in wheels)
    indra_wheels = sorted(path.name for path in indra_target.glob("*.whl"))
    emit(f"{len(wheels)} wheels ready ({deploy_log.human_size(total)}); "
         f"{len(indra_wheels)} are for Indra OCR: {', '.join(indra_wheels)}", "OK")
    if not any(name.startswith("indra_ocr-") for name in indra_wheels):
        raise RuntimeError("The Indra OCR wheel (indra_ocr-*.whl) was not downloaded")


def prepare_ocr(work: Path) -> None:
    target = work / "offline_installers"
    download(TESSERACT_URL, target / TESSERACT_INSTALLER)
    download(ARABIC_MODEL_URL, target / "ara.traineddata")


def indra_api_url(repo=INDRA_HF_REPO, revision=INDRA_HF_REVISION) -> str:
    return ("https://huggingface.co/api/models/"
            f"{quote(repo, safe='/')}/revision/{quote(revision, safe='')}")


def indra_blobs_url(repo=INDRA_HF_REPO, revision=INDRA_HF_REVISION) -> str:
    """Same pinned revision, with each file's size and SHA-256 included."""
    return indra_api_url(repo, revision) + "?blobs=true"


def indra_resolve_url(filename: str, repo=INDRA_HF_REPO,
                      revision=INDRA_HF_REVISION) -> str:
    return (f"https://huggingface.co/{quote(repo, safe='/')}/resolve/"
            f"{quote(revision, safe='')}/{quote(filename, safe='/')}")


MODEL_FETCH_ATTEMPTS = 3


def _published_checks(sibling: dict):
    """-> (size, sha256) published by the model host; either may be None."""
    lfs = sibling.get("lfs") if isinstance(sibling.get("lfs"), dict) else {}
    size = lfs.get("size", sibling.get("size"))
    sha = lfs.get("sha256")
    return (size if isinstance(size, int) else None), (sha if isinstance(sha, str) else None)


def prepare_indra_models(work: Path, downloader=download) -> None:
    """Download the pinned default Indra snapshot using only the stdlib.

    Every file is compared with the size and SHA-256 the model host publishes,
    and re-downloaded (up to MODEL_FETCH_ATTEMPTS times) when it does not match,
    so a truncated or altered model can never reach the offline machines.
    """
    metadata = work / "indra-model-snapshot.json"
    emit(f"Model repository: {INDRA_HF_REPO}, pinned revision {INDRA_HF_REVISION}", "INFO")
    downloader(indra_blobs_url(), metadata)
    try:
        payload = json.loads(metadata.read_text(encoding="utf-8"))
        siblings = {
            item.get("rfilename"): item for item in payload.get("siblings", [])
            if isinstance(item, dict)
        }
    except (OSError, UnicodeError, ValueError, AttributeError) as exc:
        raise RuntimeError("The Indra model API returned invalid metadata") from exc
    missing = [name for name in INDRA_MODEL_FILES if name not in siblings]
    if missing:
        raise RuntimeError("The pinned Indra snapshot is missing: " + ", ".join(missing))
    emit(f"The model host lists {len(siblings)} files; downloading the {len(INDRA_MODEL_FILES)} "
         "that the system uses.", "INFO")
    target = work / "indra-models"
    target.mkdir()
    verified = unverified = 0
    for number, name in enumerate(INDRA_MODEL_FILES, 1):
        expected_size, expected_sha = _published_checks(siblings[name])
        path = target / name
        for attempt in range(1, MODEL_FETCH_ATTEMPTS + 1):
            emit(f"Model {number}/{len(INDRA_MODEL_FILES)}: {name}"
                 f" (expected {deploy_log.human_size(expected_size) if expected_size else 'unknown size'})", "INFO")
            downloader(indra_resolve_url(name), path)
            actual_size = path.stat().st_size
            problem = ""
            if expected_size is not None and actual_size != expected_size:
                problem = f"size {actual_size} differs from the published {expected_size}"
            elif expected_sha:
                actual_sha = sha256(path)
                if actual_sha != expected_sha:
                    problem = f"SHA-256 {actual_sha[:16]}... differs from the published {expected_sha[:16]}..."
            if not problem:
                break
            emit(f"{name}: {problem} (attempt {attempt}/{MODEL_FETCH_ATTEMPTS})", "WARN")
            path.unlink(missing_ok=True)
            if attempt == MODEL_FETCH_ATTEMPTS:
                raise RuntimeError(f"Indra model {name} failed verification: {problem}")
        if expected_sha:
            verified += 1
            emit(f"{name}: {deploy_log.human_size(actual_size)}, SHA-256 matches the model host "
                 f"({expected_sha[:16]}...)", "OK")
        else:
            unverified += 1
            emit(f"{name}: {deploy_log.human_size(actual_size)}; the model host publishes no SHA-256 "
                 "for this small file, so only its size was checked.", "INFO")
    total = sum(path.stat().st_size for path in target.iterdir())
    emit(f"{len(INDRA_MODEL_FILES)} Indra model files ready ({deploy_log.human_size(total)}): "
         f"{verified} verified by SHA-256, {unverified} by size only.", "OK")


def activate_directory(source: Path, target: Path) -> Path | None:
    """Move `source` into place, keeping the previous folder as a rollback.

    Returns the retained previous folder (or None when there was none).  The
    caller deletes it with `commit_directories` once the whole set is verified,
    or restores it with `rollback_directories`.
    """
    old = target.with_name(target.name + ".old-offline-build")
    target.parent.mkdir(parents=True, exist_ok=True)
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
                             ("offline_installers", ROOT / "tools" / "offline_installers"),
                             ("indra-models", ROOT / "vendor" / "indra-models")):
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
    assets = [*sorted((ROOT / "wheels").rglob("*.whl")),
              *sorted((ROOT / "runtime").glob("*")),
              *sorted((ROOT / "tools" / "offline_installers").glob("*")),
              *sorted((ROOT / "vendor" / "indra-models").glob("*"))]
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


class StageFailed(Exception):
    """A preparation stage failed; the reason was already printed as [X] lines."""


def run_stage(number: int, total: int, title: str, function, *args):
    emit("", "")
    emit(f"=== Stage {number}/{total}: {title} ===", "INFO")
    started = time.monotonic()
    try:
        result = function(*args)
    except Exception as exc:
        emit(f"Stage {number}/{total} ({title}) failed: {type(exc).__name__}: {exc}", "X")
        for line in traceback.format_exc().splitlines():
            deploy_log._write_log("    " + line)
            deploy_log._write_console("    " + line)
        raise StageFailed(title) from exc
    emit(f"Stage {number}/{total} done in {time.monotonic() - started:.0f}s", "INFO")
    return result


def log_environment() -> None:
    emit(f"Preparing {ROOT}", "INFO")
    emit(f"Python {sys.version.split()[0]} at {sys.executable}", "INFO")
    try:
        free = shutil.disk_usage(ROOT).free
        emit(f"Free disk space on this volume: {deploy_log.human_size(free)}", "INFO")
    except OSError as exc:
        emit(f"Could not read free disk space: {exc}", "WARN")
    for name in ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "PIP_INDEX_URL", "PIP_PROXY"):
        value = os.environ.get(name) or os.environ.get(name.lower())
        if value:
            emit(f"Environment {name}={value}", "INFO")


def log_summary() -> None:
    emit("", "")
    emit("=== What is now installed in this project folder ===", "INFO")
    wheels = list((ROOT / "wheels").rglob("*.whl"))
    groups = (
        ("runtime", [path for path in (ROOT / "runtime").glob("*") if path.is_file()]),
        ("wheels", wheels),
        ("tools/offline_installers", [path for path in (ROOT / "tools" / "offline_installers").glob("*")
                                      if path.is_file()]),
        ("vendor/indra-models", [path for path in (ROOT / "vendor" / "indra-models").glob("*")
                                 if path.is_file()]),
    )
    for name, files in groups:
        total = sum(path.stat().st_size for path in files)
        emit(f"{name}: {len(files)} files, {deploy_log.human_size(total)}", "INFO")
    for path in sorted((ROOT / "vendor" / "indra-models").glob("*")):
        emit(f"  {path.name}  {deploy_log.human_size(path.stat().st_size)}  sha256 {sha256(path)[:16]}...", "INFO")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", action="store_true", help="also create the final transfer ZIP")
    args = parser.parse_args(argv)
    # Keep the staging directory on the project volume so the final directory
    # swaps are atomic even when the system /tmp lives on another filesystem.
    if sys.version_info[:2] < MIN_HOST_PYTHON:
        emit(f"Python {MIN_HOST_PYTHON[0]}.{MIN_HOST_PYTHON[1]} or newer is required "
             f"on the preparation PC (found {sys.version.split()[0]}).", "X")
        return 1
    manifest_path = ROOT / "OFFLINE_ASSETS.sha256"
    old_manifest = manifest_path.read_bytes() if manifest_path.is_file() else None
    log_environment()
    stages = (
        ("Checking internet access to every download host", check_connectivity),
        ("Embedded Python runtime", prepare_runtime),
        ("Python wheels (application + Indra OCR)", prepare_wheels),
        ("Tesseract installer and Arabic data", prepare_ocr),
        ("Indra OCR models (verified against the model host)", prepare_indra_models),
    )
    try:
        with tempfile.TemporaryDirectory(prefix=".offline-build-", dir=ROOT) as raw:
            work = Path(raw)
            total = len(stages) + 1
            for number, (title, function) in enumerate(stages, 1):
                if function is check_connectivity:
                    run_stage(number, total, title, function)
                else:
                    run_stage(number, total, title, function, work)
            done = run_stage(total, total, "Activating the new assets (previous ones kept until verified)",
                             install_assets, work)
            # Validate the activated set before discarding the previous one.
            try:
                manifest = write_asset_manifest()
                emit(f"Wrote the checksum manifest {manifest.name}; verifying every asset against it", "INFO")
                if verify_offline_assets.verify(quiet=True) != 0:
                    raise RuntimeError("The newly prepared assets failed verification")
            except Exception as exc:
                rollback_directories(done)
                if old_manifest is None:
                    manifest_path.unlink(missing_ok=True)
                else:
                    manifest_path.write_bytes(old_manifest)
                emit(f"Verification failed ({exc}); the previous runtime and wheels were restored.", "X")
                raise StageFailed("verification") from exc
            commit_directories(done)
    except StageFailed:
        return 1
    except Exception as exc:  # anything unexpected must still end with a clear [X] line
        emit(f"Unexpected error: {type(exc).__name__}: {exc}", "X")
        for line in traceback.format_exc().splitlines():
            deploy_log._write_log("    " + line)
            deploy_log._write_console("    " + line)
        return 1
    emit(f"Asset manifest: {manifest}", "OK")
    log_summary()
    if args.archive:
        archive = build_archive()
        emit(f"Offline ZIP: {archive}", "OK")
        emit(f"SHA-256: {sha256(archive)}", "OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

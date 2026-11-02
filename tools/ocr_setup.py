#!/usr/bin/env python3
"""Locate and check the OPTIONAL Tesseract engine used for image OCR.

OCR is one feature of the personnel system, never a startup requirement.
For `status`, the exit code continues to describe Tesseract readiness only;
Indra readiness is printed as an additional informational line.

    python tools/ocr_setup.py status [--quiet]      # exit 0 ready, 1 unavailable
    python tools/ocr_setup.py find                  # print the executable path
    python tools/ocr_setup.py setup-indra           # online, optional
    python tools/ocr_setup.py setup-indra --offline # wheels + local models

Search order for tesseract.exe: a valid TESSERACT_CMD already in the
environment, the project copy (tools/tesseract), %ProgramFiles%,
%ProgramFiles(x86)%, %LOCALAPPDATA%\\Programs, then PATH.
Arabic data is kept inside the project (tools/tesseract/tessdata) and is
refreshed from tools/offline_installers/ara.traineddata when that file exists.
Standard library only; ASCII console output.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXE_NAME = "tesseract.exe"
LANGUAGE = "ara"
INDRA_MODEL_FILES = (
    "det.onnx", "lm.npz", "lm_cjk.npz", "lm_world.npz", "meta.json",
    "order.onnx", "orient.onnx", "rec.onnx", "rec_cjk.onnx", "rec_rtl.onnx",
    "rec_world.onnx", "script.onnx",
)


def project_exe(root=None):
    return Path(root or ROOT) / "tools" / "tesseract" / EXE_NAME


def project_tessdata(root=None):
    return Path(root or ROOT) / "tools" / "tesseract" / "tessdata"


def installer_model(root=None):
    return Path(root or ROOT) / "tools" / "offline_installers" / f"{LANGUAGE}.traineddata"


def candidates(root=None, environ=None):
    """Ordered (label, path) pairs; PATH lookup is appended by `find_tesseract`."""
    env = os.environ if environ is None else environ
    items = []
    supplied = (env.get("TESSERACT_CMD") or "").strip().strip('"')
    if supplied:
        items.append(("TESSERACT_CMD", Path(supplied)))
    items.append(("project", project_exe(root)))
    for var, label in (("ProgramFiles", "ProgramFiles"), ("ProgramFiles(x86)", "ProgramFiles(x86)")):
        base = env.get(var)
        if base:
            items.append((label, Path(base) / "Tesseract-OCR" / EXE_NAME))
    local = env.get("LOCALAPPDATA")
    if local:
        items.append(("LOCALAPPDATA", Path(local) / "Programs" / "Tesseract-OCR" / EXE_NAME))
    return items


def find_tesseract(root=None, environ=None, which=shutil.which):
    """-> (path, source) of the first existing executable, or (None, reason)."""
    notes = []
    for label, path in candidates(root, environ):
        if path.is_file():
            return str(path), label
        if label == "TESSERACT_CMD":
            notes.append(f"TESSERACT_CMD points to a missing file: {path}")
    found = which("tesseract")
    if found:
        return found, "PATH"
    return None, "; ".join(notes) or "tesseract.exe was not found"


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sync_arabic_data(root=None):
    """Copy the prepared Arabic model into the project tessdata. -> True if present."""
    source = installer_model(root)
    target = project_tessdata(root) / f"{LANGUAGE}.traineddata"
    if source.is_file():
        if not target.is_file() or _sha256(source) != _sha256(target):
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    return target.is_file()


def status(root=None, environ=None, which=shutil.which, run=subprocess.run):
    """-> dict(ready, path, source, tessdata, reason). Never raises for OCR problems."""
    result = {"ready": False, "path": None, "source": None, "tessdata": None, "reason": ""}
    try:
        has_project_data = sync_arabic_data(root)
    except OSError as exc:
        has_project_data = project_tessdata(root).joinpath(f"{LANGUAGE}.traineddata").is_file()
        result["reason"] = f"could not refresh project Arabic data ({exc})"
    path, source = find_tesseract(root, environ, which)
    if not path:
        result["reason"] = source
        return result
    result.update(path=path, source=source)
    env = dict(os.environ if environ is None else environ)
    if has_project_data:
        env["TESSDATA_PREFIX"] = str(project_tessdata(root))
        result["tessdata"] = env["TESSDATA_PREFIX"]
    elif env.get("TESSDATA_PREFIX"):
        result["tessdata"] = env["TESSDATA_PREFIX"]
    try:
        listing = run([path, "--list-langs"], env=env, capture_output=True, text=True,
                      timeout=30, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        result["reason"] = f"tesseract could not be run ({exc})"
        return result
    if listing.returncode != 0:
        result["reason"] = f"tesseract --list-langs failed with exit code {listing.returncode}"
        return result
    langs = {line.strip() for line in (listing.stdout or "").splitlines()}
    if LANGUAGE not in langs:
        result["reason"] = "Arabic language data (ara) is missing"
        return result
    result["ready"] = True
    result["reason"] = ""
    return result


def describe(info):
    """ASCII, single-line summary used by logs and the deployment manifest."""
    if info["ready"]:
        return f"ready ({info['source']}: {info['path']})"
    return f"unavailable ({info['reason']})"


def indra_status(root=None, python=None):
    """Cheap readiness check; model loading is reserved for setup/worker runs."""
    root = Path(root or ROOT)
    site = root / "vendor" / "indra-site"
    models = root / "vendor" / "indra-models"
    missing = [name for name in INDRA_MODEL_FILES if not (models / name).is_file()]
    result = {
        "ready": False,
        "reason": "",
        "python": str(python or sys.executable),
        "site": str(site),
        "models": str(models),
    }
    if not site.joinpath("indra_ocr").is_dir():
        result["reason"] = "vendor/indra-site is not installed"
        return result
    if missing:
        result["reason"] = "model files are missing: " + ", ".join(missing)
        return result
    result["ready"] = True
    return result


def describe_indra(info):
    if info["ready"]:
        return f"ready ({info['site']}; models: {info['models']})"
    return f"unavailable ({info['reason']})"


def setup_indra(root=None, python=None, wheelhouse=None, model_dir=None,
                offline=False, run=subprocess.run):
    """Install Indra into a worker-only target using the application's Python."""
    root = Path(root or ROOT)
    source_python = str(python or sys.executable)
    site = root / "vendor" / "indra-site"
    models = Path(model_dir) if model_dir else root / "vendor" / "indra-models"
    wheels = Path(wheelhouse) if wheelhouse else root / "wheels" / "indra"
    requirements = root / "requirements-indra-ocr.txt"
    worker = root / "tools" / "indra_ocr_worker.py"
    install = [source_python, "-m", "pip", "install", "--upgrade", "--ignore-installed"]
    if offline:
        install.extend(["--no-index", "--find-links", str(wheels)])
    install.extend(["--target", str(site), "-r", str(requirements)])
    installed = run(install, check=False)
    if installed.returncode != 0:
        return {"ready": False, "reason": "could not install indra-ocr"}

    env = os.environ.copy()
    env["INDRA_OCR_MODEL_DIR"] = str(models)
    if offline:
        env["HF_HUB_OFFLINE"] = "1"
    checked = run(
        [source_python, str(worker), "--site-dir", str(site), "--check"],
        env=env,
        check=False,
    )
    if checked.returncode != 0:
        return {"ready": False, "reason": "Indra models are unavailable or invalid"}
    return {"ready": True, "python": source_python, "site": str(site),
            "models": str(models), "reason": ""}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_status = sub.add_parser("status")
    p_status.add_argument("--quiet", action="store_true")
    sub.add_parser("find")
    p_indra = sub.add_parser("setup-indra")
    p_indra.add_argument("--offline", action="store_true")
    p_indra.add_argument("--python")
    p_indra.add_argument("--wheelhouse")
    p_indra.add_argument("--model-dir")
    args = parser.parse_args(argv)

    if args.cmd == "find":
        path, source = find_tesseract()
        if not path:
            print(source)
            return 1
        print(path)
        return 0
    if args.cmd == "setup-indra":
        info = setup_indra(
            python=args.python,
            wheelhouse=args.wheelhouse,
            model_dir=args.model_dir,
            offline=args.offline,
        )
        if info["ready"]:
            print(f"[OK] Indra OCR ready ({info['python']}; models: {info['models']})")
            return 0
        print(f"[WARNING] Indra OCR unavailable ({info['reason']})")
        return 1
    info = status()
    if not args.quiet:
        print(("[OK] OCR " if info["ready"] else "[WARNING] OCR ") + describe(info))
        indra = indra_status()
        print(("[OK] Indra OCR " if indra["ready"] else "[INFO] Indra OCR ")
              + describe_indra(indra))
        if not info["ready"]:
            print("Image OCR is unavailable. The personnel system itself works without it.")
    return 0 if info["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())

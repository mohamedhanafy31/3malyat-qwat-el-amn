#!/usr/bin/env python3
"""Locate and check the OPTIONAL Tesseract engine used for image OCR.

OCR is one feature of the personnel system, never a startup requirement.
For `status`, the exit code continues to describe Tesseract readiness only;
Indra readiness is printed as an additional informational line.

    python tools/ocr_setup.py status [--quiet]      # exit 0 ready, 1 unavailable
    python tools/ocr_setup.py find                  # print the executable path
    python tools/ocr_setup.py setup-indra           # online, optional
    python tools/ocr_setup.py setup-indra --offline # wheels + local models
    python tools/ocr_setup.py indra-preflight       # list every Indra asset, exit 1 if incomplete
    python tools/ocr_setup.py indra-check           # load the models + run one real OCR inference

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

try:
    from tools import deploy_log
except ImportError:  # run as `python tools/ocr_setup.py`
    import deploy_log

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


# Exit codes a crashed worker can leave behind.  Windows reports the NTSTATUS
# value (shown by cmd as a negative number); POSIX reports -signal.
_WINDOWS_CRASHES = {
    0xC0000005: "access violation: a native library crashed (damaged model or library file, "
                "or an incompatible build)",
    0xC000001D: "illegal instruction: this CPU lacks an instruction the OCR library needs "
                "(usually AVX/AVX2 on an old processor)",
    0xC000007B: "bad image: a 32-bit/64-bit mismatch in a library",
    0xC0000135: "a required DLL was not found (Visual C++ runtime missing?)",
    0xC0000142: "a DLL failed to initialise",
    0xC0000409: "fast-fail / stack buffer overrun inside a native library",
    0xC00000FD: "stack overflow",
    0xC0000017: "not enough memory",
    0xC0000094: "integer division by zero in a native library",
    0xE06D7363: "unhandled C++ exception thrown by a native library (onnxruntime)",
}
_POSIX_SIGNALS = {4: "SIGILL (illegal instruction: CPU lacks an instruction the library needs)",
                  6: "SIGABRT", 7: "SIGBUS", 8: "SIGFPE",
                  9: "SIGKILL (often the out-of-memory killer)",
                  11: "SIGSEGV (a native library crashed)"}


def describe_exit_code(code):
    """Plain-English meaning of a worker exit code."""
    if code is None:
        return "no exit code"
    if code == 0:
        return "success"
    if code == 127:
        return "the command could not be started"
    if code < 0 and -code in _POSIX_SIGNALS:
        return f"killed by {_POSIX_SIGNALS[-code]}"
    unsigned = code & 0xFFFFFFFF
    if unsigned in _WINDOWS_CRASHES:
        return f"0x{unsigned:08X} - {_WINDOWS_CRASHES[unsigned]}"
    if unsigned > 0xFFFF:
        return f"0x{unsigned:08X} - the process crashed (Windows error code)"
    return "the worker stopped with a Python error (see the traceback above)"


def _default_run(command, check=False, env=None, timeout=None):
    return deploy_log.stream_run(command, env=env, timeout=timeout, check=check, label="Running")


def indra_preflight(root=None, need_wheel=True):
    """Log every asset the Indra worker needs. -> list of problems (empty = complete).

    need_wheel is False when checking an install that already exists.
    """
    root = Path(root or ROOT)
    emit = deploy_log.emit
    problems = []
    emit("Checking the Indra OCR assets", "INFO")
    requirements = root / "requirements-indra-ocr.txt"
    emit(f"requirements-indra-ocr.txt: {'present' if requirements.is_file() else 'MISSING'}", "INFO")
    if not requirements.is_file():
        problems.append("requirements-indra-ocr.txt is missing")
    wheels = sorted((root / "wheels" / "indra").glob("*.whl"))
    for wheel in wheels:
        emit(f"  wheel {wheel.name}  {deploy_log.human_size(wheel.stat().st_size)}", "INFO")
    if need_wheel and not any(wheel.name.startswith("indra_ocr-") for wheel in wheels):
        problems.append("wheels/indra/indra_ocr-*.whl is missing (run PREPARE_ONLINE.bat with internet)")
    models = root / "vendor" / "indra-models"
    emit(f"Model folder: {models} ({'present' if models.is_dir() else 'MISSING'})", "INFO")
    for name in INDRA_MODEL_FILES:
        path = models / name
        if not path.is_file():
            emit(f"  model {name}: MISSING", "WARN")
            problems.append(f"model file {name} is missing")
        elif path.stat().st_size == 0:
            emit(f"  model {name}: EMPTY (0 bytes)", "WARN")
            problems.append(f"model file {name} is empty")
        else:
            emit(f"  model {name}  {deploy_log.human_size(path.stat().st_size)}", "INFO")
    for problem in problems:
        emit(f"Indra OCR assets incomplete: {problem}", "WARN")
    if not problems:
        emit("All Indra OCR assets are present.", "OK")
    return problems


def _worker_env(models, offline):
    env = os.environ.copy()
    env["INDRA_OCR_MODEL_DIR"] = str(models)
    if offline or Path(models).is_dir():
        env["HF_HUB_OFFLINE"] = "1"
    return env


def verify_indra(root, python, site, models, run, offline=True):
    """Load the models, then run one real inference. -> (ready, reason)."""
    emit = deploy_log.emit
    worker = Path(root) / "tools" / "indra_ocr_worker.py"
    env = _worker_env(models, offline)
    emit("Step: loading the Indra models in a separate worker process", "INFO")
    checked = run([python, str(worker), "--site-dir", str(site), "--check"],
                  env=env, check=False, timeout=900)
    if checked.returncode != 0:
        emit(f"The worker could not load the models: {describe_exit_code(checked.returncode)}", "WARN")
        return False, f"the models could not be loaded ({describe_exit_code(checked.returncode)})"
    emit("The models loaded. Step: running one real OCR inference on a test image", "INFO")
    tested = run([python, str(worker), "--site-dir", str(site), "--selftest"],
                 env=env, check=False, timeout=900)
    if tested.returncode != 0:
        emit(f"The OCR inference failed: {describe_exit_code(tested.returncode)}", "WARN")
        return False, f"the OCR inference failed ({describe_exit_code(tested.returncode)})"
    return True, ""


def setup_indra(root=None, python=None, wheelhouse=None, model_dir=None,
                offline=False, run=None):
    """Install Indra into a worker-only target using the application's Python."""
    run = run or _default_run
    emit = deploy_log.emit
    root = Path(root or ROOT)
    source_python = str(python or sys.executable)
    site = root / "vendor" / "indra-site"
    models = Path(model_dir) if model_dir else root / "vendor" / "indra-models"
    wheels = Path(wheelhouse) if wheelhouse else root / "wheels" / "indra"
    requirements = root / "requirements-indra-ocr.txt"
    emit(f"Indra setup: python={source_python} ({sys.version.split()[0]} running this script)", "INFO")
    emit(f"Indra setup: install target={site}, models={models}, "
         f"wheelhouse={wheels if offline else 'online index'}, mode={'offline' if offline else 'online'}",
         "INFO")
    install = [source_python, "-m", "pip", "install", "--upgrade", "--ignore-installed"]
    if offline:
        install.extend(["--no-index", "--find-links", str(wheels)])
    install.extend(["--target", str(site), "-r", str(requirements)])
    emit("Step: installing the Indra OCR package into vendor/indra-site", "INFO")
    installed = run(install, check=False)
    if installed.returncode != 0:
        emit(f"pip failed with exit code {installed.returncode}. Check the pip lines above; "
             "an offline install needs every wheel in wheels/indra.", "WARN")
        return {"ready": False, "reason": f"could not install indra-ocr (pip exit code {installed.returncode})"}
    emit("The Indra OCR package is installed.", "OK")
    ready, reason = verify_indra(root, source_python, site, models, run, offline)
    if not ready:
        return {"ready": False, "reason": reason}
    return {"ready": True, "python": source_python, "site": str(site),
            "models": str(models), "reason": ""}


def check_indra(root=None, python=None, run=None):
    """Verify an existing Indra install without reinstalling it. -> (ready, reason)."""
    run = run or _default_run
    root = Path(root or ROOT)
    problems = indra_preflight(root, need_wheel=False)
    site = root / "vendor" / "indra-site"
    if not (site / "indra_ocr").is_dir():
        problems.append("vendor/indra-site is not installed")
        deploy_log.emit("vendor/indra-site is not installed (run SETUP_OFFLINE.bat).", "WARN")
    if problems:
        return False, "; ".join(problems)
    return verify_indra(root, str(python or sys.executable), site,
                        root / "vendor" / "indra-models", run)


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
    sub.add_parser("indra-preflight")
    p_check = sub.add_parser("indra-check")
    p_check.add_argument("--python")
    args = parser.parse_args(argv)

    if args.cmd == "find":
        path, source = find_tesseract()
        if not path:
            print(source)
            return 1
        print(path)
        return 0
    if args.cmd == "indra-preflight":
        return 1 if indra_preflight() else 0
    if args.cmd == "indra-check":
        ready, reason = check_indra(python=args.python)
        if ready:
            deploy_log.emit("Indra OCR is READY: models load and a real inference runs.", "OK")
            return 0
        deploy_log.emit(f"Indra OCR is NOT ready: {reason}. Photo import will use the weaker "
                        "fallback engine until this is fixed.", "WARN")
        return 1
    if args.cmd == "setup-indra":
        info = setup_indra(
            python=args.python,
            wheelhouse=args.wheelhouse,
            model_dir=args.model_dir,
            offline=args.offline,
        )
        if info["ready"]:
            deploy_log.emit(f"Indra OCR ready ({info['python']}; models: {info['models']})", "OK")
            return 0
        deploy_log.emit(f"Indra OCR unavailable ({info['reason']})", "WARN")
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

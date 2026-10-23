#!/usr/bin/env python3
"""Verify every downloaded offline runtime asset before installation.

The checksum manifest must be complete for the prepared-clone contract, not
merely non-empty: the embedded runtime executables, at least one wheel, and the
Tesseract installer together with the Arabic model (listed together, and listed
whenever those files exist on disk) must all be present and match. Every wheel
or installer on disk must also be listed, because setup installs everything it
finds. Failures always name the offending file; --quiet only hides the success
line. Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path, PurePosixPath, PureWindowsPath


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "OFFLINE_ASSETS.sha256"

# python311._pth is deliberately rewritten by setup (project root + site-packages),
# so it is never part of the manifest.
ALLOWED_PREFIXES = ("runtime/", "wheels/", "tools/offline_installers/")
REQUIRED_RUNTIME = ("runtime/python.exe", "runtime/pythonw.exe")
RUNTIME_DLL = re.compile(r"runtime/python3\d+\.dll", re.IGNORECASE)
TESSERACT_INSTALLER = re.compile(r"tools/offline_installers/tesseract-ocr-w64-setup-.+\.exe",
                                 re.IGNORECASE)
ARABIC_MODEL = "tools/offline_installers/ara.traineddata"
_HEX64 = re.compile(r"[0-9a-f]{64}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_sha256() -> str:
    """Hash of the manifest file itself (support information), or '' if missing."""
    return sha256(MANIFEST) if MANIFEST.is_file() else ""


def safe_relative(text: str) -> str | None:
    """Normalised POSIX path inside the project, or None when it is not acceptable."""
    if not text or text != text.strip() or "\\" in text or ":" in text or "\x00" in text:
        return None
    posix = PurePosixPath(text)
    if posix.is_absolute() or PureWindowsPath(text).is_absolute():
        return None
    if any(part in ("", ".", "..") for part in text.split("/")):
        return None
    normal = posix.as_posix()
    if not normal.startswith(ALLOWED_PREFIXES):
        return None
    return normal


def _inside_project(path: Path) -> bool:
    try:
        path.resolve().relative_to(ROOT.resolve())
    except (OSError, ValueError):
        return False
    return True


def parse_manifest(text: str):
    """-> (entries {relative: digest}, problems). Never raises on malformed text."""
    entries, problems = {}, []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            expected, relative = line.split("  ", 1)
        except ValueError:
            problems.append(f"Invalid manifest line {number}")
            continue
        if not _HEX64.fullmatch(expected):
            problems.append(f"Invalid checksum on manifest line {number}")
            continue
        normal = safe_relative(relative)
        if normal is None:
            problems.append(f"Unsafe or unexpected asset path on manifest line {number}: {relative!r}")
            continue
        if normal in entries:
            problems.append(f"Duplicate manifest entry: {normal}")
            continue
        entries[normal] = expected
    return entries, problems


def completeness_problems(entries, root: Path):
    """Contract checks against the manifest and the files actually on disk."""
    problems = []
    for name in REQUIRED_RUNTIME:
        if name not in entries:
            problems.append(f"Manifest is incomplete: missing runtime executable {name}")
    if not any(RUNTIME_DLL.fullmatch(name) for name in entries):
        problems.append("Manifest is incomplete: missing runtime Python DLL (runtime/python3XX.dll)")
    if not any(name.startswith("wheels/") and name.endswith(".whl") for name in entries):
        problems.append("Manifest is incomplete: no wheels are listed")

    listed_installer = any(TESSERACT_INSTALLER.fullmatch(name) for name in entries)
    disk_installers = sorted((root / "tools" / "offline_installers").glob("tesseract-ocr-w64-setup-*.exe"))
    disk_model = (root / ARABIC_MODEL).is_file()
    if listed_installer or disk_installers or ARABIC_MODEL in entries or disk_model:
        if not listed_installer:
            problems.append("Manifest is incomplete: missing Tesseract installer")
        if ARABIC_MODEL not in entries:
            problems.append(f"Manifest is incomplete: missing {ARABIC_MODEL}")

    for folder, pattern in (("wheels", "*.whl"),
                            ("tools/offline_installers", "*")):
        base = root / folder
        if not base.is_dir():
            continue
        for path in sorted(base.glob(pattern)):
            relative = path.relative_to(root).as_posix()
            if path.is_file() and relative not in entries:
                problems.append(f"File is not covered by the manifest: {relative}")
    return problems


def verify(quiet: bool = False) -> int:
    def fail(message: str) -> int:
        print(f"[X] {message}")
        return 1

    if not MANIFEST.is_file():
        return fail(f"Missing checksum manifest: {MANIFEST}")
    try:
        text = MANIFEST.read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError) as exc:
        return fail(f"Cannot read checksum manifest {MANIFEST}: {exc}")
    entries, problems = parse_manifest(text)
    if not entries and not problems:
        problems.append("Offline checksum manifest is empty")
    if problems:
        for problem in problems:
            print(f"[X] {problem}")
        return 1

    problems = completeness_problems(entries, ROOT)
    for relative, expected in sorted(entries.items()):
        path = ROOT / relative
        if not _inside_project(path):
            problems.append(f"Offline asset resolves outside the project: {relative}")
        elif not path.is_file():
            problems.append(f"Missing offline asset: {relative}")
        elif sha256(path) != expected:
            problems.append(f"Corrupt offline asset (checksum mismatch): {relative}")
    if problems:
        for problem in problems:
            print(f"[X] {problem}")
        print("[X] Run PREPARE_ONLINE.bat again on a PC with internet to repair the assets.")
        return 1
    if not quiet:
        print(f"[OK] Verified {len(entries)} offline runtime assets")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true", help="hide the success line only")
    args = parser.parse_args(argv)
    return verify(args.quiet)


if __name__ == "__main__":
    raise SystemExit(main())

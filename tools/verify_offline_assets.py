#!/usr/bin/env python3
"""Verify every downloaded offline runtime asset before installation."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "OFFLINE_ASSETS.sha256"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(quiet: bool = False) -> int:
    if not MANIFEST.is_file():
        if not quiet:
            print(f"[X] Missing checksum manifest: {MANIFEST}")
        return 1
    checked = 0
    for number, line in enumerate(MANIFEST.read_text(encoding="ascii").splitlines(), 1):
        if not line.strip():
            continue
        try:
            expected, relative = line.split("  ", 1)
        except ValueError:
            if not quiet:
                print(f"[X] Invalid manifest line {number}")
            return 1
        path = ROOT / Path(relative)
        if not path.is_file() or sha256(path) != expected:
            if not quiet:
                print(f"[X] Missing or corrupt offline asset: {relative}")
            return 1
        checked += 1
    if checked == 0:
        if not quiet:
            print("[X] Offline checksum manifest is empty")
        return 1
    if not quiet:
        print(f"[OK] Verified {checked} offline runtime assets")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    return verify(args.quiet)


if __name__ == "__main__":
    raise SystemExit(main())

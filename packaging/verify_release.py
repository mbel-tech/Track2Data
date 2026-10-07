"""Verify a downloaded release artifact against its published checksums.

Usage::

    python packaging/verify_release.py Track2Data-setup.exe --sums SHA256SUMS.txt
    python packaging/verify_release.py Track2Data-x86_64.AppImage \\
        --sums SHA256SUMS.txt --sig Track2Data-x86_64.AppImage.asc

Exit codes: 0 verified, 1 mismatch / not listed / bad signature, 2 gpg unavailable.

The Authenticode (Windows) and notarisation (macOS) checks need the platform
tools and are listed in ``docs/CODE_SIGNING.md`` section 5.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path


def parse_sums(text: str) -> dict[str, str]:
    """Parse ``<sha256>  <name>`` (or ``<sha256> *<name>``) lines into {name: digest}."""
    sums: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        digest, _, name = line.partition(" ")
        sums[name.strip().lstrip("*")] = digest.lower()
    return sums


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--sums", type=Path, required=True, help="SHA256SUMS.txt")
    parser.add_argument("--sig", type=Path, help="detached .asc signature (Linux AppImage)")
    args = parser.parse_args(argv)

    expected = parse_sums(args.sums.read_text(encoding="utf-8")).get(args.artifact.name)
    if expected is None:
        print(f"FAIL: {args.artifact.name} is not listed in {args.sums}")
        return 1
    actual = sha256_of(args.artifact)
    if actual != expected:
        print(f"MISMATCH: {args.artifact.name}\n  expected {expected}\n  actual   {actual}")
        return 1
    print(f"OK: sha256 matches for {args.artifact.name}")

    if args.sig is not None:
        gpg = shutil.which("gpg")
        if gpg is None:
            print("gpg is not installed; cannot check the signature", file=sys.stderr)
            return 2
        done = subprocess.run([gpg, "--verify", str(args.sig), str(args.artifact)], check=False)
        if done.returncode != 0:
            print("FAIL: gpg signature did not verify")
            return 1
        print("OK: gpg signature verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())

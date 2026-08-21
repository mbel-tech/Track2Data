"""
Writes a SHA256SUMS-style file for every regular file directly inside a
directory (release workflow, issue #43).

A dedicated script rather than a shell one-liner: `sha256sum` is
Linux/GNU-only, and `shasum` -- the usual macOS/Linux fallback --
turned out not to be on windows-2022's Git Bash either (confirmed by a
real CI failure: "shasum: command not found"). hashlib is the one
thing guaranteed identical across all three release-workflow runners,
since Python is already on PATH from actions/setup-python in every job.

Usage: python packaging/compute_sha256.py <dir> <output_file>
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: compute_sha256.py <dir> <output_file>", file=sys.stderr)
        return 2

    src_dir = Path(sys.argv[1])
    out_file = Path(sys.argv[2])

    lines = [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}"
        for path in sorted(src_dir.iterdir())
        if path.is_file()
    ]

    out_file.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    print(f"wrote {out_file} ({len(lines)} file(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

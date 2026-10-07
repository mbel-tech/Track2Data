"""Describe an idtracker.ai output folder so its layout can be shared.

Prints the file tree and, for every ``.npy`` file, its structure (array shape,
dtype, NaN count; dict keys; object attributes). Needs only numpy -- idtracker.ai
does not have to be installed. Run it on real v4 (or v5) output and paste the
result into an issue; see docs/IDTRACKERAI_V4_SAMPLES.md.

    python scripts/inspect_idtrackerai_output.py /path/to/session_folder
    python scripts/inspect_idtrackerai_output.py /path/to/session_folder --allow-pickle

SECURITY: idtracker.ai stores dicts and objects as pickles, and loading a pickle
can execute arbitrary code. Without ``--allow-pickle`` such files are listed but
NOT opened. Use the flag only on folders you produced yourself.
"""

from __future__ import annotations

import argparse
import platform
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

MAX_DEPTH = 3
MAX_ITEMS = 25


def file_tree(root: Path) -> list[str]:
    lines = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            lines.append(f"{path.relative_to(root)}  ({path.stat().st_size} bytes)")
    return lines


def _describe(obj: Any, indent: str, depth: int) -> list[str]:
    if isinstance(obj, np.ndarray):
        line = f"{indent}ndarray shape={obj.shape} dtype={obj.dtype}"
        if obj.dtype.kind == "f":
            line += f" nan={int(np.isnan(obj).sum())}"
        return [line]
    if isinstance(obj, dict):
        lines = [f"{indent}dict with {len(obj)} keys"]
        if depth >= MAX_DEPTH:
            return lines
        for key in list(obj)[:MAX_ITEMS]:
            lines.append(f"{indent}  [{key!r}]")
            lines += _describe(obj[key], indent + "    ", depth + 1)
        return lines
    if isinstance(obj, list | tuple):
        lines = [f"{indent}{type(obj).__name__} of {len(obj)}"]
        if obj and depth < MAX_DEPTH:
            lines += _describe(obj[0], indent + "  first: ", depth + 1)
        return lines
    if isinstance(obj, str | int | float | bool | type(None)):
        return [f"{indent}{type(obj).__name__} = {obj!r}"]
    lines = [f"{indent}{type(obj).__module__}.{type(obj).__name__}"]
    attrs = getattr(obj, "__dict__", None)
    if isinstance(attrs, dict) and depth < MAX_DEPTH:
        for key in list(attrs)[:MAX_ITEMS]:
            lines.append(f"{indent}  .{key}")
            lines += _describe(attrs[key], indent + "    ", depth + 1)
    return lines


def describe_npy(path: Path, *, allow_pickle: bool) -> list[str]:
    head = f"{path.name}:"
    try:
        data = np.load(path, allow_pickle=False)
    except ValueError:
        # Object arrays need pickle.
        if not allow_pickle:
            return [head, "  contains pickled objects; not opened (re-run with --allow-pickle)"]
        try:
            data = np.load(path, allow_pickle=True)
        except Exception as exc:
            return [head, f"  cannot read: {exc}"]
    except Exception as exc:
        return [head, f"  cannot read: {exc}"]
    if isinstance(data, np.ndarray) and data.dtype == object and data.shape == ():
        data = data.item()
    return [head, *_describe(data, "  ", 0)]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=Path)
    parser.add_argument("--allow-pickle", action="store_true", help="open pickled objects (unsafe)")
    args = parser.parse_args(argv)

    if not args.folder.is_dir():
        print(f"not a folder: {args.folder}", file=sys.stderr)
        return 2

    print(f"python {platform.python_version()}  numpy {np.__version__}  {platform.platform()}")
    print(f"\n== files in {args.folder} ==")
    print("\n".join(file_tree(args.folder)))
    print("\n== .npy contents ==")
    for path in sorted(args.folder.rglob("*.npy")):
        print("\n".join(describe_npy(path, allow_pickle=args.allow_pickle)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

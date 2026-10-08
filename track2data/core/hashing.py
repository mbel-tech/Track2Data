"""SHA-256 helpers used by the manifest and export layers."""

from __future__ import annotations

import hashlib
from pathlib import Path


def file_sha256(path: Path, chunk_size: int = 65536) -> str:
    """Return hex SHA-256 of a file's contents."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def dict_sha256(data: dict) -> str:
    """Return hex SHA-256 of a JSON-serialised dict (keys sorted)."""
    import json
    serialised = json.dumps(data, sort_keys=True, default=str).encode()
    return hashlib.sha256(serialised).hexdigest()


def folder_fingerprint(folder: Path) -> str:
    """Cheap change-detector for a session folder: SHA-256 over every file's
    relative path, size and mtime (nanoseconds). Not content-addressed -- a
    multi-gigabyte session cannot be read just to decide whether to read it --
    but any edit, add or removal changes it."""
    h = hashlib.sha256()
    folder = Path(folder)
    if folder.is_file():
        # A format that writes one file per session (DeepLabCut, SLEAP, ...) puts the file here.
        # Without this a file would hash to nothing: every such session would share one cache
        # entry, and editing the file would never refresh it.
        st = folder.stat()
        h.update(f"{folder.name}|{st.st_size}|{st.st_mtime_ns}\n".encode())
        return h.hexdigest()
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        st = path.stat()
        h.update(f"{path.relative_to(folder).as_posix()}|{st.st_size}|{st.st_mtime_ns}\n".encode())
    return h.hexdigest()

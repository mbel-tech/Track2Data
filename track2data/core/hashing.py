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

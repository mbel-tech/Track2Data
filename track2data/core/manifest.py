"""Project manifest read/write and schema migration."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from track2data.core.models import ProjectManifest


def read(path: Path) -> ProjectManifest:
    """Load a manifest from a JSON file."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return ProjectManifest.model_validate(data)


def write(manifest: ProjectManifest, path: Path) -> None:
    """Replace the manifest atomically, preserving the old file on failure."""
    path = Path(path)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.",
            suffix=".tmp", delete=False,
        ) as fh:
            temporary = Path(fh.name)
            fh.write(manifest.model_dump_json(indent=2))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

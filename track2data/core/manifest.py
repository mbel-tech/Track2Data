"""Project manifest read/write and schema migration."""

from __future__ import annotations

import json
from pathlib import Path

from track2data.core.models import ProjectManifest


def read(path: Path) -> ProjectManifest:
    """Load a manifest from a JSON file."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return ProjectManifest.model_validate(data)


def write(manifest: ProjectManifest, path: Path) -> None:
    """Serialise *manifest* to *path* as JSON."""
    Path(path).write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )

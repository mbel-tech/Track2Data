"""
Loader for idtracker.ai trajectory dicts stored as pickled NPY files.

Security note: allow_pickle=True enables arbitrary code execution from
untrusted files.  The GUI/CLI layers enforce a per-project consent gate
(security.allow_pickle_trajectories in the project manifest) before calling
this loader.  The programmatic API loads without prompting because the caller
owns the files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from track2data.core.errors import DataValidationError, ImportError_


def load_npy(path: Path) -> dict[str, Any]:
    """
    Load a pickled trajectory NPY file and return the raw dict.

    The returned dict contains the idtracker.ai trajectory keys exactly as
    stored — including id_probabilities with shape (N, M, 1) when that is
    what the file contains.  The Normaliser is responsible for squeezing
    and reshaping.

    Raises
    ------
    ImportError_
        When the file does not exist or cannot be read.
    DataValidationError
        When the file loads successfully but is not a dict (e.g. a raw array).
    """
    path = Path(path)
    if not path.exists():
        raise ImportError_(
            f"Trajectory file not found: {path}",
            code="IDT_NO_TRAJ",
            severity="error",
            subject=str(path),
            remediation="Ensure the session folder contains trajectories/trajectories.npy",
        )

    try:
        raw = np.load(path, allow_pickle=True)
        payload = raw.item() if raw.ndim == 0 else raw
    except Exception as exc:
        raise ImportError_(
            f"Cannot load trajectory file: {exc}",
            code="IDT_NO_TRAJ",
            severity="error",
            subject=str(path),
            remediation="Check that the file is a valid pickled numpy trajectory dict.",
        ) from exc

    if not isinstance(payload, dict):
        raise DataValidationError(
            f"Expected a dict inside {path.name}, got {type(payload).__name__}",
            code="IDT_FORMAT_AMBIGUOUS",
            severity="error",
            subject=str(path),
            remediation=(
                "The trajectory NPY file must contain a pickled dict "
                "(idtracker.ai 6.x format), not a raw array."
            ),
        )

    return payload

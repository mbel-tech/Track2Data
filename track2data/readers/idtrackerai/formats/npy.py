"""
Loader for idtracker.ai trajectory dicts stored as pickled NPY files.

Security: ``np.load(..., allow_pickle=True)`` executes arbitrary code from
the file, so this loader refuses unless the caller passes
``allow_pickle=True`` explicitly -- the same shape of gate ``blobs.py``
uses, and for the same reason.

The gate is a real one now. This module's docstring previously *claimed*
that the GUI/CLI enforced a per-project consent check before calling it,
while the call below ran unconditionally: no such check existed anywhere
(see docs/IDTRACKERAI_FORMAT_ANALYSIS.md). Since ``npy`` is one of
idtracker.ai's default trajectory output formats, that path was reached by
importing an ordinary session folder, which made any shared, downloaded or
collaborator-supplied folder an execution vector.

Refusal raises ``IDT_PICKLE_REFUSED`` rather than returning None, so the
reader's format-fallback walk treats it like any other unreadable format
and moves on to h5/csv when the folder has them. A pickle-only folder
surfaces the refusal to the user, who can then opt in for that project.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from track2data.core.errors import DataValidationError, ImportError_


def load_npy(path: Path, *, allow_pickle: bool = False) -> dict[str, Any]:
    """
    Load a pickled trajectory NPY file and return the raw dict.

    The returned dict contains the idtracker.ai trajectory keys exactly as
    stored — including id_probabilities with shape (N, M, 1) when that is
    what the file contains.  The Normaliser is responsible for squeezing
    and reshaping.

    Parameters
    ----------
    path:
        The ``trajectories.npy`` to load.
    allow_pickle:
        Must be explicitly True. Defaults to False so that no caller loads
        executable content by accident; see the module docstring.

    Raises
    ------
    ImportError_
        When the file does not exist, cannot be read, or unpickling was not
        permitted (``IDT_PICKLE_REFUSED``).
    DataValidationError
        When the file loads successfully but is not a dict (e.g. a raw array).
    """
    path = Path(path)
    if not allow_pickle:
        raise ImportError_(
            f"Refusing to unpickle {path.name}: loading it would execute code "
            "from the file.",
            code="IDT_PICKLE_REFUSED",
            severity="error",
            subject=str(path),
            remediation=(
                "Enable security.allow_pickle_trajectories for this project "
                "only if you trust the source of this session folder, or "
                "re-export it in a non-executable format: "
                "`idtrackerai_format <session> --formats h5`."
            ),
        )
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

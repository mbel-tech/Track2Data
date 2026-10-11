"""
Loader for the idtracker.ai trajectories_csv/ bundle.

Bundle layout (from the real-data corpus and official docs):
    trajectories_csv/
    ├── trajectories.csv        frame, x_1, y_1, x_2, y_2, …
    ├── id_probabilities.csv    frame, prob_1, prob_2, …
    ├── areas.csv               frame, area_1, area_2, …  (optional)
    └── attributes.json         subset of the trajectory dict (strict JSON)

Returns a dict with the same keys as the pickled NPY loader so that the
Normaliser can process both formats identically.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from track2data.core.errors import ImportError_


def _shape_error(message: str, subject: str) -> ImportError_:
    return ImportError_(
        message,
        code="IDT_SHAPE_MISMATCH",
        severity="error",
        subject=subject,
        remediation="Re-export the session, or check that trajectories.csv and "
        "id_probabilities.csv come from the same run.",
    )


def load_csv_bundle(csv_dir: Path) -> dict[str, Any]:
    """
    Read the trajectories_csv/ directory and return a normaliser-ready dict.

    Raises
    ------
    ImportError_
        When *csv_dir* does not exist or required CSVs are missing.
    """
    csv_dir = Path(csv_dir)
    if not csv_dir.is_dir():
        raise ImportError_(
            f"CSV bundle directory not found: {csv_dir}",
            code="IDT_NO_TRAJ",
            severity="error",
            subject=str(csv_dir),
            remediation="Ensure trajectories/trajectories_csv/ exists in the session folder.",
        )

    traj_csv = csv_dir / "trajectories.csv"
    if not traj_csv.exists():
        raise ImportError_(
            f"trajectories.csv missing from {csv_dir}",
            code="IDT_NO_TRAJ",
            severity="error",
            subject=str(traj_csv),
            remediation="The CSV bundle must contain at least trajectories.csv.",
        )

    # Load trajectories: x_1, y_1, x_2, y_2, ... with an optional leading time column.
    # idtracker.ai omits that column when it could not read the video's frame rate, so the
    # column count decides: 2k columns are k animals, 2k+1 carry a leading time/frame column.
    traj_data = np.genfromtxt(traj_csv, delimiter=",", skip_header=1)
    if traj_data.ndim == 1:
        traj_data = traj_data.reshape(1, -1)
    n_frames, n_cols = traj_data.shape
    xy_cols = traj_data[:, 1:] if n_cols % 2 == 1 else traj_data
    if xy_cols.shape[1] == 0:
        raise _shape_error(f"{traj_csv.name} holds no coordinate columns.", str(traj_csv))
    n_animals = xy_cols.shape[1] // 2
    # Reshape (N, M*2) -> (N, M, 2)
    trajectories = xy_cols.reshape(n_frames, n_animals, 2)

    payload: dict[str, Any] = {"trajectories": trajectories}

    # id_probabilities.csv: one column per animal, same optional leading time column.
    prob_csv = csv_dir / "id_probabilities.csv"
    if prob_csv.exists():
        prob_data = np.genfromtxt(prob_csv, delimiter=",", skip_header=1)
        if prob_data.ndim == 1:
            prob_data = prob_data.reshape(1, -1)
        if prob_data.shape[1] == n_animals + 1:
            prob_data = prob_data[:, 1:]
        if prob_data.shape != (n_frames, n_animals):
            raise _shape_error(
                f"{prob_csv.name} has shape {prob_data.shape} but {traj_csv.name} holds "
                f"{n_frames} frames of {n_animals} animals.",
                str(prob_csv),
            )
        payload["id_probabilities"] = prob_data

    # attributes.json — merge into payload (provides version, fps, etc.)
    attr_file = csv_dir / "attributes.json"
    if attr_file.exists():
        try:
            attrs = json.loads(attr_file.read_text(encoding="utf-8"))
            if isinstance(attrs, dict):
                for k, v in attrs.items():
                    if k not in payload:
                        payload[k] = v
        except Exception:
            pass  # attributes.json is optional; silently skip on parse error

    return payload

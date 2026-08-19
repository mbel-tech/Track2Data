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

    # Load trajectories: first column = frame index, remaining = x_1, y_1, x_2, y_2, …
    traj_data = np.genfromtxt(traj_csv, delimiter=",", skip_header=1)
    if traj_data.ndim == 1:
        traj_data = traj_data.reshape(1, -1)
    n_frames = traj_data.shape[0]
    xy_cols = traj_data[:, 1:]  # drop frame column
    # Reshape (N, M*2) → (N, M, 2)
    n_coord_cols = xy_cols.shape[1]
    n_animals = n_coord_cols // 2
    trajectories = xy_cols.reshape(n_frames, n_animals, 2)

    payload: dict[str, Any] = {"trajectories": trajectories}

    # id_probabilities.csv
    prob_csv = csv_dir / "id_probabilities.csv"
    if prob_csv.exists():
        prob_data = np.genfromtxt(prob_csv, delimiter=",", skip_header=1)
        if prob_data.ndim == 1:
            prob_data = prob_data.reshape(1, -1)
        payload["id_probabilities"] = prob_data[:, 1:]  # drop frame column → (N, M)

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

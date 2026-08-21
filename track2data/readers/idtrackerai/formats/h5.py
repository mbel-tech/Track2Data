"""
Loader for idtracker.ai trajectory dicts stored as HDF5 (trajectories.h5).

This is idtracker.ai's own default format (``trajectories_formats`` defaults
to ``['h5', 'npy', 'csv']`` -- session_idtrackerai.md:73) and is what every
unmodified 6.x session ships. No pickle involved.

Schema (verified empirically against the 70-session real corpus, since the
official docs show only a usage snippet -- output_structure_idtrackerai.md:130-137
-- not a field-by-field layout):

    /trajectories          Dataset  (n_frames, n_animals, 2)   float64
    /id_probabilities      Dataset  (n_frames, n_animals, 1)   float64
    /areas                 Group    {mean, median, std} each (n_animals,)
    /identities_groups     Group    dict-shaped; empty group when {} (all 70
                                     corpus sessions have exclusive_rois=False)
    /setup_points          Group    dict-shaped; empty group when {}
    attrs: version, height, width, frames_per_second, body_length,
           estimated_accuracy (optional), fraction_identified,
           silhouette_score (optional), fragment_connectivity (optional),
           identities_labels, length_unit, video_paths

Two attrs schemas were observed in the corpus -- estimated_accuracy,
silhouette_score and fragment_connectivity are sometimes absent -- so every
attr read here is optional.

``length_unit`` ships as the sentinel ``-1`` when uncalibrated (not absent,
not NaN). The existing Normaliser._normalise_length_unit already treats any
value <= 0 as "not calibrated", so no special-casing is needed here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from track2data.core.errors import DataValidationError, ImportError_


def _group_to_dict(group: Any) -> dict[str, Any]:
    """Recursively turn an h5py Group into a plain dict of arrays/dicts.

    idtracker.ai stores dict-valued trajectory keys (``areas``,
    ``identities_groups``, ``setup_points``) as nested Groups rather than
    JSON blobs. An empty Group round-trips to ``{}``, matching what the npy
    loader would hand the Normaliser for an empty dict.
    """
    import h5py

    out: dict[str, Any] = {}
    for key in group:
        item = group[key]
        if isinstance(item, h5py.Group):
            out[key] = _group_to_dict(item)
        else:
            out[key] = item[()] if item.shape == () else item[:]
    return out


def _coerce_attr(value: Any) -> Any:
    """Normalise an h5py attribute value to a plain Python/numpy value.

    h5py returns object-dtype numpy arrays for string lists (e.g.
    ``identities_labels``, ``video_paths``); the rest of the reader expects
    plain Python lists for those.
    """
    if isinstance(value, np.ndarray) and value.dtype == object:
        return [str(v) for v in value.tolist()]
    return value


def load_h5(path: Path) -> dict[str, Any]:
    """
    Read an idtracker.ai ``trajectories.h5`` file and return a
    normaliser-ready dict with the same keys the pickled-NPY loader produces.

    Raises
    ------
    ImportError_
        When *path* does not exist.
    DataValidationError
        When the file has no ``trajectories`` dataset.
    """
    import h5py

    path = Path(path)
    if not path.exists():
        raise ImportError_(
            f"trajectories.h5 not found: {path}",
            code="IDT_NO_TRAJ",
            severity="error",
            subject=str(path),
            remediation="Ensure trajectories/trajectories.h5 exists in the session folder.",
        )

    payload: dict[str, Any] = {}
    with h5py.File(path, "r") as f:
        if "trajectories" not in f:
            raise DataValidationError(
                f"trajectories.h5 at {path} has no 'trajectories' dataset.",
                code="IDT_DICT_MISSING_KEY",
                severity="error",
                subject=str(path),
                remediation="Re-export the session or use a different trajectory format.",
            )

        for key in f:
            item = f[key]
            if isinstance(item, h5py.Group):
                payload[key] = _group_to_dict(item)
            else:
                payload[key] = item[:]

        for key in f.attrs:
            payload[key] = _coerce_attr(f.attrs[key])

    return payload

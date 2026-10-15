"""A preprocessed session as a ``movement``-style ``xarray.Dataset``.

`movement <https://movement.neuroinformatics.dev/>`_ centres on a Dataset whose ``position``
variable has dimensions ``(time, individuals, keypoints, space)``. This builds that from a
:class:`~track2data.core.models.PreprocessedSession`, so its plotting, filtering and kinematics
can be used on Track2Data's cleaned positions. ``xarray`` is imported inside the function (extra:
``pip install track2data[xarray]``); ``movement`` itself is not needed to build the Dataset.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from track2data.core.errors import ImportError_

if TYPE_CHECKING:
    import xarray

    from track2data.core.models import PreprocessedSession


def to_movement_dataset(
    psess: PreprocessedSession, *, include_separator_rows: bool = False
) -> xarray.Dataset:
    """Return *psess* as an ``xarray.Dataset`` with ``position`` ``(time, individuals, keypoints,
    space)``.

    * ``time`` is each row's true video frame divided by the frame rate (``psess.timeline()``),
      so a session tracked in separate intervals keeps its gaps instead of being renumbered.
    * Separator rows (the single NaN row that stands for an unfilled gap) are dropped unless
      *include_separator_rows*. Rows inserted for unobserved video stay as NaN.
    * ``keypoints`` is the one keypoint that stands for the animal, else ``["centroid"]``;
      ``space`` is ``["x", "y"]``, plus ``"z"`` for a native 3-D session.
    * The tracker's identity probability is the separate variable ``identity_confidence``. It is
      deliberately not called ``confidence``: that is a pose estimator's confidence in *where* a
      keypoint is, and identity probability is about *which animal* it is.
    * ``attrs`` hold ``fps``, ``source_software``, ``reader_verification``, ``length_unit`` (the
      unit of ``position``: ``"px"`` for a pixel session, the file's unit for a native 3-D one)
      and ``px_per_cm`` (NaN when not calibrated).
    """
    try:
        import xarray as xr
    except ImportError as exc:
        raise ImportError_(
            "Building a movement Dataset needs the optional 'xarray' package.",
            code="XARRAY_MISSING",
            remediation="Install it with: pip install track2data[xarray]",
        ) from exc

    session = psess.session
    n_animals = psess.n_animals
    frames, _verified = psess.timeline()
    keep = np.ones(psess.n_frames, dtype=bool)
    if not include_separator_rows and psess.separator_mask is not None:
        keep = ~psess.separator_mask

    xy = psess.xy[keep]
    space = ["x", "y"]
    if psess.z is not None:
        xy = np.concatenate([xy, psess.z[keep][..., None]], axis=-1)
        space.append("z")

    labels = session.identities_labels
    if labels is None or len(labels) != n_animals:
        labels = [str(k) for k in range(n_animals)]
    keypoint = session.keypoints.selection.keypoint if session.keypoints is not None else "centroid"

    data_vars: dict[str, tuple[tuple[str, ...], np.ndarray]] = {
        "position": (("time", "individuals", "keypoints", "space"), xy[:, :, None, :]),
    }
    probabilities = psess.id_probabilities_aligned
    if probabilities is not None and probabilities.shape[0] == psess.n_frames:
        data_vars["identity_confidence"] = (("time", "individuals"), probabilities[keep])

    from track2data.readers import find_reader

    reader_cls = find_reader(session.reader)
    native = not session.has_pixel_frame
    return xr.Dataset(
        data_vars,
        coords={
            "time": np.asarray(frames, dtype=float)[keep] / psess.fps,
            "individuals": labels,
            "keypoints": [keypoint],
            "space": space,
        },
        attrs={
            "fps": psess.fps,
            "source_software": (reader_cls.display_name or reader_cls.name)
            if reader_cls
            else session.reader,
            "reader_verification": reader_cls.verification if reader_cls else "unknown",
            "length_unit": (session.coordinate_unit or "") if native else "px",
            "px_per_cm": float("nan") if psess.px_per_cm is None else float(psess.px_per_cm),
        },
    )

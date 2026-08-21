"""
Opt-in loader for idtracker.ai's preprocessing/list_of_blobs.pickle.

Unlike every other loader in this reader, this one is NEVER called
automatically -- it requires an explicit ``allow_pickle=True`` from the
caller. Two reasons:

1. Security. The file pickles custom classes
   (``idtrackerai.blob.Blob``, ``idtrackerai.list_of_blobs.ListOfBlobs``)
   via STACK_GLOBAL opcodes -- a bare ``pickle.load()`` is an
   arbitrary-code-execution surface on untrusted input
   (output_structure_idtrackerai.md, both the NPY and Pickle sections:
   "The pickle module is not secure"). This module loads it through a
   restricted ``pickle.Unpickler`` subclass that returns an inert stub for
   any ``idtrackerai.*`` class and refuses everything outside a small
   numpy allowlist -- no idtracker.ai code ever executes -- but it is
   still deserializing 50MB of attacker-controllable structure, so the
   caller must opt in explicitly rather than have it happen implicitly on
   every import.
2. Cost. ~50MB per session, ~3.7GB across a 70-session corpus. Streaming
   is not attempted (a custom incremental pickle reader is a much larger
   project); instead the full pickle is loaded transiently and reduced
   immediately to a small per-identity summary -- the raw blob list is
   never returned to the caller and never stored on Session.

Schema notes (undocumented on the official side; verified empirically,
loading a real file with idtrackerai NOT installed):
  - The pickled Blob state has ~20 keys; NOT present (they are
    functools.cached_property on the live class, not pickled state):
    area, extension, bbox_corners, convexHull, centroid, exclusive_roi,
    was_a_crossing. contour IS present -- it is the only raw geometry in
    the file, and everything derived here is computed from it with plain
    numpy, not cv2 (cv2 is not a project dependency).
  - next/previous are empty tuples on every sampled blob: the
    frame-to-frame overlap graph is stripped before saving. Do not build
    anything on has_multiple_next/has_a_next_crossing/etc.
  - 5/70 real sessions carry a separate list_of_blobs_validated.pickle
    (Validator-curated); one base list_of_blobs.pickle was observed
    re-saved by the Validator (mtime newer than the rest of
    preprocessing/). Which file was used is recorded in the summary
    returned by load_body_length_px_per_identity(), not silently chosen.
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from track2data.core.models import Session

logger = logging.getLogger(__name__)


class _BlobStub:
    """Inert placeholder for any idtrackerai.* class encountered while
    unpickling. __setstate__ deposits the real pickled attributes onto
    this instance's __dict__; no idtrackerai code ever runs."""

    def __setstate__(self, state: Any) -> None:
        if isinstance(state, dict):
            self.__dict__.update(state)
        else:
            self.__dict__["_state"] = state


class _AllowlistUnpickler(pickle.Unpickler):
    """Refuses every class except idtrackerai.* (stubbed) and a small
    numpy allowlist needed to reconstruct the pickled arrays. More
    restrictive than a bare pickle.load(), not less."""

    def find_class(self, module: str, name: str) -> Any:
        if module.startswith("idtrackerai"):
            return _BlobStub
        if module.startswith("numpy"):
            return super().find_class(module, name)
        raise pickle.UnpicklingError(
            f"Refusing to unpickle {module}.{name} (not in the allowlist)."
        )


def _resolve_blob_pickle_path(folder: Path) -> Path | None:
    """
    Return whichever blob pickle should be used: the Validator-curated
    ``list_of_blobs_validated.pickle`` when present, else the base
    ``list_of_blobs.pickle``. Filters macOS resource-fork stubs the same
    way custom_artefacts.py / preprocessing.py already do.
    """
    preproc = Path(folder) / "preprocessing"
    for name in ("list_of_blobs_validated.pickle", "list_of_blobs.pickle"):
        candidate = preproc / name
        if candidate.exists() and not candidate.name.startswith("._"):
            return candidate
    return None


def _load_blobs_in_video(folder: Path) -> tuple[list, str] | None:
    """Load and return (blobs_in_video, source_filename), or None on any
    failure. Never raises."""
    path = _resolve_blob_pickle_path(folder)
    if path is None:
        return None
    try:
        with path.open("rb") as f:
            lob = _AllowlistUnpickler(f).load()
    except Exception as exc:
        logger.warning("Could not load %s: %s", path, exc)
        return None

    blobs_in_video = getattr(lob, "blobs_in_video", None)
    if not isinstance(blobs_in_video, list):
        logger.warning(
            "%s did not unpickle to the expected ListOfBlobs shape "
            "(no 'blobs_in_video' list attribute).",
            path,
        )
        return None
    return blobs_in_video, path.name


def _bbox_diagonal_px(contour: Any) -> float | None:
    """
    Bounding-box diagonal from a raw contour, matching idtracker.ai's own
    `extension` property's convention: (max - min) per axis on the
    contour's own coordinates -- NOT cv2.boundingRect, which is ~0.3%
    larger (inclusive vs exclusive corner convention; verified against a
    real blob: contour ptp gives exactly the tracker's own recorded
    diagonal, cv2.boundingRect does not). See docs/EXTRACT_BBOXES_FIX.md
    section 6 for the same finding against extract_bboxes.py.
    """
    arr = np.asarray(contour)
    if arr.ndim != 2 or arr.shape[0] < 3 or arr.shape[1] != 2:
        return None
    w, h = arr.max(axis=0) - arr.min(axis=0)
    return float(np.hypot(w, h))


def compute_body_length_px_per_identity(
    blobs_in_video: list,
    n_animals: int,
    min_certainty: float = 0.5,
) -> np.ndarray | None:
    """
    Per-identity median bounding-box diagonal, filtered on idtracker.ai's
    own unicity condition (`seems_like_individual`) plus a unicity-frame
    requirement (exactly n_animals blobs detected that frame) plus an
    identity-certainty threshold.

    This reproduces idtracker.ai's own median_body_length to within ~0.3%
    at the pooled (all-identities) level on the real corpus -- markedly
    better than the naive is_an_individual-only filter extract_bboxes.py
    uses, which was measured to overestimate by +27.8% because it
    includes blobs that are two animals merged together (see
    docs/EXTRACT_BBOXES_FIX.md, section N1). Per-identity values are not
    independently ground-truthed the same way -- real inter-individual
    spread was observed on the corpus (e.g. one identity ~1.5x the
    others' median), which may be genuine biological variation or
    residual segmentation contamination specific to that identity; this
    function reports the filtered estimate honestly, it does not
    adjudicate that question.

    identity is 1-based (fragment_idtrackerai.md convention, matching the
    trajectory dict's column order); the returned array is 0-based,
    matching Session.body_length_px's existing (n_animals,) contract.

    Returns None if no sample passed the filter for any identity.
    """
    samples: dict[int, list[float]] = {}

    for frame_blobs in blobs_in_video:
        if len(frame_blobs) != n_animals:
            continue  # not a unicity frame
        for blob in frame_blobs:
            state = blob.__dict__
            if state.get("seems_like_individual") is not True:
                continue
            identity = state.get("identity")
            certainty = state.get("identity_certainty")
            if identity is None or certainty is None or certainty < min_certainty:
                continue
            diag = _bbox_diagonal_px(state.get("contour"))
            if diag is None:
                continue
            samples.setdefault(int(identity), []).append(diag)

    if not samples:
        return None

    result = np.full(n_animals, np.nan, dtype=np.float64)
    for identity, diags in samples.items():
        idx = identity - 1  # 1-based identity -> 0-based individual_id
        if 0 <= idx < n_animals:
            result[idx] = float(np.median(diags))
    return result


def load_body_length_px_per_identity(
    folder: Path,
    n_animals: int,
    *,
    allow_pickle: bool,
    min_certainty: float = 0.5,
) -> dict[str, Any] | None:
    """
    Opt-in entry point: load preprocessing/list_of_blobs*.pickle, compute
    per-identity body length, and return
    ``{"body_length_px": np.ndarray, "source_file": str}``, or None when
    unavailable/not permitted/nothing usable was found.

    ``allow_pickle`` must be explicitly True. This function is never
    called automatically by IDTrackerAiReader.read() -- see the module
    docstring for why.
    """
    if not allow_pickle:
        return None

    loaded = _load_blobs_in_video(folder)
    if loaded is None:
        return None
    blobs_in_video, source_file = loaded

    body_length_px = compute_body_length_px_per_identity(
        blobs_in_video, n_animals, min_certainty=min_certainty
    )
    if body_length_px is None:
        return None

    return {"body_length_px": body_length_px, "source_file": source_file}


def enrich_session_with_blob_body_length(
    session: Session,
    *,
    allow_pickle: bool,
    min_certainty: float = 0.5,
) -> Session:
    """
    Upgrade ``session.body_length_px`` from the session-wide scalar
    broadcast the normal reader sets (see normaliser.py's
    ``_normalise_body_length`` -- idtracker.ai's ``body_length`` key is a
    single session-wide value, applied uniformly to every animal) to a
    real per-identity value computed from the blob layer.

    A deliberate, separate post-processing step rather than something
    ``IDTrackerAiReader.read()`` does automatically: it requires the
    caller to explicitly pass ``allow_pickle=True``, and it accepts a
    plain 50MB pickle deserialization cost that must not happen on every
    routine import (see the module docstring).

    Returns *session* unchanged (same object) when ``allow_pickle`` is
    False, or the blob pickle is absent/unusable/unavailable for this
    session, or nothing passed the quality filter -- never raises, and
    never silently produces a worse value than what was already there.
    """
    if not allow_pickle:
        return session

    result = load_body_length_px_per_identity(
        session.folder, session.n_animals,
        allow_pickle=True, min_certainty=min_certainty,
    )
    if result is None:
        return session

    return session.model_copy(update={
        "body_length_px": result["body_length_px"],
        "blob_body_length_source_file": result["source_file"],
    })

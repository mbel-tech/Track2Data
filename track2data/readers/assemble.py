"""Building blocks shared by readers of pose-style output (several keypoints per animal).

Track2Data's metrics use one position per animal. A pose tracker gives many, so a reader has to
choose, and the choice must be explicit and recorded: this module turns an ``(F, A, K, D)`` array
into the ``(F, A, 2)`` positions a ``Session`` needs, keeps the whole skeleton beside it
(``Session.keypoints``, stored only: no metric reads it), and validates the session a reader
assembles, because the ``Session`` model itself checks nothing.

Two rules are deliberate:

* The chosen position is a real keypoint, never a centroid of whichever keypoints happen to be
  visible. A centroid jumps whenever one keypoint drops out, and that jitter would read as speed.
* Missing is NaN. Infinity and any format-specific sentinel are mapped to NaN here, once, so no
  metric ever sees a ``0`` or ``-1`` that meant "not tracked".
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from track2data.core.errors import DataValidationError
from track2data.core.models import KeypointData, KeypointSelection, Session, VideoInfo

#: A skeleton larger than this is not kept unless the reader is told to (it is stored only).
SKELETON_MAX_BYTES = 256 * 1024 * 1024

_AXES = ("x", "y", "z")


def to_nan(values: Any, *sentinels: float) -> np.ndarray:
    """*values* as float64 with infinity, and every value in *sentinels*, replaced by NaN.

    Returns a copy; the input is never modified.
    """
    out = np.array(values, dtype=np.float64, copy=True)
    out[~np.isfinite(out)] = np.nan
    for sentinel in sentinels:
        out[out == sentinel] = np.nan
    return out


@dataclass(frozen=True)
class Reduction:
    """One position per animal, and the record of how it was chosen."""

    raw_xy: np.ndarray  # (F, A, 2) float64, NaN = missing
    selection: KeypointSelection
    coverage: dict[str, float]  # per keypoint, after the cutoff


def reduce_keypoints(
    xy: np.ndarray,
    names: list[str],
    confidence: np.ndarray | None = None,
    *,
    keypoint: str | None = None,
    cutoff: float | None = None,
    plane: tuple[int, int] = (0, 1),
) -> Reduction:
    """Reduce ``xy`` (F, A, K, D) to one keypoint per animal.

    *keypoint* names the one to use; without it the keypoint with the best coverage wins
    (coverage: the share of frames-and-animals that have a position after the cutoff), a tie going
    to the higher mean confidence and then to the first. *cutoff* drops positions whose confidence
    is below it (a missing confidence counts as below); it has no effect, and is recorded as
    ``None``, when there is no confidence to apply it to. *plane* picks the two axes that become
    ``raw_xy`` when the data is 3-D; the third is kept only in the stored skeleton.
    """
    xy = np.asarray(xy)
    if xy.ndim != 4 or xy.shape[3] < 2:
        raise ValueError(f"xy must be (frames, animals, keypoints, 2 or 3), got {xy.shape}")
    if len(names) != xy.shape[2]:
        raise ValueError(f"{len(names)} names for {xy.shape[2]} keypoints")
    if confidence is not None and np.shape(confidence) != xy.shape[:3]:
        raise ValueError("confidence must be (frames, animals, keypoints)")
    cutoff_used = cutoff if (cutoff is not None and confidence is not None) else None

    plane_xy = to_nan(xy[..., list(plane)])
    ok = np.isfinite(plane_xy).all(axis=-1)  # (F, A, K)
    if cutoff_used is not None:
        with np.errstate(invalid="ignore"):
            ok &= np.asarray(confidence, dtype=np.float64) >= cutoff_used
    coverage = ok.mean(axis=(0, 1))  # (K,)
    by_name = {name: float(c) for name, c in zip(names, coverage, strict=True)}

    if keypoint is not None:
        if keypoint not in names:
            raise DataValidationError(
                f"Keypoint {keypoint!r} is not in this file.",
                code="READER_OPTION_INVALID",
                subject="keypoint",
                remediation="Choose one of: " + ", ".join(names) + ".",
            )
        chosen, chosen_by = names.index(keypoint), "user"
    else:
        if not coverage.size or float(coverage.max()) <= 0.0:
            raise _no_positions(cutoff_used)
        best = np.flatnonzero(coverage == coverage.max())
        if len(best) > 1 and confidence is not None:
            conf = np.asarray(confidence, dtype=np.float64)
            means = np.array(
                [float(np.nanmean(np.where(ok[..., k], conf[..., k], np.nan))) for k in best]
            )
            best = best[means >= np.nanmax(means) - 1e-9]
        if len(best) > 1:
            best = best[[_most_central(plane_xy, ok, best)]]
        chosen = int(best[0])
        chosen_by = "coverage"
    if coverage[chosen] <= 0.0:
        raise _no_positions(cutoff_used)

    raw = plane_xy[:, :, chosen, :].copy()
    raw[~ok[:, :, chosen]] = np.nan
    selection = KeypointSelection(
        keypoint=names[chosen],
        cutoff=cutoff_used,
        chosen_by=chosen_by,  # type: ignore[arg-type]
        coverage=float(coverage[chosen]),
        plane=(_AXES[plane[0]], _AXES[plane[1]]),
    )
    return Reduction(raw_xy=raw, selection=selection, coverage=by_name)


def _most_central(plane_xy: np.ndarray, ok: np.ndarray, candidates: np.ndarray) -> int:
    """Which of *candidates* (indices) is, on average, nearest the middle of the animal's skeleton.

    The middle is the mean of the keypoints that have a position, frame by frame. It only ranks
    the candidates; the position that is used is always the chosen keypoint's own. Among equally
    covered keypoints the central one (a body or centre node) is the steadiest stand-in for the
    animal, where a head or a tail tip jitters. Returns the position within *candidates*; ties go
    to the first.
    """
    valid = np.where(ok[..., None], plane_xy, np.nan)  # (F, A, K, 2)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # frames where nothing is visible
        middle = np.nanmean(valid, axis=2, keepdims=True)  # (F, A, 1, 2)
        distance = np.linalg.norm(valid[:, :, candidates, :] - middle, axis=-1)  # (F, A, C)
        mean_distance = np.nanmean(distance, axis=(0, 1))
    return int(np.nanargmin(mean_distance))


def _no_positions(cutoff: float | None) -> DataValidationError:
    hint = (
        f"No position has a confidence of at least {cutoff}; lower the likelihood cutoff."
        if cutoff is not None
        else "The file holds no valid positions; check that it is the tracker's output."
    )
    return DataValidationError(
        "No keypoint has any usable position.",
        code="POSE_NO_POSITIONS",
        subject="keypoint",
        remediation=hint,
    )


def skeleton_fits(xy: np.ndarray, confidence: np.ndarray | None = None) -> bool:
    """Whether the full skeleton, stored as float32, stays within ``SKELETON_MAX_BYTES``."""
    size = int(np.prod(np.shape(xy), dtype=np.int64)) * 4
    if confidence is not None:
        size += int(np.prod(np.shape(confidence), dtype=np.int64)) * 4
    return size <= SKELETON_MAX_BYTES


def build_keypoints(
    xy: np.ndarray,
    names: list[str],
    confidence: np.ndarray | None,
    edges: list[tuple[int, int]],
    selection: KeypointSelection,
    *,
    keep: bool = True,
) -> KeypointData | None:
    """The full skeleton as stored data, or ``None`` when the reader declines to keep it."""
    if not keep:
        return None
    return KeypointData(
        xy=to_nan(xy).astype(np.float32),
        names=list(names),
        confidence=None if confidence is None else np.asarray(confidence, dtype=np.float32),
        edges=[(int(a), int(b)) for a, b in edges],
        selection=selection,
    )


def _invalid(subject: str, message: str, remediation: str) -> DataValidationError:
    return DataValidationError(
        message, code="READER_OUTPUT_INVALID", subject=subject, remediation=remediation
    )


def assemble_session(
    *,
    session_id: str,
    folder: Path,
    reader: str,
    fps: float,
    width_px: int,
    height_px: int,
    raw_xy: np.ndarray,
    has_stable_identities: bool,
    track_wo_identities: bool | None = None,
    trajectory_variant: str = "with_gaps",
    identities_labels: list[str] | None = None,
    tracking_intervals: list[tuple[int, int]] | None = None,
    keypoints: KeypointData | None = None,
    trajectory_source: Path | None = None,
    trajectory_format: str | None = None,
) -> Session:
    """A ``Session`` from a reader's arrays, after checking that they can be true.

    Raises ``DataValidationError`` (code ``READER_OUTPUT_INVALID``, ``subject`` naming the field)
    for a frame rate or frame size that cannot be real, positions of the wrong shape, or parts
    that disagree with each other.
    """
    if not (isinstance(fps, int | float) and math.isfinite(fps) and fps > 0):
        raise _invalid(
            "fps",
            f"Frame rate {fps!r} is not a positive number.",
            "Give the frame rate of the video.",
        )
    for name, value in (("width_px", width_px), ("height_px", height_px)):
        if not (isinstance(value, int | float) and math.isfinite(value) and value >= 1):
            raise _invalid(
                name,
                f"{name} {value!r} is not a positive size.",
                "Give the video's size in pixels.",
            )
    arr = np.asarray(raw_xy)
    if arr.ndim != 3 or arr.shape[2] != 2:
        raise _invalid(
            "raw_xy",
            f"Positions must be (frames, animals, 2), got shape {arr.shape}.",
            "This looks like the wrong kind of file for this reader.",
        )
    n_frames, n_animals = int(arr.shape[0]), int(arr.shape[1])
    if n_frames == 0 or n_animals == 0:
        raise _invalid(
            "raw_xy", "The file holds no frames or no animals.", "Check that it is complete."
        )
    if keypoints is not None and keypoints.xy.shape[:2] != (n_frames, n_animals):
        raise _invalid(
            "keypoints",
            "The stored skeleton does not match the positions.",
            "This is a bug in the reader; please report it.",
        )
    if identities_labels is not None and len(identities_labels) != n_animals:
        raise _invalid(
            "identities_labels",
            f"{len(identities_labels)} labels for {n_animals} animals.",
            "Give one label per animal.",
        )
    if tracking_intervals is not None:
        covered = sum(max(0, end - start) for start, end in tracking_intervals)
        if covered != n_frames:
            raise _invalid(
                "tracking_intervals",
                f"Tracking intervals cover {covered} frames but there are {n_frames}.",
                "Intervals are [start, end) and must add up to the number of frames.",
            )
    return Session(
        session_id=session_id,
        folder=Path(folder),
        reader=reader,
        video=VideoInfo(
            fps=float(fps), n_frames=n_frames, width_px=int(width_px), height_px=int(height_px)
        ),
        n_animals=n_animals,
        trajectory_variant=trajectory_variant,  # type: ignore[arg-type]
        has_stable_identities=has_stable_identities,
        track_wo_identities=track_wo_identities,
        raw_xy=to_nan(arr),
        identities_labels=None if identities_labels is None else list(identities_labels),
        tracking_intervals=None if tracking_intervals is None else list(tracking_intervals),
        keypoints=keypoints,
        trajectory_source=trajectory_source,
        trajectory_format=trajectory_format,
    )

"""What has to match across the sessions in a project, and what did not.

Every metric this tool computes is expressed in units that depend on facts
about the recording -- frame rate above all. Pooling sessions that disagree
on those facts produces systematically different numbers per group with
nothing in the output to say so. That is not a hypothetical: a camera or
acquisition-software change mid-study is a normal thing to happen, and
``fps`` reaches the numbers in at least four places:

* ``compute_kinematics`` scales speed and acceleration by it;
* ``JumpCfg`` thresholds are expressed per *frame*;
* ``SmoothCfg.window`` is a frame count -- 5 frames is 167 ms at 30 fps and
  83 ms at 60 fps, so the same setting smooths twice as hard at the lower
  rate;
* path length is a sum over inter-frame steps, so it is frame-rate
  dependent even for identical motion.

The same argument applies to calibration: a project where some sessions
carry a ``length_unit`` and others do not exports ``*_cm`` columns that are
real for some rows and NaN for others, with no column saying which.

These are reported as **warnings, not blocking errors**. Mixed-rate designs
are legitimate as long as the analyst knows and can model it -- the failure
this module exists to prevent is not knowing. The warnings are logged at run
time, written into each session's export README, and the underlying
per-session facts are emitted as ``sessions.csv`` so a downstream analyst
can filter or covary on them directly.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd

    from track2data.core.models import Session


@dataclass(frozen=True)
class SessionSummary:
    """Per-session facts that decide whether sessions are poolable.

    Deliberately small, frozen and picklable: one of these rides home on
    every ``SessionRunResult``, and a 70-session run must not pay for it.

    Everything here is re-derivable by re-reading the session folder, so --
    like ``ui.store.session_facts.SessionFacts``, the GUI's equivalent --
    none of it belongs in the persisted manifest.
    """

    session_id: str
    reader: str
    fps: float
    n_frames: int
    n_animals: int
    width_px: int
    height_px: int
    # idtracker.ai's own px-to-real-unit ratio; None means this session was
    # never calibrated in the Validator.
    length_unit: float | None
    # The project-wide calibration mode this session was run under.
    calibration_mode: str
    # The ratio actually used to produce *_cm columns, once the run has
    # resolved it. None means no calibrated columns were written for this
    # session -- which is the interesting case when other sessions have one.
    px_per_cm: float | None = None
    is_identity_free: bool = False
    # SHA-256 of the trajectory file that produced this session's numbers,
    # and its name. Empty/None when the hash was not computed -- pre-flight
    # reports skip it, since hashing every input is a full extra read of
    # every session and only the run itself needs the provenance record.
    trajectory_sha256: str = ""
    trajectory_source: str | None = None
    # What body length/area are *defined by* (idtracker.ai's segmentation
    # parameters) and what identity matching across sessions needs to agree
    # on (the identification CNN's input geometry). None = not recorded.
    segmentation_params: dict[str, Any] | None = None
    resolution_reduction: float | None = None
    id_image_size: tuple[int, ...] | None = None

    @property
    def duration_s(self) -> float:
        """Recording length in seconds, or NaN when fps is unusable."""
        if not self.fps or self.fps <= 0:
            return float("nan")
        return self.n_frames / self.fps

    @property
    def is_calibrated(self) -> bool:
        return self.px_per_cm is not None

    @classmethod
    def from_session(
        cls,
        session: Session,
        *,
        calibration_mode: str,
        is_identity_free: bool = False,
        px_per_cm: float | None = None,
        trajectory_sha256: str = "",
    ) -> SessionSummary:
        """Build from a freshly-read engine ``Session``."""
        source = session.trajectory_source
        return cls(
            session_id=session.session_id,
            reader=session.reader,
            fps=session.video.fps,
            n_frames=session.n_frames,
            n_animals=session.n_animals,
            width_px=session.video.width_px,
            height_px=session.video.height_px,
            length_unit=session.length_unit,
            calibration_mode=calibration_mode,
            px_per_cm=px_per_cm,
            is_identity_free=is_identity_free,
            trajectory_sha256=trajectory_sha256,
            trajectory_source=source.name if source is not None else None,
            segmentation_params=session.segmentation_params,
            resolution_reduction=session.resolution_reduction,
            id_image_size=(
                tuple(session.id_image_size) if session.id_image_size else None
            ),
        )


def _group_by(
    summaries: Sequence[SessionSummary], key: Any
) -> dict[Any, list[str]]:
    """Map each distinct value of *key* to the session ids carrying it."""
    groups: dict[Any, list[str]] = {}
    for summary in summaries:
        groups.setdefault(key(summary), []).append(summary.session_id)
    return groups


def _describe(groups: dict[Any, list[str]], *, limit: int = 4) -> str:
    """Render ``value (session, session, ...)`` clauses, naming the sessions.

    Named rather than counted: "3 sessions at 60 fps" tells the user a
    problem exists, "trial_07, trial_08, trial_09" tells them where.
    """
    parts = []
    for value, ids in sorted(groups.items(), key=lambda kv: str(kv[0])):
        shown = ", ".join(ids[:limit])
        if len(ids) > limit:
            shown += f", +{len(ids) - limit} more"
        parts.append(f"{value} ({shown})")
    return "; ".join(parts)


def heterogeneity_warnings(summaries: Sequence[SessionSummary]) -> list[str]:
    """Report every way the sessions in a project disagree with each other.

    Returns an empty list for a homogeneous project (and for a project with
    fewer than two sessions, where the question does not arise).

    Each warning names the consequence, not just the discrepancy: the point
    is to let someone decide whether to proceed, and that needs to be a
    judgement about their analysis rather than about a config field.
    """
    if len(summaries) < 2:
        return []

    warnings: list[str] = []

    fps_groups = _group_by(summaries, lambda s: s.fps)
    if len(fps_groups) > 1:
        warnings.append(
            "Sessions were recorded at different frame rates: "
            f"{_describe(fps_groups)}. Speed, acceleration and path length all "
            "scale with frame rate, jump thresholds are expressed per frame, "
            "and the smoothing window is a frame count -- so metric values are "
            "not directly comparable across these groups. Model frame rate as a "
            "covariate, or process each group separately."
        )

    n_animals_groups = _group_by(summaries, lambda s: s.n_animals)
    if len(n_animals_groups) > 1:
        warnings.append(
            "Sessions contain different numbers of animals: "
            f"{_describe(n_animals_groups)}. Group-level metrics (nearest-neighbour "
            "distance, inter-individual distance, convex hull area, polarisation) "
            "depend on group size by construction and are not comparable across "
            "these groups."
        )

    calibrated = [s.session_id for s in summaries if s.is_calibrated]
    uncalibrated = [s.session_id for s in summaries if not s.is_calibrated]
    if calibrated and uncalibrated:
        warnings.append(
            f"{len(calibrated)} session(s) are calibrated and {len(uncalibrated)} "
            f"are not ({_describe({'uncalibrated': uncalibrated})}). Every *_cm and "
            "*_bl column is a real measurement for the former and NaN for the "
            "latter, in the same exported table. Calibrate the remaining sessions, "
            "or analyse the pixel columns only."
        )

    mode_groups = _group_by(summaries, lambda s: s.calibration_mode)
    if len(mode_groups) > 1:
        warnings.append(
            "Sessions were calibrated by different methods: "
            f"{_describe(mode_groups)}. A body-length-relative measure and a "
            "centimetre measure are different quantities; do not pool them."
        )

    resolution_groups = _group_by(summaries, lambda s: (s.width_px, s.height_px))
    if len(resolution_groups) > 1:
        warnings.append(
            "Sessions were recorded at different video resolutions: "
            f"{_describe(resolution_groups)}. Pixel-unit metrics are not comparable "
            "across resolutions, and a ZoneSet drawn against one resolution does "
            "not describe the same physical region in another."
        )

    seg_groups = _group_by(summaries, _segmentation_key)
    if len(seg_groups) > 1:
        warnings.append(
            "Sessions were segmented with different idtracker.ai parameters: "
            f"{_describe(seg_groups)}. Body length and area are defined by "
            "these parameters (intensity/area thresholds, background "
            "subtraction, erosion), so body-length and area values -- and every "
            "*_bl column derived from them -- are not comparable across these "
            "groups."
        )

    id_groups = _group_by(summaries, _identification_key)
    if len(id_groups) > 1:
        warnings.append(
            "Sessions used different identification-image settings "
            f"(resolution_reduction / id_image_size): {_describe(id_groups)}. "
            "Identities are only matchable across sessions (e.g. with "
            "idmatcher.ai) when both agree."
        )

    return warnings


def _segmentation_key(s: SessionSummary) -> str:
    """Canonical, order-independent label for a session's segmentation params."""
    if not s.segmentation_params:
        return "not recorded"
    return ", ".join(f"{k}={v}" for k, v in sorted(s.segmentation_params.items()))


def _identification_key(s: SessionSummary) -> str:
    if s.resolution_reduction is None and s.id_image_size is None:
        return "not recorded"
    size = "x".join(str(v) for v in s.id_image_size) if s.id_image_size else "?"
    return f"reduction={s.resolution_reduction}, size={size}"


def sessions_table(
    summaries: Sequence[SessionSummary],
    errors: dict[str, str] | None = None,
) -> pd.DataFrame:
    """One row per session: the facts a downstream analyst needs to filter on.

    Written as ``sessions.csv`` at the root of a run's output directory. This
    is the machine-readable half of :func:`heterogeneity_warnings` -- the
    warnings say what is wrong, this says exactly which sessions to exclude
    or covary on.

    Parameters
    ----------
    summaries:
        One entry per session that got far enough to be summarised.
    errors:
        ``session_id -> error message`` for sessions that failed. A session
        that failed early enough to have no summary at all still gets a row,
        carrying its id and the error and nothing else -- otherwise a reader
        cannot tell "excluded because it broke" from "never in the project",
        and a silently shorter table reads as a smaller study.
    """
    import pandas as pd

    errors = errors or {}
    rows = [
        {
            "session_id": s.session_id,
            "reader": s.reader,
            "fps": s.fps,
            "n_frames": s.n_frames,
            "duration_s": s.duration_s,
            "n_animals": s.n_animals,
            "width_px": s.width_px,
            "height_px": s.height_px,
            "calibration_mode": s.calibration_mode,
            "length_unit": s.length_unit,
            "px_per_cm": s.px_per_cm,
            "is_calibrated": s.is_calibrated,
            "is_identity_free": s.is_identity_free,
            "trajectory_source": s.trajectory_source,
            "trajectory_sha256": s.trajectory_sha256 or None,
            "error": errors.get(s.session_id),
        }
        for s in summaries
    ]
    summarised = {s.session_id for s in summaries}
    rows.extend(
        {"session_id": session_id, "error": message}
        for session_id, message in errors.items()
        if session_id not in summarised
    )
    return pd.DataFrame(
        rows,
        columns=[
            "session_id", "reader", "fps", "n_frames", "duration_s", "n_animals",
            "width_px", "height_px", "calibration_mode", "length_unit",
            "px_per_cm", "is_calibrated", "is_identity_free",
            "trajectory_source", "trajectory_sha256", "error",
        ],
    )

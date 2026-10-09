"""
Core Pydantic data models.

Design notes
────────────
• Session holds numpy arrays (arbitrary_types_allowed=True).  It is
  never serialised to JSON directly; only ProjectManifest is.
• ProjectManifest is fully JSON-serialisable (no numpy).
• All config models use plain Python types and export cleanly via
  model_dump_json() / model_validate_json().
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

if TYPE_CHECKING:
    # Type-only: session_consistency imports Session from here, so a runtime
    # import would close the cycle. SessionRunResult is a plain dataclass, not
    # a pydantic model, so its annotations are never evaluated.
    from track2data.core.session_consistency import SessionSummary

# Imported from the module, not the package, to keep this import leaf-level:
# track2data/__init__.py re-exports __version__ from here too, and models.py
# is imported during that package init.
from track2data._version import __version__

# ── Video / Session ───────────────────────────────────────────────────────────


class VideoInfo(BaseModel):
    path: Path | None = None
    fps: float
    n_frames: int
    width_px: int
    height_px: int


class KeypointSelection(BaseModel):
    """Which keypoint stands for the animal in ``Session.raw_xy``, and how it was chosen."""

    keypoint: str
    #: Likelihood cutoff applied, or None when none was (or there was no likelihood to apply).
    cutoff: float | None = None
    #: "user" named it; "coverage" is the keypoint seen most often after the cutoff.
    chosen_by: Literal["user", "coverage"]
    #: Share of (frame, animal) cells that have a position for this keypoint after the cutoff.
    coverage: float
    #: The two axes that became ``raw_xy`` (the third, for 3-D data, is only in the skeleton).
    plane: tuple[str, str] = ("x", "y")


class KeypointData(BaseModel):
    """The full skeleton a pose tracker gave, kept beside the one position metrics use.

    Stored only: no metric reads it, so adding it cannot change a number. It is here so the
    export can say which keypoint was used, and so a later feature does not need the source files.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    #: (n_frames, n_animals, n_keypoints, 2 or 3), float32, NaN = missing.
    xy: np.ndarray
    names: list[str]
    #: (n_frames, n_animals, n_keypoints) float32 likelihood/score, or None.
    #: Never an identity probability: ``Session.id_probabilities`` is a different thing.
    confidence: np.ndarray | None = None
    #: Pairs of keypoint indices joined in the tracker's skeleton.
    edges: list[tuple[int, int]] = []
    selection: KeypointSelection

    def provenance(self) -> dict[str, Any]:
        """What the export records about the choice: the selection and how many keypoints."""
        return {**self.selection.model_dump(mode="json"), "n_keypoints": len(self.names)}

    @model_validator(mode="after")
    def _consistent(self) -> KeypointData:
        if self.xy.ndim != 4 or self.xy.shape[3] not in (2, 3):
            raise ValueError(
                f"xy must be (frames, animals, keypoints, 2 or 3), got {self.xy.shape}"
            )
        if len(self.names) != self.xy.shape[2]:
            raise ValueError(f"{len(self.names)} names for {self.xy.shape[2]} keypoints")
        if self.confidence is not None and self.confidence.shape != self.xy.shape[:3]:
            raise ValueError("confidence must be (frames, animals, keypoints)")
        k = self.xy.shape[2]
        for a, b in self.edges:
            if not (0 <= a < k and 0 <= b < k):
                raise ValueError(f"edge ({a}, {b}) names a keypoint that does not exist")
        return self


class Session(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    session_id: str
    folder: Path
    reader: str
    video: VideoInfo
    n_animals: int
    trajectory_variant: Literal["with_gaps", "wo_gaps"]
    has_stable_identities: bool
    # idtracker.ai's own --track_wo_identities declaration, verbatim
    # (idtracker.ai_usage.md: "Track the video without assigning
    # identities"). None when the source didn't report it -- a CSV bundle
    # without attributes.json, or a legacy v4 session.
    #
    # Deliberately kept separate from has_stable_identities, which is a
    # 3-way OR (this flag OR fraction_identified < 0.5 OR the NaN-coverage
    # fallback) and therefore cannot distinguish "identity-free by
    # construction" -- where the row index is just a per-frame detection
    # slot and no per-individual metric means anything -- from "identities
    # exist but are low quality". Only the former is grounds for refusing
    # to compute a metric; see Engine.compute_metrics.
    track_wo_identities: bool | None = None
    # Shape (n_frames, n_animals, 2), dtype float64, NaN = missing position.
    raw_xy: np.ndarray
    # Shape (n_animals,) in pixels; None when no body-length data is available.
    body_length_px: np.ndarray | None = None
    # Always False until the user explicitly acknowledges the segmentation-dependency caveat.
    body_length_reliable: bool = False

    # ── idtracker.ai reader fields ────────────────────────────────────────────
    # Shape (n_frames, n_animals), squeezed from (N, M, 1) when needed.
    id_probabilities: np.ndarray | None = None
    # Quality metrics: estimated_accuracy, fraction_identified, silhouette_score, etc.
    quality: dict[str, Any] | None = None
    # Px-to-real-unit ratio from the validator's length-calibration tool; None = not calibrated.
    length_unit: float | None = None
    identities_labels: list[str] | None = None
    # Hex colours ("#ff0000", ...) assigned per identity in the Validator
    # GUI, index-aligned with identities_labels / individual_id. Only in
    # session.json, not the trajectory dict -- see reader.py's session.json
    # enrichment. Lets an export match the colours a user already spent
    # time associating with each identity while validating.
    identities_colors: list[str] | None = None
    # idtracker.ai docs disagree on this type: session_idtrackerai.md:21 says dict
    # ("Named groups of identities... if exclusive ROI, saved here"); output_structure
    # says list. Real 6.x sessions ship a dict (verified: 70/70 in the GOT corpus).
    # Kept permissive on purpose -- do not narrow this back to list[str].
    identities_groups: dict[str, Any] | list[str] | None = None
    setup_points: dict[str, Any] | None = None
    # [[start, end], …] frame ranges that are valid; frames outside are not tracked.
    tracking_intervals: list[tuple[int, int]] | None = None
    # Parsed signed polygons from session.json roi_list.
    roi_list: list[dict[str, Any]] | None = None
    # Digest extracted from idtrackerai.log: status, per-stage durations, warnings.
    tracking_log: dict[str, Any] | None = None
    # Frame indices flagged as inconsistent by post-processing.
    inconsistent_frames: set[int] | None = None
    # Per-(frame, identity) bounding-box table (pd.DataFrame when present).
    bbox_table: Any | None = None
    bbox_summary: dict[str, Any] | None = None
    # Names of sessions matched by idmatcher.ai (v1.0: list-and-ignore).
    matching_results: list[str] | None = None
    idtrackerai_version: str | None = None
    trajectory_format: str | None = None
    # Verbatim unknown keys from the source trajectory dict.
    raw_attrs: dict[str, Any] | None = None

    # ── session.json fields (Fase 4) ────────────────────────────────────────
    # idtracker.ai's own authoritative count of frames with more blobs than
    # animals -- independent of any user-side inconsistent_frames.csv, and
    # the only place a `Check_segmentation is False` (silenced) session can
    # still surface segmentation contamination.
    number_of_error_frames: int | None = None
    # When True, identities are physically partitioned by ROI: every group
    # metric (nearest-neighbour distance, polarisation, cohesion, ...) is
    # meaningless across partitions, since those animals can never interact.
    exclusive_rois: bool | None = None
    # ISO timestamp of the last Validator manual-review pass, or None if the
    # session was never opened in the Validator.
    last_validated: str | None = None
    # Predicts which output folders survive (idtracker.ai_usage.md's
    # data_policy table) -- e.g. "trajectories" deletes preprocessing/,
    # identification_images/, and accumulation/.
    data_policy: str | None = None
    # [{"point_A": [x,y], "point_B": [x,y], "distance": float}, ...] -- the
    # raw pixel-endpoint pairs behind length_unit. Multiple entries give a
    # real uncertainty estimate on every calibrated metric (see
    # calibration/bodylength.py); length_unit alone is just their average.
    length_calibrations: list[dict[str, Any]] | None = None
    # Segmentation parameters that body_length/areas are *defined by*
    # (output_structure_idtrackerai.md:104): intensity_ths, area_ths,
    # use_bkg, background_subtraction_stat, erosion_kernel_size. Comparing
    # body length/area across sessions is only valid when these match --
    # kept as a single dict since they're always used together for that
    # one batch-consistency question, not individually.
    segmentation_params: dict[str, Any] | None = None
    # idtracker.ai's own outlier-displacement threshold (px/frame),
    # computed from the actual tracked data -- a better-grounded default
    # for jump detection than a hardcoded SD-multiple; see
    # preprocess/jump_detect.py's "idtracker_velocity_threshold" method.
    velocity_threshold_px_frame: float | None = None
    # resolution_reduction/id_image_size apply ONLY to the identification
    # CNN's input images (idtracker.ai_usage.md:370), never to trajectory
    # coordinates -- do NOT scale raw_xy by resolution_reduction. Recorded
    # for idmatcher.ai cross-session-matching provenance (both must match
    # across sessions for identity matching to be valid), not for use here.
    resolution_reduction: float | None = None
    id_image_size: list[int] | None = None
    # The trajectory file whose bytes produced raw_xy. Set by the reader,
    # which is the only layer that knows: it falls back through the formats
    # present in the folder, so the file actually read is not always the
    # highest-ranked one and cannot be re-derived afterwards. Hashed into the
    # export's provenance record -- "these bytes produced these numbers" is
    # not a checkable claim without it.
    trajectory_source: Path | None = None
    # Paths only, not decoded pixel data -- see
    # readers/idtrackerai/preprocessing.py's module docstring for why.
    roi_mask_path: Path | None = None
    background_image_path: Path | None = None
    # Parsed preprocessing/list_of_fragments.json -- see
    # readers/idtrackerai/fragments.py's module docstring for the schema
    # (undocumented on the official side; derived empirically) and the
    # defensive-parsing rules any consumer of session.fragments must follow.
    fragments: dict[str, Any] | None = None
    # Which preprocessing/list_of_blobs*.pickle produced body_length_px,
    # when it came from the opt-in blob-layer enrichment
    # (readers/idtrackerai/blobs.py) rather than the session-wide scalar
    # broadcast the normal reader sets. None when body_length_px is still
    # that broadcast (or absent). Recorded because 5/70 real sessions carry
    # a separate list_of_blobs_validated.pickle, and mixing curated and
    # uncurated sessions in one analysis without knowing which is which is
    # a reproducibility hazard.
    blob_body_length_source_file: str | None = None
    # Frame indices where idtracker.ai's own post-processing re-assigned an
    # identity (blob attribute ``identity_corrected_solving_jumps`` set).
    # Comes from the blob pickle, so it is None unless the project opted in
    # (ProjectManifest.blob_diagnostics) AND allowed pickle loading; None
    # means "not read", never "no corrections".
    tracker_corrected_frames: set[int] | None = None

    # ── pose readers ─────────────────────────────────────────────────────────
    # The whole skeleton, when the tracker gave one (DeepLabCut, SLEAP, ...). raw_xy is the one
    # keypoint named in keypoints.selection. Stored only; None for trackers with one point.
    keypoints: KeypointData | None = None

    @property
    def n_frames(self) -> int:
        return int(self.raw_xy.shape[0])

    def coverage(self) -> np.ndarray:
        """Fraction of non-NaN frames per animal, shape (n_animals,)."""
        valid = ~np.isnan(self.raw_xy[:, :, 0])  # (n_frames, n_animals)
        return valid.mean(axis=0)


# ── Preprocessing config ──────────────────────────────────────────────────────


class GapFillCfg(BaseModel):
    enabled: bool = True
    max_gap_frames: int = 30
    # A session stored as concatenated tracking intervals has stretches of video that were never
    # tracked between its rows. Off (the default, so existing projects do not change): those
    # stretches stay unfilled and every temporal step treats them as a break. On: a stretch of at
    # most ``max_cross_interval_gap_s`` seconds of missing video is rebuilt frame by frame as a
    # straight line between the animal's last and next observed positions. This is an
    # assumption, not a measurement, and is recorded as interpolated. It needs stable
    # identities (identity-free rows are detection slots, not animals) and an observed
    # position for that animal on both sides, and never extrapolates.
    across_tracking_intervals: bool = False
    max_cross_interval_gap_s: float = Field(default=30.0, gt=0)


class JumpCfg(BaseModel):
    enabled: bool = True
    # "idtracker_velocity_threshold" uses Session.velocity_threshold_px_frame
    # -- idtracker.ai's own outlier-displacement bound, computed from the
    # actual tracked data -- as an absolute px/frame threshold, instead of
    # the hardcoded SD-multiple/percentile heuristics below. Falls back to
    # sd_multiple (with a warning) when the session has no such value.
    method: Literal["sd_multiple", "percentile", "idtracker_velocity_threshold"] = (
        "sd_multiple"
    )
    sd_mult: float = 10.0
    percentile: float = 99.0
    pct_mult: float = 2.0
    replacement: Literal["nan", "linear_interp"] = "linear_interp"


class IdSwitchCfg(BaseModel):
    # Defaults to OFF. The corrector predicts each identity's next position
    # by constant velocity and reassigns against the observations at t+1,
    # propagating an accepted permutation to the end of the segment -- and,
    # when the session carries preprocessing/list_of_fragments.json, it only
    # evaluates idtracker.ai's own fragment boundaries, the only frames
    # where a swap is physically possible (see
    # docs_from_idtracker.ai/fragment_idtrackerai.md).
    #
    # It stays off by default because that last clause is conditional: a
    # session without fragment data falls back to scanning every frame, and
    # geometry alone cannot tell "these two animals crossed and were
    # relabelled" from "these two animals crossed". The earlier
    # implementation, which reasoned from within-frame conspecific proximity
    # and applied single-frame permutations, re-permuted 17.1% of a real
    # recording (session_trial10_Segment1) and injected ~640px teleports (a
    # stationary animal's path length inflated from 218px to 11,639px,
    # +5234%). That specific failure mode is fixed; enabling this on a
    # fragment-less session still warrants reviewing the output.
    enabled: bool = False
    # Margin by which a candidate permutation must beat the tracker's own
    # labelling before it is accepted. Ties (two animals at the same point
    # mid-crossing) are rejected, so a crossing alone never triggers a swap.
    tier1_ratio: float = 1.5
    tier2_hungarian: bool = True
    # Retained for manifest backward-compatibility and no longer read: an
    # identity switch is a persistent relabelling, so the correction runs to
    # the end of the segment rather than for a fixed window. Applying it for
    # a few frames and then reverting turned one discontinuity into two.
    consolidate_window: int = 5


class SmoothCfg(BaseModel):
    enabled: bool = True
    method: Literal["none", "moving_avg", "savgol"] = "savgol"
    window: int = 5
    polyorder: int = 2


class KinematicsCfg(BaseModel):
    # "savgol" differentiates the trajectory with a Savitzky-Golay filter:
    # centred (no half-frame offset) and one filtered derivative per
    # quantity (no squared noise). "forward_difference" is the pre-0.2
    # estimator, kept for one release so a project can reproduce older
    # numbers -- it assigns each forward difference to the earlier frame and
    # obtains acceleration by differencing an already-differenced series.
    # Switching shifts every speed, acceleration and turning value.
    method: Literal["savgol", "forward_difference"] = "savgol"
    # Deliberately separate from SmoothCfg's window even though the defaults
    # match: with smoothing on, the trajectory is filtered once for position
    # and again for the derivative, and tying the two together would hide
    # that rather than make it adjustable.
    window: int = 5
    polyorder: int = 2


class ValidateCfg(BaseModel):
    min_track_frames: int = 0
    max_pct_na_per_individual: float = 0.10


class PreprocessConfig(BaseModel):
    gap_fill: GapFillCfg = GapFillCfg()
    jump: JumpCfg = JumpCfg()
    identity_switch: IdSwitchCfg = IdSwitchCfg()
    smoothing: SmoothCfg = SmoothCfg()
    kinematics: KinematicsCfg = KinematicsCfg()
    coverage: ValidateCfg = ValidateCfg()


# ── Calibration & zones ───────────────────────────────────────────────────────


class CalibrationConfig(BaseModel):
    # "session" reads each session's own length_unit (the validator's
    # px-to-real-unit ratio) directly -- see
    # track2data/calibration/session_unit.py. Distinct from
    # "bodylength", which no longer consumes length_unit at all (see
    # that module's docstring for why).
    mode: Literal["scalar", "bodylength", "session"] = "bodylength"
    px_per_cm: float | None = None
    bl_min_samples: int = 30
    # idtracker.ai's length_unit (session_idtrackerai.md:242) is a ratio
    # to "user defined units" -- it does NOT record which physical unit
    # the Validator's Length Calibration tool was actually run in. The
    # arithmetic in calibration/bodylength.py and every *_cm-suffixed
    # export column is correct regardless; only the label is an
    # assumption. Defaults to "cm" (today's unconfirmed assumption, made
    # explicit rather than silent) -- set it to whatever unit was really
    # used (e.g. "mm") when Session.length_unit came from a calibration;
    # confirmed_by_user records whether anyone actually verified it.
    length_unit_label: str = "cm"
    length_unit_confirmed_by_user: bool = False
    # Which scale "session" mode takes when a session holds several Validator length
    # calibrations (Session.length_calibrations). "mean" is idtracker.ai's own length_unit (and
    # the default, so nothing changes for existing projects); "median" is the median of the
    # per-calibration ratios, which one badly placed click cannot move.
    session_calibration_stat: Literal["mean", "median"] = "mean"
    # Where the per-identity body length comes from (bodylength mode and every
    # *_bl column). "session" is the session-wide scalar idtracker.ai records
    # and the default. "blobs" derives a per-identity value from
    # preprocessing/list_of_blobs.pickle (readers/idtrackerai/blobs.py); it
    # needs security.allow_pickle_trajectories because it unpickles, and is
    # opt-in because docs/dev/EXTRACT_BBOXES_FIX.md measured a +27.8% bias in
    # the bbox-derived value it corrects, so switching changes *_cm numbers.
    body_length_source: Literal["session", "blobs"] = "session"


#: How the camera looked at the animals. "unknown" is the default and means nothing was declared,
#: so no view-dependent metric is offered. All three values exist from the start: a build that
#: predates a value rejects a manifest that uses it.
CameraView = Literal["unknown", "top", "side"]


class SceneConfig(BaseModel):
    """What the recordings look at, declared once for the project.

    Kept apart from ``ZoneSet`` (the Zones screen replaces that whole object on Clear/Load/Import)
    and from ``CalibrationConfig`` (hashed into the preprocessing cache key, which a camera view
    never changes: it only decides which metrics are offered).
    """

    camera_view: CameraView = "unknown"


MODE_3D_BLOCK_REASON = "3-D fusion is not available yet"
VIEWS_3D_ONLY = "Views apply to 3-D projects only"

#: Which camera a session was recorded from, in a 3-D project.
ViewRole = Literal["top", "side"]


class PairingPatterns(BaseModel):
    """Regular expressions that recognise the top and side session of a pair by name.

    Empty means no pattern. Stored in the mode, so they survive a re-scan of the sessions.
    """

    top_regex: str = ""
    side_regex: str = ""


class ViewPair(BaseModel):
    """One top session matched with one side session.

    ``fish_map`` maps a top fish label to the side fish label. ``same_ids`` says both views use
    the same labels, so the map is implied. ``auto`` marks a pair found by the name patterns.
    """

    top_session_id: str
    side_session_id: str
    same_ids: bool = False
    fish_map: dict[str, str] = {}
    auto: bool = False

    @model_validator(mode="after")
    def _two_different_sessions(self) -> ViewPair:
        if self.top_session_id == self.side_session_id:
            raise ValueError("a view pair needs two different sessions")
        return self


class ProjectMode(BaseModel):
    """Whether the project is 2-D or 3-D, and for 3-D how the two views are supplied.

    ``layout`` is set if and only if ``dimension == "3d"``. ``pairing`` holds the name
    patterns that match top and side sessions. A manifest written before ``pairing``
    existed may still carry an ``id_map`` key; pydantic ignores it.
    """

    dimension: Literal["2d", "3d"] = "2d"
    layout: Literal["single_video_two_panels", "two_videos"] | None = None
    pairing: PairingPatterns = PairingPatterns()

    @model_validator(mode="after")
    def _layout_iff_3d(self) -> ProjectMode:
        if self.dimension == "3d" and self.layout is None:
            raise ValueError("a 3d project mode requires a layout")
        if self.dimension == "2d" and self.layout is not None:
            raise ValueError("a 2d project mode must not set a layout")
        return self


class ROI(BaseModel):
    name: str
    level: str = "main"
    vertices: list[tuple[float, float]]
    area_units: float | None = None
    # "+" (additive) or "-" (subtractive/exclusion). idtracker.ai's roi_list
    # defines an arena as one or more "+ Polygon" outer boundaries minus any
    # number of "- Polygon" exclusion holes (idtracker.ai_usage.md:30-31).
    # Multiple ROIs sharing the same (name, level) with different signs
    # combine: a point belongs to the zone iff it is covered by at least
    # one "+" polygon and not covered by any "-" polygon of that name.
    # Defaults to "+" so hand-drawn zones (which have no notion of holes)
    # are unaffected.
    sign: Literal["+", "-"] = "+"


class ZoneSet(BaseModel):
    rois: list[ROI] = []
    orientation_tag: str | None = None
    zone_levels: dict[str, str] = {}
    # Pixel dimensions of the video these ROIs were defined against. Set
    # when seeding a ZoneSet from Session.roi_list; None for hand-drawn
    # zones (no source video to compare against). Used to detect (not
    # silently ignore) reusing a ZoneSet on a session tracked at a
    # different resolution -- see zones/io.py::zone_set_from_roi_list.
    source_width_px: int | None = None
    source_height_px: int | None = None


# ── Metric selection ──────────────────────────────────────────────────────────


class MetricSelection(BaseModel):
    individual: list[str] = []
    group: list[str] = []
    zone: list[str] = []
    # Diagnostic IDs (D-*) are auto-computed regardless; this list is
    # reserved for future per-user opt-outs.
    diagnostic: list[str] = []
    # Minutes per time bin (fractions allowed); None or 0 = whole session.
    # Results then carry bin_index / bin_start_s / bin_end_s. See metrics/binning.py.
    timepoint_minutes: float | None = None
    # Mask per-frame metrics when id_probabilities[frame, animal] < threshold.
    quality_threshold: float = 0.0
    # Per-metric parameter overrides, keyed metric_id -> {param_name:
    # value} -- see track2data/metrics/base.py's MetricParameter and
    # the ⚙ config dialog (ui/dialogs/metric_config_dialog.py). Only
    # covers non-derived parameters; a metric's derived values (e.g.
    # IL-3's arena centre) are never user-set, so never stored here.
    config: dict[str, dict[str, Any]] = {}


# ── Security ──────────────────────────────────────────────────────────────────


class SecurityConfig(BaseModel):
    """Per-project consent for operations that can execute code from data.

    ``npy`` is one of idtracker.ai's default trajectory output formats, and
    loading one means ``np.load(..., allow_pickle=True)`` -- which runs
    arbitrary code from the file. That matters more for a desktop app that
    invites the user to point a file dialog at a folder than it would for a
    library: any shared, downloaded or collaborator-supplied session folder
    is otherwise an execution vector.

    Defaults to off. When off, the reader refuses the pickled formats and
    falls through to h5/csv if the folder has them, so an ordinary session
    still imports; only a pickle-only folder needs the user to opt in.
    """

    allow_pickle_trajectories: bool = False


# ── Manifest building blocks ──────────────────────────────────────────────────


class SessionRef(BaseModel):
    session_id: str
    folder: Path
    sha256: str
    has_stable_identities: bool | None = None
    # Session.track_wo_identities as reported by the tracker, filled in by
    # the background probe in ui/store/project_store.py. None means "not
    # probed yet, or the reader had nothing to report" -- never "False".
    track_wo_identities: bool | None = None
    # The user's per-session answer from the Sessions screen checkbox.
    # None = follow the detected value; True/False = the user has
    # deliberately disagreed with (or confirmed) the tracker. Persisted,
    # unlike the detected value's cached twin in SessionFacts, because it
    # is user-authored project state that cannot be re-derived from the
    # session folder.
    identity_free_override: bool | None = None
    # The reader that reads this session, and how. Chosen once, by detection or by the user in
    # the confirm dialog, and replayed on every run, so the numbers cannot change because a
    # later detection came out differently. None on a manifest written before a reader could
    # be chosen: the engine then auto-detects exactly as it always did.
    reader: str | None = None
    reader_options: dict[str, Any] = {}
    reader_chosen_by: Literal["detected", "user"] | None = None
    # How sure the scan was when the choice was made ("HIGH", "MEDIUM", "LOW"), for provenance.
    reader_confidence: str | None = None
    # Which camera recorded this session, in a 3-D project. None until the user (or the name
    # patterns) says so.
    view_role: ViewRole | None = None

    @field_validator("session_id")
    @classmethod
    def _id_is_a_safe_path_segment(cls, value: str) -> str:
        """An id is used as a directory name (out_dir/<session_id>/): reject only what could
        escape it, so every id that loaded before still loads."""
        if not value or value in {".", ".."} or any(c in value for c in ("/", "\\", "\x00")):
            raise ValueError(f"unsafe session id: {value!r}")
        return value

    def is_identity_free(self) -> bool:
        """Whether per-individual metrics are meaningless for this session.

        The single source of truth for that question: the GUI greys rows
        with it (ui/metrics_screen.py) and the engine skips metrics with
        it (Engine.compute_metrics). Keeping the rule here rather than
        writing it out at both call sites is the point -- if those two
        ever disagreed, the UI would promise a skip that didn't happen
        (which is exactly the bug this replaced).
        """
        if self.identity_free_override is not None:
            return self.identity_free_override
        return self.track_wo_identities is True


class MetadataSource(BaseModel):
    path: Path
    sha256: str


class MappingRule(BaseModel):
    rules: dict[str, str] = {}   # canonical_field -> source_column
    join_keys: list[str] = ["session_id"]
    join_regex: str | None = None
    # Further metadata columns to carry through under their own (lower-cased)
    # names, e.g. weight or sex. Anything not listed is dropped, as before.
    extra_columns: list[str] = []
    # Only used when ``rules`` maps ``individual_id`` (one metadata row per
    # animal): how a row's individual_id is matched to an animal. "label" uses
    # the validator's identity labels, falling back to the 0-based position
    # when a session has none; "index" always uses the 0-based position.
    individual_match: Literal["label", "index"] = "label"


class ExportTarget(BaseModel):
    exporter_name: str
    out_dir: Path | None = None


# ── Project manifest ──────────────────────────────────────────────────────────


class ProjectManifest(BaseModel):
    schema_version: int = 1
    # Stamped into every exported manifest.json and the run README's
    # "App version" row -- part of the reproducibility record, so it must
    # track the real build rather than being an independent literal that
    # goes stale the moment a release is cut.
    app_version: str = __version__
    project_name: str
    created_at: datetime
    updated_at: datetime
    sessions: list[SessionRef] = []
    calibration: CalibrationConfig = CalibrationConfig()
    zones: ZoneSet = ZoneSet()
    scene: SceneConfig = SceneConfig()
    mode: ProjectMode = ProjectMode()
    view_pairs: list[ViewPair] = []
    metadata_source: MetadataSource | None = None
    mapping: MappingRule | None = None
    preprocess: PreprocessConfig = PreprocessConfig()
    metrics: MetricSelection = MetricSelection()
    security: SecurityConfig = SecurityConfig()
    export_targets: list[ExportTarget] = []
    run_log_path: Path | None = None
    # session_id -> video file, for sessions whose recorded video path does not
    # exist on this machine (IDT_VIDEO_PATH_UNREACHABLE). Remembered per
    # project, so the user locates the video once.
    video_overrides: dict[str, Path] = {}
    # Read idtracker.ai's blob layer on import to feed D-15 (tracker
    # corrections). Opt-in: it unpickles a file that is tens of MB, and needs
    # security.allow_pickle_trajectories.
    blob_diagnostics: bool = False

    def project_hash(self) -> str:
        """16-char hex hash of the manifest content (timestamps excluded)."""
        data: dict[str, Any] = self.model_dump(
            exclude={"created_at", "updated_at", "run_log_path"}
        )
        serialised = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(serialised.encode()).hexdigest()[:16]


# ── Preprocessing runtime types ───────────────────────────────────────────────
# These are dataclasses (not Pydantic) because they hold numpy arrays and are
# never serialised to JSON; they exist only in memory during a pipeline run.


@dataclass
class PPStepResult:
    """Result of a single preprocessing step."""

    step_name: str
    affected_frames: int
    affected_per_individual: list[int]
    notes: str = ""


@dataclass
class PreprocessReport:
    """Ordered log of all preprocessing steps applied to a session."""

    steps: list[PPStepResult] = field(default_factory=list)

    @property
    def total_affected_frames(self) -> int:
        return sum(s.affected_frames for s in self.steps)


@dataclass
class SessionRunResult:
    """
    Outcome of running one session through ``Engine.run()``.

    Deliberately small and picklable (a prerequisite for any future
    parallel execution across processes): metric previews are capped at
    ``head(200)`` and the full ``fish_by_frame`` table is never retained
    at all -- a 70-session real run would need tens of GB if every
    session's per-frame table were kept in memory afterwards.
    """

    session_id: str
    written: list[Path] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    metric_previews: dict[str, Any] = field(default_factory=dict)
    preprocess_report: PreprocessReport | None = None
    duration_s: float = 0.0
    error: str | None = None
    # Per-session facts (fps, group size, realised calibration) carried back
    # so run() can write sessions.csv and report cross-session heterogeneity
    # without re-reading 70 session folders. Small and frozen, so it does not
    # compromise this class's picklability. None when import itself failed.
    summary: SessionSummary | None = None


@dataclass
class RunResult:
    """Outcome of running every session in a manifest through ``Engine.run()``."""

    sessions: list[SessionRunResult] = field(default_factory=list)
    #: Files of the run-root ``all_sessions/`` folder (empty for fewer than two sessions).
    pooled: list[Path] = field(default_factory=list)

    @property
    def written(self) -> list[Path]:
        """All written paths: every session's, flattened, then the ``all_sessions/`` ones."""
        paths: list[Path] = []
        for s in self.sessions:
            paths.extend(s.written)
        paths.extend(self.pooled)
        return paths


@dataclass
class KinematicsArrays:
    """Per-frame kinematics derived from a preprocessed xy array."""

    speed_px_s: np.ndarray        # (n_frames, n_animals) — NaN at missing/boundary frames
    accel_px_s2: np.ndarray       # (n_frames, n_animals)
    heading_rad: np.ndarray       # (n_frames, n_animals)


@dataclass
class PreprocessedSession:
    """
    A fully preprocessed session ready for metric computation.

    Produced by ``preprocess.pipeline.run(session, config)``; consumed by
    all metric modules and the exporter layer.
    """

    session: Session                          # original Session (raw_xy untouched)
    xy: np.ndarray                            # (n_frames, n_animals, 2) preprocessed
    kinematics: KinematicsArrays
    px_per_cm: float | None = None            # set by calibration.scalar
    # Relative SD of the Validator's length-calibration clicks behind
    # px_per_cm. Only session mode derives px_per_cm from them, so only it
    # sets this; None means "no spread estimate" (other modes, or fewer than
    # two usable clicks), never "zero uncertainty".
    px_per_cm_rel_sd: float | None = None
    # (n_animals,) — set by calibration.bodylength. Historic misnomer: in
    # bodylength mode this holds pixel values (see calibration/bodylength.py).
    body_length_cm: np.ndarray | None = None
    # (n_animals,) body length in pixels — set by calibration.bodylength.
    # Body-length-normalised metrics divide pixel quantities by this, so they
    # do not depend on px_per_cm.
    body_length_px: np.ndarray | None = None
    # Zone assignments: object arrays of zone-name strings; None if zones not configured.
    main_zone: np.ndarray | None = None       # (n_frames, n_animals)
    sec_zone: np.ndarray | None = None        # (n_frames, n_animals)
    report: PreprocessReport = field(default_factory=PreprocessReport)
    # (n_frames, n_animals) bool -- True where jump_detect replaced an
    # anomalous position. Captured by the pipeline rather than derived like
    # was_interpolated, because it cannot be recovered by comparing raw_xy to
    # the final array: smoothing runs afterwards and moves every position, so
    # "differs from raw" stops isolating this step the moment it is enabled.
    # None when jump detection did not run.
    jump_replaced: np.ndarray | None = None
    # (n_frames,) true video frame of each row, for a session cut down to a window of its rows
    # (see metrics.binning.slice_psess); the full session derives it from
    # ``session.tracking_intervals`` instead, so this stays None. Use ``timeline()``.
    frame_index: np.ndarray | None = None
    timeline_valid: bool = True
    # The arrays above have one row per entry of ``frame_index`` when the session's tracking
    # intervals left unobserved stretches (see preprocess/timeline_expand.py); otherwise these
    # all stay None and every array is aligned with ``session`` exactly as before.
    # (n_rows,) bool: True for rows that came from a tracked interval, False for rows inserted
    # to represent unobserved video (an estimated frame or a separator).
    tracked_mask: np.ndarray | None = None
    # (n_rows,) bool: True for the single NaN row that stands for an unfilled gap. It is never
    # exported and is not a frame; it only keeps the two sides from being read as adjacent.
    separator_mask: np.ndarray | None = None
    # ``session.raw_xy`` / ``session.id_probabilities`` laid out on these rows (NaN where a row
    # was inserted). Tracker confidence is never invented for an inserted row.
    raw_xy_rows: np.ndarray | None = None
    id_probabilities_rows: np.ndarray | None = None

    @property
    def raw_xy_aligned(self) -> np.ndarray:
        """The tracker's positions on the same rows as ``xy``."""
        return self.session.raw_xy if self.raw_xy_rows is None else self.raw_xy_rows

    @property
    def id_probabilities_aligned(self) -> np.ndarray | None:
        """Identification probabilities on the same rows as ``xy`` (None when the tracker gave
        none)."""
        if self.id_probabilities_rows is not None:
            return self.id_probabilities_rows
        return self.session.id_probabilities

    def counted_rows(self) -> np.ndarray:
        """(n_rows,) bool: rows that stand for a video frame (everything but separators)."""
        if self.separator_mask is None:
            return np.ones(self.n_frames, dtype=bool)
        return ~self.separator_mask

    def timeline(self) -> tuple[np.ndarray, bool]:
        """(true video frame per row, whether that mapping is verified).

        The one place rows become video frames, shared by the per-frame table, binning and the
        zone events, so they cannot disagree about the clock.
        """
        if self.frame_index is not None:
            return self.frame_index, self.timeline_valid
        from track2data.core.timeline import map_array_index_to_true_frame

        return map_array_index_to_true_frame(self.session.tracking_intervals, self.n_frames)

    # ── convenience pass-throughs ─────────────────────────────────────────────

    @property
    def session_id(self) -> str:
        return self.session.session_id

    @property
    def n_frames(self) -> int:
        return int(self.xy.shape[0])

    def body_length_in_px(self) -> np.ndarray | None:
        """Per-animal body length in pixels, or None when unavailable.

        Prefers ``body_length_px`` (set by body-length calibration). Falls back
        to ``body_length_cm * px_per_cm`` when both are known in physical
        units, so ``*_bl`` metrics never depend on ``px_per_cm`` alone.
        """
        if self.body_length_px is not None:
            return self.body_length_px
        if self.body_length_cm is not None and self.px_per_cm is not None:
            return self.body_length_cm * self.px_per_cm
        return None

    @property
    def n_animals(self) -> int:
        return int(self.xy.shape[1])

    @property
    def fps(self) -> float:
        return self.session.video.fps

    @property
    def was_interpolated(self) -> np.ndarray:
        """
        (n_frames, n_animals) bool -- True where a position was originally
        missing (NaN in ``Session.raw_xy``) and is now present after
        preprocessing.

        Before this, ``trajectory_variant`` was a Session-level constant
        (always ``"with_gaps"``), so nothing in the exported per-frame
        table could distinguish a measured position from a reconstructed
        one. This is the honest, minimal version of that distinction: it
        does NOT flag ``jump_detect``'s anomaly-corrected replacements
        that did not originate from a NaN gap (those are already visible
        in ``PreprocessReport``'s ``jump_detect`` step, which records
        exactly how many frames it touched).
        """
        raw_nan = np.isnan(self.raw_xy_aligned[:, :, 0])
        final_present = ~np.isnan(self.xy[:, :, 0])
        return raw_nan & final_present

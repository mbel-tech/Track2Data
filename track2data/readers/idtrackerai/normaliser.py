"""
Normaliser: maps a raw TrajectoryPayload dict → Session.

Applies all version-agnostic normalisation rules from the analysis doc §4.1:
- id_probabilities shape (N, M, 1) is squeezed to (N, M).
- length_unit ≤ 0, None, or inf is treated as "not calibrated" → None.
- body_length_reliable is always False until the user explicitly acknowledges.
- Quality metrics are extracted into Session.quality.
- Unknown keys are preserved verbatim in Session.raw_attrs.

The Normaliser does NOT load files from disk — that is the format-specific
loader's job.  It only transforms an already-loaded dict into a Session.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from track2data.core.errors import DataValidationError
from track2data.core.models import Session, VideoInfo
from track2data.readers.idtrackerai.key_aliases import KNOWN_TRAJECTORY_KEYS, QUALITY_KEYS


class Normaliser:
    def __init__(self, folder: Path) -> None:
        self._folder = Path(folder)

    def normalise(
        self,
        payload: dict[str, Any],
        *,
        trajectory_format: str | None = None,
        session_meta: dict[str, Any] | None = None,
    ) -> Session:
        """
        Transform a raw trajectory dict into a canonical Session.

        Parameters
        ----------
        payload:
            Dict with the 17 idtracker.ai trajectory-dict keys (some may be absent).
        trajectory_format:
            Which file format the payload was loaded from (e.g. "npy", "h5", "csv").
        session_meta:
            Parsed contents of session.json, if available.
        """
        payload = self._apply_aliases(payload)
        meta = session_meta or {}
        raw_xy = self._extract_trajectories(payload, meta)
        n_frames, n_animals = raw_xy.shape[0], raw_xy.shape[1]

        id_prob = self._normalise_id_probabilities(
            payload.get("id_probabilities"), n_frames, n_animals
        )
        length_unit = self._normalise_length_unit(payload.get("length_unit"))
        quality = self._extract_quality(payload)
        version = payload.get("version") or meta.get("version")
        raw_attrs = self._collect_unknown_keys(payload)
        fps = self._require_positive_number(
            "frames_per_second", payload.get("frames_per_second"), meta.get("frames_per_second")
        )
        width = int(self._require_positive_number(
            "width", payload.get("width"), meta.get("width")
        ))
        height = int(self._require_positive_number(
            "height", payload.get("height"), meta.get("height")
        ))
        video_paths = payload.get("video_paths") or meta.get("video_paths") or []
        video_path = self._resolve_video_path(video_paths)

        video = VideoInfo(
            path=video_path,
            fps=fps,
            n_frames=n_frames,
            width_px=width,
            height_px=height,
        )

        has_stable = self._check_stability(raw_xy, quality, meta)
        body_length_px = self._normalise_body_length(payload.get("body_length"), n_animals)

        return Session(
            session_id=self._folder.name,
            folder=self._folder,
            reader="idtrackerai",
            video=video,
            n_animals=n_animals,
            trajectory_variant="with_gaps",
            has_stable_identities=has_stable,
            raw_xy=raw_xy,
            body_length_px=body_length_px,
            # output_structure_idtrackerai.md:104 warns this value depends on
            # segmentation parameters and video conditions, so it starts
            # unacknowledged regardless of source; see Session docstring.
            body_length_reliable=False,
            id_probabilities=id_prob,
            quality=quality,
            length_unit=length_unit,
            identities_labels=payload.get("identities_labels"),
            identities_groups=payload.get("identities_groups"),
            setup_points=payload.get("setup_points"),
            idtrackerai_version=version if isinstance(version, str) else None,
            trajectory_format=trajectory_format,
            raw_attrs=raw_attrs,
        )

    # ── private ───────────────────────────────────────────────────────────────

    @staticmethod
    def _apply_aliases(payload: dict[str, Any]) -> dict[str, Any]:
        """Rename old keys to their canonical names (extensible via key_aliases)."""
        from track2data.readers.idtrackerai.key_aliases import KEY_ALIASES
        out = dict(payload)
        for canonical, old_names in KEY_ALIASES.items():
            for old in old_names:
                if old in out and canonical not in out:
                    out[canonical] = out.pop(old)
                    break
        return out

    @staticmethod
    def _extract_trajectories(
        payload: dict[str, Any], session_meta: dict[str, Any]
    ) -> np.ndarray:
        """
        Extract and validate the ``trajectories`` array.

        Previously this accepted any array with no ndim/shape checks and no
        cross-check against session.json -- a missing key silently produced
        an empty (0, 0, 2) Session, and a transposed (n_animals, n_frames, 2)
        array (e.g. from a user-side reshape, or the tidy-CSV pivot path)
        would pass straight through and be silently misinterpreted, with
        every per-animal statistic computed over the wrong axis.
        idtrackerai_v5.py's legacy reader already solved this
        (_canonicalise_shape); reused here rather than reimplemented.
        """
        arr = payload.get("trajectories")
        if arr is None:
            raise DataValidationError(
                "Trajectory payload has no 'trajectories' key.",
                code="IDT_DICT_MISSING_KEY",
                severity="error",
                subject="trajectories",
                remediation=(
                    "The trajectory file is missing its primary array; "
                    "re-export the session or try a different trajectory format."
                ),
            )
        arr = np.asarray(arr, dtype=np.float64)

        if arr.ndim != 3 or arr.shape[-1] != 2:
            raise DataValidationError(
                f"Expected trajectories shape (n_frames, n_animals, 2), got {arr.shape}.",
                code="IDT_SHAPE_MISMATCH",
                severity="error",
                subject=str(arr.shape),
                remediation="Verify the trajectory file was written by idtracker.ai.",
            )

        n_frames_hint = session_meta.get("number_of_frames")
        n_animals_hint = session_meta.get("number_of_animals")
        d0, d1, _ = arr.shape
        resolved_by_hint = False

        if isinstance(n_frames_hint, (int, float)) and n_frames_hint > 0:
            if d0 == n_frames_hint:
                resolved_by_hint = True  # already canonical
            elif d1 == n_frames_hint:
                arr = arr.transpose(1, 0, 2)
                resolved_by_hint = True
            # else: neither axis matches the hint -- fall through to the
            # d0 < d1 heuristic below rather than raising, since a partial
            # session (tracking_intervals subsetting the video) can
            # legitimately make n_frames != number_of_frames.

        if not resolved_by_hint and arr.shape[0] < arr.shape[1]:
            # n_animals << n_frames in every real session; a smaller leading
            # axis means this is actually (n_animals, n_frames, 2). Only
            # applied when the hint above didn't already settle it -- a
            # short session can legitimately have n_frames < n_animals.
            arr = arr.transpose(1, 0, 2)

        if isinstance(n_animals_hint, (int, float)) and n_animals_hint > 0:
            if arr.shape[1] != n_animals_hint:
                raise DataValidationError(
                    f"trajectories has {arr.shape[1]} animals but session.json "
                    f"declares number_of_animals={int(n_animals_hint)}.",
                    code="IDT_SHAPE_MISMATCH",
                    severity="error",
                    subject=str(arr.shape),
                    remediation=(
                        "The trajectory array and session.json disagree on "
                        "animal count; the session data may be truncated or corrupt."
                    ),
                )

        return arr

    @staticmethod
    def _normalise_id_probabilities(
        raw: Any, n_frames: int, n_animals: int
    ) -> np.ndarray | None:
        if raw is None:
            return None
        arr = np.asarray(raw, dtype=np.float64)
        # Squeeze trailing singleton axis: (N, M, 1) → (N, M)
        if arr.ndim == 3 and arr.shape[2] == 1:
            arr = arr[:, :, 0]
        if arr.ndim != 2:
            return None
        return arr

    @staticmethod
    def _require_positive_number(
        field_name: str, primary: Any, fallback: Any
    ) -> float:
        """
        Resolve *field_name* from the trajectory dict, falling back to
        session.json, and raise rather than fabricate a value when neither
        source has a valid (finite, > 0) number.

        Previously this silently defaulted frames_per_second to 25.0 and
        width/height to 0 -- on the real idtracker.ai corpus every session's
        true fps sits in [24.833, 24.880] and none is 25.0, so a payload
        missing this key was producing every downstream speed/duration
        metric wrong by (true_fps / 25) with no warning at all. Also,
        `float("nan") or 25.0` evaluates to `nan` (NaN is truthy in Python),
        so a NaN value used to pass this check silently too -- isfinite()
        below closes that hole.
        """
        for candidate in (primary, fallback):
            if candidate is None:
                continue
            try:
                value = float(candidate)
            except (TypeError, ValueError):
                continue
            if math.isfinite(value) and value > 0:
                return value
        raise DataValidationError(
            f"{field_name} is missing or invalid in both the trajectory payload "
            "and session.json.",
            code="IDT_DICT_MISSING_KEY",
            severity="error",
            subject=field_name,
            remediation=(
                f"Ensure the session's trajectory file or session.json carries a "
                f"valid '{field_name}' value; it cannot be safely defaulted."
            ),
        )

    @staticmethod
    def _normalise_body_length(raw: Any, n_animals: int) -> np.ndarray | None:
        """
        Map the trajectory dict's ``body_length`` to ``Session.body_length_px``.

        ``body_length`` (output_structure_idtrackerai.md:81 / session_idtrackerai.md:17)
        is a single session-wide scalar -- the median diagonal of individual
        blob bounding boxes -- not a per-animal value. It is broadcast across
        all animals rather than fabricated per-identity: this is honestly
        the same session-wide estimate applied uniformly, and it is what
        unblocks the default 'bodylength' calibration mode
        (CalibrationConfig.mode default, calibration/bodylength.py), which
        previously raised CAL-BL-MISSING on every idtracker.ai session because
        this field was read from the payload and then silently discarded.

        A genuinely per-identity body length requires the blob layer
        (preprocessing/list_of_blobs.pickle) filtered on seems_like_individual
        + unicity frames -- out of scope here; see the format-alignment plan
        Fase 6c/7.
        """
        if raw is None or n_animals <= 0:
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(value) or value <= 0:
            return None
        return np.full(n_animals, value, dtype=np.float64)

    @staticmethod
    def _normalise_length_unit(raw: Any) -> float | None:
        if raw is None:
            return None
        try:
            val = float(raw)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(val) or val <= 0:
            return None
        return val

    @staticmethod
    def _extract_quality(payload: dict[str, Any]) -> dict[str, Any] | None:
        quality = {k: payload[k] for k in QUALITY_KEYS if k in payload}
        return quality if quality else None

    @staticmethod
    def _collect_unknown_keys(payload: dict[str, Any]) -> dict[str, Any] | None:
        unknown = {k: v for k, v in payload.items() if k not in KNOWN_TRAJECTORY_KEYS}
        return unknown if unknown else None

    @staticmethod
    def _resolve_video_path(video_paths: list | Any) -> Path | None:
        if not video_paths:
            return None
        first = video_paths[0] if isinstance(video_paths, (list, tuple)) else video_paths
        p = Path(str(first))
        return p if p.exists() else None

    @staticmethod
    def _check_stability(
        raw_xy: np.ndarray, quality: dict[str, Any] | None, session_meta: dict[str, Any]
    ) -> bool:
        """
        Decide whether per-individual identity is meaningful for this session.

        Prefers idtracker.ai's own authoritative signals over the NaN-based
        heuristic:

        1. ``track_wo_identities`` (idtracker.ai_usage.md: "Track the video
           without assigning identities") is decisive when present and True
           -- identities are not persistent by construction, so per-individual
           analysis is meaningless regardless of how complete the coverage
           looks. The old heuristic-only version would label such a session
           "stable" whenever coverage happened to be good.
        2. ``fraction_identified`` (output_structure_idtrackerai.md:85,
           already loaded into Session.quality) is the tracker's own
           fraction of (frame, animal) entries with a valid position --
           used at the same >= 0.5 threshold as D-5 IdentityStability
           (metrics/diagnostic.py) for consistency.
        3. Falls back to the raw per-animal NaN-coverage heuristic only when
           neither authoritative signal is available (e.g. a CSV bundle
           whose attributes.json doesn't carry these keys).
        """
        if session_meta.get("track_wo_identities") is True:
            return False

        if quality is not None and "fraction_identified" in quality:
            raw = quality["fraction_identified"]
            try:
                return float(raw) >= 0.50
            except (TypeError, ValueError):
                pass

        if raw_xy.size == 0:
            return False
        valid_frac = (~np.isnan(raw_xy[:, :, 0])).mean(axis=0)
        return bool(np.all(valid_frac >= 0.50))

"""
Reader for idtracker.ai v5 output folders.

Format assumptions (documented; verified by tests against synthetic fixtures)
────────────────────────────────────────────────────────────────────────────────
ASSUMPTION 1 — Trajectory file location
  <session_folder>/trajectories/trajectories_wo_gaps.npy   (preferred)
  <session_folder>/trajectories/trajectories.npy           (fallback)

ASSUMPTION 2 — Trajectory array shape
  Canonical: (n_frames, n_animals, 2) with (x, y) in pixels, float64.
  When n_frames is known from video_object.npy it is used to unambiguously
  identify which dimension is time.  Without that hint we fall back to a
  heuristic transpose when d0 < d1 and d2 == 2.  Any unresolvable shape
  raises DataValidationError.

ASSUMPTION 3 — NaN encoding
  Missing / untracked positions are encoded as NaN in the trajectory array.

ASSUMPTION 4 — video_object.npy
  Loaded via np.load(..., allow_pickle=True).item().
  Result is either a dict or an object with attribute access; both are tried
  via _get_field().  Known field aliases:
    fps      : "fps", "frames_per_second"
    n_frames : "frame_number", "total_frames", "n_frames"
    height   : "height", "original_height", "video_height"
    width    : "width", "original_width", "video_width"
    paths    : "paths_to_video_files", "video_paths", "video_path"

ASSUMPTION 5 — Body length
  Not stored at the trajectory level in v5 (blob-level data would require
  loading blobs_collection*.npy, which is out of scope for the reader).
  body_length_px is set to None; the calibration module can populate it later.

ASSUMPTION 6 — Identity stability
  has_stable_identities = True iff ALL animals have a non-NaN frame
  fraction ≥ STABILITY_THRESHOLD (default 0.50).

Open question: exact video_object.npy attribute names may differ between
minor idtracker.ai v5 releases.  The _get_field() helper tries multiple
aliases; add new ones here as needed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from track2data.core.errors import DataValidationError, ImportError_
from track2data.core.models import Session, VideoInfo
from track2data.readers.base import SessionReader

_SENTINEL = object()

#: Fraction of non-NaN frames required for an animal to be considered "tracked".
STABILITY_THRESHOLD: float = 0.50

#: Names to search when the trajectory subfolder is absent (legacy flat layout).
_TRAJ_SUBDIR = "trajectories"
_TRAJ_NAMES = ("trajectories_wo_gaps.npy", "trajectories.npy")
_VIDEO_OBJ_NAME = "video_object.npy"
_SESSION_JSON_NAMES = ("session_progress.json", "session.json")


def _get_field(obj: Any, *keys: str, default: Any = None) -> Any:
    """Try each key against obj using dict or attribute access; return first hit."""
    for key in keys:
        if isinstance(obj, dict):
            if key in obj:
                return obj[key]
        else:
            val = getattr(obj, key, _SENTINEL)
            if val is not _SENTINEL:
                return val
    return default


class IDTrackerAiV5Reader(SessionReader):
    """Reader for the current (v5) idtracker.ai output format."""

    name = "idtrackerai_v5"
    priority = 10

    # ── detect ────────────────────────────────────────────────────────────────

    @classmethod
    def detect(cls, folder: Path) -> bool:
        """Return True when folder looks like an idtracker.ai v5 session."""
        traj_dir = folder / _TRAJ_SUBDIR
        if not traj_dir.is_dir():
            return False
        has_traj = any((traj_dir / name).exists() for name in _TRAJ_NAMES)
        has_video_obj = (folder / _VIDEO_OBJ_NAME).exists()
        return has_traj and has_video_obj

    # ── read ──────────────────────────────────────────────────────────────────

    def read(self, folder: Path) -> Session:
        folder = Path(folder)
        # Load video object first so n_frames hint is available for shape detection.
        video_obj = self._load_video_object(folder)
        n_frames_hint = int(
            _get_field(video_obj, "frame_number", "total_frames", "n_frames") or 0
        )
        traj_path, variant = self._find_trajectory(folder)
        raw_xy = self._load_trajectory(traj_path, n_frames_hint=n_frames_hint)
        video_info = self._load_video_info(folder, raw_xy, video_obj=video_obj)
        has_stable = self._check_stability(raw_xy)

        return Session(
            session_id=folder.name,
            folder=folder,
            reader=self.name,
            video=video_info,
            n_animals=int(raw_xy.shape[1]),
            trajectory_variant=variant,
            has_stable_identities=has_stable,
            raw_xy=raw_xy,
            body_length_px=None,  # ASSUMPTION 5
        )

    # ── private helpers ───────────────────────────────────────────────────────

    def _find_trajectory(self, folder: Path) -> tuple[Path, str]:
        """
        Return (path, variant_label).  Prefers wo_gaps; falls back to with_gaps.
        Raises DataValidationError if neither file exists.
        """
        traj_dir = folder / _TRAJ_SUBDIR
        for name, variant in (
            ("trajectories_wo_gaps.npy", "wo_gaps"),
            ("trajectories.npy", "with_gaps"),
        ):
            candidate = traj_dir / name
            if candidate.exists():
                return candidate, variant

        raise DataValidationError(
            f"No trajectory file found in {traj_dir}",
            code="TRAJ_NOT_FOUND",
            severity="error",
            subject=str(folder),
            remediation=(
                "Ensure the session folder contains "
                "trajectories/trajectories.npy or trajectories/trajectories_wo_gaps.npy"
            ),
        )

    def _load_trajectory(self, path: Path, n_frames_hint: int = 0) -> np.ndarray:
        """
        Load trajectory .npy and return canonical (n_frames, n_animals, 2) float64.
        *n_frames_hint* from video_object.npy is used for unambiguous shape detection.
        """
        try:
            arr = np.load(path, allow_pickle=False)
        except Exception as exc:
            raise ImportError_(
                f"Cannot load trajectory file: {exc}",
                code="TRAJ_LOAD_ERROR",
                subject=str(path),
                remediation="Check that the file is a valid numpy array.",
            ) from exc

        if arr.ndim != 3:
            raise DataValidationError(
                f"Expected 3-D trajectory array, got shape {arr.shape}",
                code="TRAJ_BAD_NDIM",
                subject=str(path),
                remediation="Expected shape (n_frames, n_animals, 2).",
            )

        arr = self._canonicalise_shape(arr, path, n_frames_hint=n_frames_hint)
        return arr.astype(np.float64)

    @staticmethod
    def _canonicalise_shape(
        arr: np.ndarray, path: Path, n_frames_hint: int = 0
    ) -> np.ndarray:
        """
        Ensure array has shape (n_frames, n_animals, 2).

        ASSUMPTION 2: last dimension must be 2 (x, y).
        Disambiguation strategy (in priority order):
          1. If n_frames_hint > 0: match d0 or d1 against hint to identify axes.
          2. Heuristic: if d0 < d1 and d2 == 2, treat as (n_animals, n_frames, 2).
          3. If d2 != 2 but d1 == 2: try (n_frames, 2, n_animals) — unsupported.
        Raises DataValidationError for unresolvable shapes.
        """
        d0, d1, d2 = arr.shape

        if d2 != 2:
            raise DataValidationError(
                f"Expected last dimension == 2 for (x, y), got shape {arr.shape}",
                code="TRAJ_BAD_SHAPE",
                subject=str(path),
                remediation="Expected shape (n_frames, n_animals, 2).",
            )

        # Hint-based: video_object.npy knows n_frames
        if n_frames_hint > 0:
            if d0 == n_frames_hint:
                return arr  # canonical
            if d1 == n_frames_hint:
                return arr.transpose(1, 0, 2)  # (n_animals, n_frames, 2) → canonical
            # Neither axis matches — fall through to heuristic

        # Heuristic: in typical sessions n_animals << n_frames
        if d0 < d1:
            return arr.transpose(1, 0, 2)  # assume (n_animals, n_frames, 2)
        return arr  # assume canonical

    def _load_video_info(
        self, folder: Path, raw_xy: np.ndarray, video_obj: Any = None
    ) -> VideoInfo:
        """
        Build VideoInfo from video_object.npy with fallback to session_progress.json.
        n_frames is always taken from the trajectory shape (authoritative).
        *video_obj* may be passed in when already loaded to avoid a second disk read.
        """
        n_frames_from_traj = int(raw_xy.shape[0])

        # Primary: video_object.npy (ASSUMPTION 4)
        obj = video_obj if video_obj is not None else self._load_video_object(folder)

        fps = float(_get_field(obj, "fps", "frames_per_second") or 1.0)
        height = int(_get_field(obj, "height", "original_height", "video_height") or 0)
        width = int(_get_field(obj, "width", "original_width", "video_width") or 0)
        raw_paths = _get_field(obj, "paths_to_video_files", "video_paths", "video_path")

        # Fallback: session_progress.json for any missing fields
        if not height or not width or fps == 1.0:
            meta = self._load_session_json(folder)
            if meta:
                if fps == 1.0:
                    fps = float(_get_field(meta, "fps", "frames_per_second") or fps)
                if not height:
                    height = int(_get_field(meta, "video_height", "height") or 0)
                if not width:
                    width = int(_get_field(meta, "video_width", "width") or 0)

        # Resolve video path (ASSUMPTION 5 — may be unreachable)
        video_path: Path | None = None
        if raw_paths:
            if isinstance(raw_paths, (list, tuple)):
                raw_paths = raw_paths[0] if raw_paths else None
            if raw_paths:
                p = Path(str(raw_paths))
                video_path = p if p.exists() else None

        return VideoInfo(
            path=video_path,
            fps=fps,
            n_frames=n_frames_from_traj,
            width_px=width,
            height_px=height,
        )

    @staticmethod
    def _load_video_object(folder: Path) -> Any:
        path = folder / _VIDEO_OBJ_NAME
        raw = np.load(path, allow_pickle=True)
        return raw.item() if raw.ndim == 0 else raw

    @staticmethod
    def _load_session_json(folder: Path) -> dict | None:
        for name in _SESSION_JSON_NAMES:
            p = folder / name
            if p.exists():
                try:
                    return json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    return None
        return None

    @staticmethod
    def _check_stability(raw_xy: np.ndarray) -> bool:
        """True iff every animal has ≥ STABILITY_THRESHOLD non-NaN frames."""
        valid_frac = (~np.isnan(raw_xy[:, :, 0])).mean(axis=0)  # (n_animals,)
        return bool(np.all(valid_frac >= STABILITY_THRESHOLD))

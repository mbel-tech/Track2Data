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
        raw_xy = self._extract_trajectories(payload)
        n_frames, n_animals = raw_xy.shape[0], raw_xy.shape[1]

        id_prob = self._normalise_id_probabilities(
            payload.get("id_probabilities"), n_frames, n_animals
        )
        length_unit = self._normalise_length_unit(payload.get("length_unit"))
        quality = self._extract_quality(payload)
        version = payload.get("version")
        raw_attrs = self._collect_unknown_keys(payload)

        fps = float(payload.get("frames_per_second") or 25.0)
        width = int(payload.get("width") or 0)
        height = int(payload.get("height") or 0)
        video_paths = payload.get("video_paths") or []
        video_path = self._resolve_video_path(video_paths)

        video = VideoInfo(
            path=video_path,
            fps=fps,
            n_frames=n_frames,
            width_px=width,
            height_px=height,
        )

        has_stable = self._check_stability(raw_xy)

        return Session(
            session_id=self._folder.name,
            folder=self._folder,
            reader="idtrackerai",
            video=video,
            n_animals=n_animals,
            trajectory_variant="with_gaps",
            has_stable_identities=has_stable,
            raw_xy=raw_xy,
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
    def _extract_trajectories(payload: dict[str, Any]) -> np.ndarray:
        arr = payload.get("trajectories")
        if arr is None:
            return np.empty((0, 0, 2), dtype=np.float64)
        return np.asarray(arr, dtype=np.float64)

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
    def _check_stability(raw_xy: np.ndarray) -> bool:
        if raw_xy.size == 0:
            return False
        valid_frac = (~np.isnan(raw_xy[:, :, 0])).mean(axis=0)
        return bool(np.all(valid_frac >= 0.50))

"""Synthetic top/side ``PreprocessedSession`` pairs with known positions, for the fusion tests."""

from __future__ import annotations

import numpy as np

from track2data.core.models import (
    FusionSettings,
    KinematicsArrays,
    PreprocessedSession,
    Session,
    VideoInfo,
    ViewPair,
)

N_FRAMES = 100
FPS = 25.0
LABELS = ["a", "b", "c"]
SURFACE_ROW = 100.0
FLOOR_ROW = 300.0
TANK_CM = 20.0
#: Side-view image rows that give a depth of exactly 0.25 / 0.5 / 0.75 for the default settings.
SIDE_Y = (150.0, 200.0, 250.0)


def settings(**kw) -> FusionSettings:
    base = dict(surface_row=SURFACE_ROW, floor_row=FLOOR_ROW, tank_height_cm=TANK_CM)
    base.update(kw)
    return FusionSettings(**base)


def make_psess(
    session_id: str,
    xy: np.ndarray,
    *,
    fps: float = FPS,
    labels: list[str] | None = None,
    px_per_cm: float | None = None,
    frame_index: np.ndarray | None = None,
    separator_mask: np.ndarray | None = None,
    tracked_mask: np.ndarray | None = None,
    stable: bool = True,
) -> PreprocessedSession:
    """A preprocessed session around ``xy`` (n_frames, n_animals, 2).

    ``frame_index`` (true video frame per row) is set directly; without it row i is frame i.
    The raw positions equal ``xy``; kinematics are zero.
    """
    xy = np.asarray(xy, dtype=float)
    n_frames, n_animals = xy.shape[:2]
    session = Session(
        session_id=session_id,
        folder=f"/tmp/{session_id}",
        reader="test",
        video=VideoInfo(path=None, fps=fps, n_frames=n_frames, width_px=400, height_px=300),
        n_animals=n_animals,
        trajectory_variant="with_gaps",
        has_stable_identities=stable,
        raw_xy=xy.copy(),
        identities_labels=labels,
        body_length_px=np.arange(1, n_animals + 1, dtype=float) * 10,
        id_probabilities=np.full((n_frames, n_animals), 0.9),
    )
    zeros = np.zeros((n_frames, n_animals))
    return PreprocessedSession(
        session=session,
        xy=xy,
        kinematics=KinematicsArrays(
            speed_px_s=zeros.copy(), accel_px_s2=zeros.copy(), heading_rad=zeros.copy()
        ),
        px_per_cm=px_per_cm,
        frame_index=frame_index,
        separator_mask=separator_mask,
        tracked_mask=tracked_mask,
    )


def top_xy(n_frames: int = N_FRAMES) -> np.ndarray:
    """Three fish moving along x (fish k at x = 10 k + frame, y = 20 k + 5)."""
    t = np.arange(n_frames, dtype=float)
    out = np.empty((n_frames, 3, 2))
    for k in range(3):
        out[:, k, 0] = 10 * k + t
        out[:, k, 1] = 20 * k + 5
    return out


def side_xy(n_frames: int = N_FRAMES, reverse: bool = False) -> np.ndarray:
    """The side view of ``top_xy``: same horizontal position, constant depth per fish.

    With ``reverse`` the side view lists the fish in the opposite order (fish "c" first).
    """
    t = np.arange(n_frames, dtype=float)
    out = np.empty((n_frames, 3, 2))
    for k in range(3):
        out[:, k, 0] = 10 * k + t
        out[:, k, 1] = SIDE_Y[k]
    return out[:, ::-1] if reverse else out


def make_pair(
    *,
    n_frames: int = N_FRAMES,
    fps_top: float = FPS,
    fps_side: float = FPS,
    reverse_side: bool = False,
    px_per_cm: float | None = 2.0,
    fusion: FusionSettings | None = None,
    top_id: str = "t",
    side_id: str = "s",
) -> tuple[PreprocessedSession, PreprocessedSession, ViewPair]:
    """(top, side, pair) with labels a, b, c; the fish map is the identity."""
    side_labels = LABELS[::-1] if reverse_side else LABELS
    top = make_psess(
        top_id, top_xy(n_frames), fps=fps_top, labels=list(LABELS), px_per_cm=px_per_cm
    )
    side = make_psess(
        side_id, side_xy(n_frames, reverse_side), fps=fps_side, labels=list(side_labels)
    )
    pair = ViewPair(
        top_session_id=top_id,
        side_session_id=side_id,
        fish_map={lab: lab for lab in LABELS},
        fusion=fusion if fusion is not None else settings(),
    )
    return top, side, pair

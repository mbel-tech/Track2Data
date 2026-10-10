"""A small 3-D project on disk: real idtracker.ai v5 session folders with known depths.

The folders are read by a built-in reader, so a spawned worker process (which sees none of the
tests' monkeypatches) runs exactly what the calling process runs.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from track2data.core.models import (
    CalibrationConfig,
    FusionSettings,
    MetricSelection,
    ProjectManifest,
    ProjectMode,
    SessionRef,
    ViewPair,
)

N_FRAMES = 100
FPS = 25.0
#: Side-view rows of fish 0, 1, 2: depth 0.25 / 0.5 / 0.75 between surface row 100 and floor 300.
SIDE_ROWS = (150.0, 200.0, 250.0)
DEPTHS = (0.25, 0.5, 0.75)
TANK_CM = 20.0
LABELS = ("0", "1", "2")  # the v5 reader has no labels, so fish are named by column


def write_v5_session(folder: Path, xy: np.ndarray, *, fps: float = FPS) -> Path:
    """Write ``xy`` (n_frames, n_animals, 2) as an idtracker.ai v5 session folder."""
    (folder / "trajectories").mkdir(parents=True)
    np.save(folder / "trajectories" / "trajectories.npy", xy)
    n_frames, n_animals = xy.shape[:2]
    np.save(
        folder / "video_object.npy",
        {
            "fps": fps,
            "frame_number": n_frames,
            "height": 400,
            "width": 400,
            "paths_to_video_files": ["video.mp4"],
        },
    )
    (folder / "session_progress.json").write_text(
        json.dumps(
            {
                "session_name": folder.name,
                "number_of_animals": n_animals,
                "frames_per_second": fps,
                "video_height": 400,
                "video_width": 400,
                "status": "finished",
            }
        ),
        encoding="utf-8",
    )
    return folder


def top_xy(shift: float = 0.0) -> np.ndarray:
    t = np.arange(N_FRAMES, dtype=float)
    out = np.empty((N_FRAMES, 3, 2))
    for k in range(3):
        out[:, k, 0] = 20 + 10 * k + t + shift
        out[:, k, 1] = 50 + 20 * k
    return out


def side_xy(shift: float = 0.0) -> np.ndarray:
    out = top_xy(shift)
    for k in range(3):
        out[:, k, 1] = SIDE_ROWS[k]
    return out


def fusion_settings(**kw: object) -> FusionSettings:
    base: dict[str, object] = {"surface_row": 100.0, "floor_row": 300.0, "tank_height_cm": TANK_CM}
    base.update(kw)
    return FusionSettings(**base)  # type: ignore[arg-type]


def pair(top: str, side: str, *, fusion: FusionSettings | None = None) -> ViewPair:
    return ViewPair(
        top_session_id=top,
        side_session_id=side,
        fish_map={lab: lab for lab in LABELS},
        fusion=fusion if fusion is not None else fusion_settings(),
    )


def build_scene(
    base: Path,
    *,
    side2_fps: float = FPS,
    pairs: list[ViewPair] | None = None,
    with_lone: bool = True,
) -> ProjectManifest:
    """Two top/side pairs (t1+s1, t2+s2) and, with ``with_lone``, a top session in no pair.

    ``side2_fps`` other than ``FPS`` makes the second pair fail to fuse (frame rates differ).
    """
    write_v5_session(base / "t1", top_xy())
    write_v5_session(base / "s1", side_xy())
    write_v5_session(base / "t2", top_xy(5.0))
    write_v5_session(base / "s2", side_xy(5.0), fps=side2_fps)
    ids = ["t1", "s1", "t2", "s2"]
    if with_lone:
        write_v5_session(base / "lone", top_xy(9.0))
        ids.append("lone")
    now = datetime.now(tz=UTC)
    return ProjectManifest(
        project_name="scene3d",
        created_at=now,
        updated_at=now,
        sessions=[SessionRef(session_id=i, folder=base / i, sha256="") for i in ids],
        mode=ProjectMode(dimension="3d", layout="two_videos"),
        calibration=CalibrationConfig(mode="scalar", px_per_cm=10.0),
        metrics=MetricSelection(individual=["IL-1", "IL-15"], group=[], zone=[], diagnostic=[]),
        view_pairs=pairs if pairs is not None else [pair("t1", "s1"), pair("t2", "s2")],
    )

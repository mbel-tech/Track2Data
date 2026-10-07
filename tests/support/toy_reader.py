"""A minimal reader for a tracker that is not idtracker.ai.

It stands in for the real readers that arrive later, so everything that is *not* specific to a
tracker can be tested now: saved readers and options are replayed, the cache knows which reader
produced a session, the export says where the numbers came from.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import pandas as pd

from track2data.core.models import Session, VideoInfo
from track2data.readers.base import SessionReader
from track2data.readers.params import ReaderParameter

OPTIONS = {"fps": 25.0, "width_px": 100, "height_px": 80}


class ToyCsvReader(SessionReader):
    """Reads ``toy.csv`` (frame, id, x, y). Records nothing in the file about fps or frame size."""

    name = "toy_csv"
    display_name: ClassVar[str] = "Toy tracker"
    verification = "synthetic_only"
    parameters: ClassVar[tuple[ReaderParameter, ...]] = (
        ReaderParameter(name="fps", label="Frame rate", kind="float", required=True),
        ReaderParameter(name="width_px", label="Frame width", kind="int", required=True),
        ReaderParameter(name="height_px", label="Frame height", kind="int", required=True),
    )

    @classmethod
    def detect(cls, folder: Path) -> bool:
        return (folder / "toy.csv").exists()

    def read(self, folder: Path, *, allow_pickle: bool = False, options: Any = None) -> Session:
        table = pd.read_csv(folder / "toy.csv")
        ids = sorted(table["id"].unique())
        n_frames = int(table["frame"].max()) + 1
        xy = np.full((n_frames, len(ids), 2), np.nan)
        for column, animal in enumerate(ids):
            rows = table[table["id"] == animal]
            xy[rows["frame"].to_numpy(), column, 0] = rows["x"].to_numpy()
            xy[rows["frame"].to_numpy(), column, 1] = rows["y"].to_numpy()
        return Session(
            session_id="derived-by-the-reader",
            folder=folder,
            reader=self.name,
            video=VideoInfo(
                path=None,
                fps=options["fps"],
                n_frames=n_frames,
                width_px=options["width_px"],
                height_px=options["height_px"],
            ),
            n_animals=len(ids),
            trajectory_variant="with_gaps",
            has_stable_identities=True,
            raw_xy=xy,
            trajectory_source=folder / "toy.csv",
        )


def write_toy_session(folder: Path, *, n_frames: int = 60, seed: int = 0) -> Path:
    """Write a two-animal random walk to ``folder/toy.csv`` and return *folder*."""
    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    rows = []
    for animal in (0, 1):
        position = rng.uniform(20, 60, size=2)
        for frame in range(n_frames):
            position = position + rng.normal(0, 1.5, size=2)
            rows.append((frame, animal, *position))
    pd.DataFrame(rows, columns=["frame", "id", "x", "y"]).to_csv(folder / "toy.csv", index=False)
    return folder

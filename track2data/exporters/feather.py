"""PyArrow Feather (Arrow IPC) exporter."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from track2data.exporters._merge import merge_metric_frames
from track2data.exporters.base import Exporter, ExportPayload

_merge_individual_metrics = merge_metric_frames  # name kept for existing callers/tests


def _to_feather_safe(df: pd.DataFrame, path: Path) -> Path:
    """Write *df* to *path* as Feather (Arrow IPC), resetting the index.

    Converts object columns that contain mixed types to strings so that
    PyArrow can serialise them.
    """
    df = df.reset_index(drop=True)
    # Convert object columns to string to avoid PyArrow type inference issues
    for col in df.select_dtypes(include=["object"]).columns:
        df[col] = df[col].astype(str)
    df.to_feather(str(path))
    return path


# ── FeatherExporter ───────────────────────────────────────────────────────────


class FeatherExporter(Exporter):
    """PyArrow Feather (Arrow IPC) exporter.

    Writes two ``.feather`` files:

    * ``master_fish_by_frame.feather`` — per-frame trajectory + kinematics table.
    * ``trial_activity_summary.feather`` — individual-level metrics merged wide.
    """

    name = "feather"
    file_extension = ".feather"

    def write(self, payload: object, out_dir: Path) -> list[Path]:
        """Write Feather files to *out_dir*.

        Parameters
        ----------
        payload:
            An :class:`ExportPayload` instance.
        out_dir:
            Output directory (created if it does not exist).

        Returns
        -------
        list[Path]
            Paths of every file written.
        """
        p: ExportPayload = payload  # type: ignore[assignment]
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        written: list[Path] = []

        # ── master per-frame feather ───────────────────────────────────────────
        fish_df = p.fish_by_frame.copy()
        sort_keys = [k for k in ("session_id", "individual_id", "frame") if k in fish_df.columns]
        if sort_keys:
            fish_df = fish_df.sort_values(sort_keys).reset_index(drop=True)
        written.append(
            _to_feather_safe(fish_df, out_dir / "master_fish_by_frame.feather")
        )

        # ── individual metrics summary feather ────────────────────────────────
        indiv_summary = _merge_individual_metrics(p.individual_metrics)
        written.append(
            _to_feather_safe(indiv_summary, out_dir / "trial_activity_summary.feather")
        )

        return written


# ── Registration ──────────────────────────────────────────────────────────────

from track2data.exporters import register as _register  # noqa: E402

_register(FeatherExporter)

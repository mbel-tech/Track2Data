"""Long-format CSV exporter."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from track2data.exporters.base import Exporter, ExportPayload

# ── CSV write helpers ──────────────────────────────────────────────────────────

_CSV_KWARGS: dict[str, object] = {
    "encoding": "utf-8",
    "lineterminator": "\n",
    "index": False,
}


def _write_csv(df: pd.DataFrame, path: Path) -> Path:
    """Write *df* to *path* as UTF-8 CSV with LF line endings."""
    df.to_csv(path, **_CSV_KWARGS)  # type: ignore[arg-type]
    return path


def _merge_metric_dfs(metrics: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Outer-merge all metric DataFrames on their shared key columns.

    Key columns are identified as any column named ``session_id`` or
    ``individual_id`` (or any subset that is common to all frames).
    Returns an empty DataFrame when *metrics* is empty.
    """
    dfs = list(metrics.values())
    if not dfs:
        return pd.DataFrame()
    result = dfs[0]
    for other in dfs[1:]:
        # Identify join keys as shared columns present in both frames
        shared = [c for c in result.columns if c in other.columns]
        if shared:
            result = result.merge(other, on=shared, how="outer")
        else:
            result = pd.concat([result, other], axis=1)
    return result


# ── CsvLongExporter ───────────────────────────────────────────────────────────


class CsvLongExporter(Exporter):
    """Primary long-format CSV exporter.

    Writes three CSV files:

    * ``master_fish_by_frame.csv`` — per-frame trajectory + kinematics table,
      sorted by (session_id, individual_id, frame).
    * ``trial_activity_summary.csv`` — individual-level metrics merged into one
      row per (session x individual).
    * ``group_dynamics_summary.csv`` — group-level metrics (one row per session).
    """

    name = "csv_long"
    file_extension = ".csv"

    def write(self, payload: object, out_dir: Path) -> list[Path]:
        """Write all CSV files to *out_dir* and return the list of written Paths.

        Parameters
        ----------
        payload:
            An :class:`ExportPayload` instance.
        out_dir:
            Output directory (must already exist or will be created).

        Returns
        -------
        list[Path]
            Paths of every file written.
        """
        p: ExportPayload = payload  # type: ignore[assignment]
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        written: list[Path] = []

        # ── master per-frame CSV ───────────────────────────────────────────────
        fish_df = p.fish_by_frame.copy()
        sort_keys = [k for k in ("session_id", "individual_id", "frame") if k in fish_df.columns]
        if sort_keys:
            fish_df = fish_df.sort_values(sort_keys).reset_index(drop=True)
        written.append(_write_csv(fish_df, out_dir / "master_fish_by_frame.csv"))

        # ── individual metrics summary ─────────────────────────────────────────
        indiv_summary = _merge_metric_dfs(p.individual_metrics)
        if not indiv_summary.empty:
            sort_keys_i = [k for k in ("session_id", "individual_id") if k in indiv_summary.columns]
            if sort_keys_i:
                indiv_summary = indiv_summary.sort_values(sort_keys_i).reset_index(drop=True)
        written.append(_write_csv(indiv_summary, out_dir / "trial_activity_summary.csv"))

        # ── group dynamics summary ─────────────────────────────────────────────
        group_summary = _merge_metric_dfs(p.group_metrics)
        if not group_summary.empty:
            sort_keys_g = [k for k in ("session_id",) if k in group_summary.columns]
            if sort_keys_g:
                group_summary = group_summary.sort_values(sort_keys_g).reset_index(drop=True)
        written.append(_write_csv(group_summary, out_dir / "group_dynamics_summary.csv"))

        return written

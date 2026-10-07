"""Wide-format CSV exporter."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from track2data.exporters._merge import merge_metric_frames
from track2data.exporters.base import Exporter, ExportPayload

# ── CSV write helpers ──────────────────────────────────────────────────────────

_CSV_KWARGS: dict[str, object] = {
    "encoding": "utf-8",
    "lineterminator": "\n",
    "index": False,
}


def _write_csv(df: pd.DataFrame, path: Path) -> Path:
    """Write *df* to *path* as UTF-8 CSV with LF line endings."""
    df.to_csv(path, **_CSV_KWARGS)
    return path


def _build_wide(individual_metrics: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Merge all individual metric DataFrames into one wide-format frame.

    One row per (session_id, individual_id[, bin_index]) with every metric's
    value columns. ``metric_id`` is dropped; columns carried by several
    frames (e.g. metadata) appear once. Empty when *individual_metrics* is empty.
    """
    merged = merge_metric_frames(individual_metrics)
    if merged.empty and not len(merged.columns):
        return pd.DataFrame(columns=["session_id", "individual_id"])
    return merged


# ── CsvWideExporter ───────────────────────────────────────────────────────────


class CsvWideExporter(Exporter):
    """Wide-format CSV exporter.

    Writes a single file:

    * ``trial_summary_wide.csv`` — one row per (session_id, individual_id) with
      all individual metric values in wide format.
    """

    name = "csv_wide"
    file_extension = ".csv"

    def write(self, payload: object, out_dir: Path) -> list[Path]:
        """Write wide-format summary CSV to *out_dir*.

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

        wide_df = _build_wide(p.individual_metrics)
        path = _write_csv(wide_df, out_dir / "trial_summary_wide.csv")

        return [path]


# ── Registration ──────────────────────────────────────────────────────────────

from track2data.exporters import register as _register  # noqa: E402

_register(CsvWideExporter)

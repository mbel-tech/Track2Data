"""Wide-format CSV exporter."""

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


def _build_wide(individual_metrics: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Merge all individual metric DataFrames into a single wide-format frame.

    Each input DataFrame is expected to have at least ``session_id`` and
    ``individual_id`` columns.  Extra identifier columns (``metric_id``) are
    dropped before merging so they do not pollute the wide output.

    Parameters
    ----------
    individual_metrics:
        Dict mapping metric_id → per-individual DataFrame.

    Returns
    -------
    pd.DataFrame
        One row per (session_id, individual_id) with all metric value columns.
        Empty DataFrame when *individual_metrics* is empty.
    """
    if not individual_metrics:
        return pd.DataFrame(columns=["session_id", "individual_id"])

    key_cols = {"session_id", "individual_id"}
    drop_cols = {"metric_id"}

    merged: pd.DataFrame | None = None

    for df in individual_metrics.values():
        # Drop identifier columns that should not appear as wide columns
        df = df.drop(columns=[c for c in drop_cols if c in df.columns])

        if merged is None:
            merged = df.copy()
        else:
            # Join on shared key columns
            shared_keys = [c for c in df.columns if c in KEY_COLS and c in merged.columns]
            if shared_keys:
                merged = merged.merge(df, on=shared_keys, how="outer")
            else:
                merged = pd.concat([merged, df], axis=1)

    if merged is None:
        return pd.DataFrame(columns=["session_id", "individual_id"])

    # Sort by key columns if present
    sort_keys = [k for k in ("session_id", "individual_id") if k in merged.columns]
    if sort_keys:
        merged = merged.sort_values(sort_keys).reset_index(drop=True)

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

"""Multi-sheet XLSX exporter."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from track2data.exporters._merge import merge_metric_frames
from track2data.exporters.base import Exporter, ExportPayload

_merge_metric_dfs = merge_metric_frames  # name kept for existing callers/tests


def _merge_zone_dfs(metrics: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Concatenate all zone metric DataFrames."""
    dfs = list(metrics.values())
    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True)

logger = logging.getLogger(__name__)


#: One header row leaves this many data rows per worksheet (Excel's hard limit
#: is 1,048,576 rows); openpyxl refuses to write past it.
EXCEL_MAX_DATA_ROWS = 1_048_575


def _write_fish_by_frame(writer: pd.ExcelWriter, df: pd.DataFrame) -> None:
    """Write the per-frame table, continuing on "Fish by Frame 2", ... when it
    exceeds a worksheet. A 1 h, 60 fps, 10-animal session is 2.16 M rows; the
    full table is always available in the CSV/Feather exports."""
    limit = EXCEL_MAX_DATA_ROWS
    n_sheets = max(1, -(-len(df) // limit))
    if n_sheets > 1:
        logger.warning(
            "Fish-by-frame table has %d rows, over Excel's per-sheet limit; "
            "splitting across %d sheets.",
            len(df),
            n_sheets,
        )
    for i in range(n_sheets):
        name = "Fish by Frame" if i == 0 else f"Fish by Frame {i + 1}"
        df.iloc[i * limit : (i + 1) * limit].to_excel(writer, sheet_name=name, index=False)


class ExcelExporter(Exporter):
    """Write a multi-sheet XLSX workbook via openpyxl.

    Sheets
    ------
    * **Fish by Frame** — ``payload.fish_by_frame``
    * **Activity Summary** — individual metrics merged
    * **Group Dynamics** — group metrics merged
    * **Zone Occupancy** — zone metrics concatenated
    * **Quality** — diagnostic metrics concatenated
    """

    name = "excel"
    file_extension = ".xlsx"

    def write(self, payload: object, out_dir: Path) -> list[Path]:
        """Write a single XLSX file to *out_dir* and return ``[xlsx_path]``.

        Parameters
        ----------
        payload:
            An :class:`ExportPayload` instance.
        out_dir:
            Output directory.

        Returns
        -------
        list[Path]
            A one-element list containing the path to the written XLSX file.
        """
        p: ExportPayload = payload  # type: ignore[assignment]
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        xlsx_path = out_dir / f"Track2Data_{p.project_name}.xlsx"

        activity_df = _merge_metric_dfs(p.individual_metrics)
        group_df = _merge_metric_dfs(p.group_metrics)
        zone_df = _merge_zone_dfs(p.zone_metrics)
        quality_df = _merge_zone_dfs(p.diagnostic_metrics)

        with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
            _write_fish_by_frame(writer, p.fish_by_frame)
            activity_df.to_excel(writer, sheet_name="Activity Summary", index=False)
            group_df.to_excel(writer, sheet_name="Group Dynamics", index=False)
            zone_df.to_excel(writer, sheet_name="Zone Occupancy", index=False)
            quality_df.to_excel(writer, sheet_name="Quality", index=False)

        return [xlsx_path]


# ── Registration ──────────────────────────────────────────────────────────────

from track2data.exporters import register as _register  # noqa: E402

_register(ExcelExporter)

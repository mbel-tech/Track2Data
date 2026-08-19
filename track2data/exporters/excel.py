"""Multi-sheet XLSX exporter."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from track2data.exporters.base import Exporter, ExportPayload


def _merge_metric_dfs(metrics: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Outer-merge all metric DataFrames on shared key columns.

    Returns an empty DataFrame when *metrics* is empty.
    """
    dfs = list(metrics.values())
    if not dfs:
        return pd.DataFrame()
    result = dfs[0]
    for other in dfs[1:]:
        shared = [c for c in result.columns if c in other.columns]
        if shared:
            result = result.merge(other, on=shared, how="outer")
        else:
            result = pd.concat([result, other], axis=1)
    return result


def _merge_zone_dfs(metrics: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Concatenate all zone metric DataFrames."""
    dfs = list(metrics.values())
    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True)


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
            p.fish_by_frame.to_excel(writer, sheet_name="Fish by Frame", index=False)
            activity_df.to_excel(writer, sheet_name="Activity Summary", index=False)
            group_df.to_excel(writer, sheet_name="Group Dynamics", index=False)
            zone_df.to_excel(writer, sheet_name="Zone Occupancy", index=False)
            quality_df.to_excel(writer, sheet_name="Quality", index=False)

        return [xlsx_path]


# ── Registration ──────────────────────────────────────────────────────────────

from track2data.exporters import register as _register  # noqa: E402

_register(ExcelExporter)

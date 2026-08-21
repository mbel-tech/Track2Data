"""
Dumb pandas DataFrame -> QTableWidget formatting layer (issue #25).

Deliberately knows nothing about track2data (the engine): this module
may import ONLY pandas and PySide6 widgets, never track2data. That
keeps it reusable for rendering any DataFrame from any screen, with
zero engine coupling -- the same spirit as the ui/app-vs-engine
boundary recorded as D-001 in DECISIONS.md, applied one layer deeper to
this new widgets-vs-engine boundary. Enforced by
tests/test_ui/test_dataframe_table.py's source-text import check.
"""

from __future__ import annotations

import math

import pandas as pd
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem


def populate_table(table: QTableWidget, df: pd.DataFrame, max_rows: int = 200) -> None:
    """Fill *table* with *df*'s contents, truncated to *max_rows* rows.

    Column count and headers come from ``df.columns``; row count is
    ``min(len(df), max_rows)``. Each call fully replaces any previous
    contents. Floats are formatted to 4 significant figures, NaN
    renders as an empty string, everything else via ``str(value)``.
    """
    columns = list(df.columns)
    n_rows = min(len(df), max_rows)

    table.setColumnCount(len(columns))
    table.setHorizontalHeaderLabels([str(c) for c in columns])
    table.setRowCount(n_rows)

    for row in range(n_rows):
        for col_idx in range(len(columns)):
            value = df.iloc[row, col_idx]
            table.setItem(row, col_idx, QTableWidgetItem(_format_cell(value)))


def clear_table(table: QTableWidget) -> None:
    """Reset *table* to zero rows and zero columns."""
    table.setRowCount(0)
    table.setColumnCount(0)


def _format_cell(value: object) -> str:
    """Float -> 4 significant figures; NaN -> ""; everything else -> str()."""
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        return f"{value:.4g}"
    return str(value)

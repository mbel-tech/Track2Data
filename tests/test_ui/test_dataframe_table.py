"""
Tests for ui/widgets/dataframe_table.py (issue #25) -- a dumb pandas
DataFrame -> QTableWidget formatting layer with zero engine knowledge.

The layering-boundary test below enforces that dataframe_table.py never
imports track2data (the engine), mirroring the spirit of the ui/app-vs-
engine boundary recorded as D-001 in DECISIONS.md, applied to this new
widgets-vs-engine boundary.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QTableWidget

_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "ui" / "widgets" / "dataframe_table.py"
)


# ── layering boundary ────────────────────────────────────────────────────────


def test_dataframe_table_module_never_imports_track2data() -> None:
    """ui/widgets/dataframe_table.py must import ONLY pandas and PySide6 --
    never track2data. A simple source-text scan of its own import/from
    lines is enough to catch a regression."""
    source = _MODULE_PATH.read_text(encoding="utf-8")
    import_lines = [
        line for line in source.splitlines() if re.match(r"^\s*(import|from)\s", line)
    ]
    assert import_lines, "expected the module to contain at least one import statement"
    assert not any("track2data" in line for line in import_lines), (
        f"found a track2data import in a supposedly engine-free module: {import_lines}"
    )


# ── populate_table ───────────────────────────────────────────────────────────


def test_populate_table_sets_column_count_and_headers_from_df_columns(qtbot) -> None:
    from ui.widgets.dataframe_table import populate_table

    df = pd.DataFrame({"alpha": [1, 2], "beta": ["x", "y"]})
    table = QTableWidget()

    populate_table(table, df)

    assert table.columnCount() == 2
    assert table.horizontalHeaderItem(0).text() == "alpha"
    assert table.horizontalHeaderItem(1).text() == "beta"


def test_populate_table_sets_row_count_from_len_df(qtbot) -> None:
    from ui.widgets.dataframe_table import populate_table

    df = pd.DataFrame({"v": [1, 2, 3]})
    table = QTableWidget()

    populate_table(table, df)

    assert table.rowCount() == 3


def test_populate_table_truncates_to_max_rows(qtbot) -> None:
    from ui.widgets.dataframe_table import populate_table

    df = pd.DataFrame({"v": list(range(10))})
    table = QTableWidget()

    populate_table(table, df, max_rows=3)

    assert table.rowCount() == 3
    # First 3 rows in order, not an arbitrary subset.
    assert [table.item(r, 0).text() for r in range(3)] == ["0", "1", "2"]


def test_populate_table_formats_float_to_4_significant_figures(qtbot) -> None:
    from ui.widgets.dataframe_table import populate_table

    df = pd.DataFrame({"v": [1.0 / 3.0]})
    table = QTableWidget()

    populate_table(table, df)

    assert table.item(0, 0).text() == "0.3333"


def test_populate_table_renders_nan_as_empty_string(qtbot) -> None:
    from ui.widgets.dataframe_table import populate_table

    df = pd.DataFrame({"v": [1.0, float("nan")]})
    table = QTableWidget()

    populate_table(table, df)

    assert table.item(0, 0).text() == "1"
    assert table.item(1, 0).text() == ""


def test_populate_table_renders_other_types_via_str(qtbot) -> None:
    from ui.widgets.dataframe_table import populate_table

    df = pd.DataFrame({"session_id": ["abc"], "n": [5], "ok": [True]})
    table = QTableWidget()

    populate_table(table, df)

    assert table.item(0, 0).text() == "abc"
    assert table.item(0, 1).text() == "5"
    assert table.item(0, 2).text() == "True"


def test_populate_table_called_twice_overwrites_previous_contents(qtbot) -> None:
    """A second, smaller DataFrame must fully replace the first -- no
    stale rows/columns left behind from the earlier call."""
    from ui.widgets.dataframe_table import populate_table

    table = QTableWidget()
    populate_table(table, pd.DataFrame({"a": [1, 2], "b": [3, 4]}))
    assert table.columnCount() == 2
    assert table.rowCount() == 2

    populate_table(table, pd.DataFrame({"x": [1]}))

    assert table.columnCount() == 1
    assert table.rowCount() == 1
    assert table.horizontalHeaderItem(0).text() == "x"
    assert table.item(0, 0).text() == "1"


def test_populate_table_handles_empty_dataframe(qtbot) -> None:
    from ui.widgets.dataframe_table import populate_table

    df = pd.DataFrame({"a": pd.Series(dtype="float64"), "b": pd.Series(dtype="object")})
    table = QTableWidget()

    populate_table(table, df)

    assert table.columnCount() == 2
    assert table.rowCount() == 0


# ── clear_table ──────────────────────────────────────────────────────────────


def test_clear_table_resets_to_zero_rows_and_columns(qtbot) -> None:
    from ui.widgets.dataframe_table import clear_table, populate_table

    table = QTableWidget()
    populate_table(table, pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]}))
    assert table.rowCount() == 3
    assert table.columnCount() == 2

    clear_table(table)

    assert table.rowCount() == 0
    assert table.columnCount() == 0

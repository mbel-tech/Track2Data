"""
CSV / XLSX metadata loader with type coercion.

``load(path, sheet=None)`` returns a cleaned ``pandas.DataFrame`` (``sheet`` picks a sheet of an
Excel workbook; the first one by default). ``list_sheets`` names a workbook's sheets and
``preview`` gives the header and first rows exactly as stored, for the metadata screen:
  - Column names are stripped and lowercased.
  - String columns are stripped of leading/trailing whitespace.
  - Date-like columns are parsed to ``datetime64``.
"""

from __future__ import annotations

import contextlib
import csv
from pathlib import Path

import pandas as pd

_EXCEL_SUFFIXES = {".xlsx", ".xlsm"}


def _check_suffix(path: Path) -> str:
    """The lower-case suffix of a supported metadata file, else ``ValueError``."""
    suffix = path.suffix.lower()
    if suffix == ".xls":
        raise ValueError(
            f"{path.name} is an old-format Excel file (.xls), which is not supported. "
            "Save it as .xlsx or as a CSV and load that."
        )
    if suffix not in _EXCEL_SUFFIXES | {".csv"}:
        raise ValueError(f"Unsupported metadata file format: {suffix!r}")
    return suffix


def list_sheets(path: Path) -> list[str]:
    """The sheet names of an Excel workbook, in order; ``[]`` for a CSV.

    Raises ``ValueError`` for a format that is not supported (including ``.xls``).
    """
    path = Path(path)
    if _check_suffix(path) == ".csv":
        return []
    with pd.ExcelFile(path, engine="openpyxl") as workbook:
        return [str(name) for name in workbook.sheet_names]


def _sheet_to_read(path: Path, sheet: str | None) -> str | int:
    """*sheet* if the workbook has it, the first sheet when None, else ``ValueError`` that
    lists the sheets there are."""
    if sheet is None:
        return 0
    names = list_sheets(path)
    if sheet not in names:
        raise ValueError(
            f"{path.name} has no sheet {sheet!r}; its sheets are: {', '.join(names) or '(none)'}."
        )
    return sheet


def preview(
    path: Path, sheet: str | None = None, rows: int = 5
) -> tuple[list[str], list[list[str]]]:
    """The header and the first *rows* data rows as text, as stored (column names keep their case).

    Empty lists for an empty file or sheet. Raises like :func:`load`.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Metadata file not found: {path}")
    if _check_suffix(path) == ".csv":
        lines: list[list[str]] = []
        with open(path, newline="", encoding="utf-8-sig") as handle:
            for i, row in enumerate(csv.reader(handle)):
                lines.append(row)
                if i >= rows:  # header + rows
                    break
        return (lines[0], lines[1:]) if lines else ([], [])
    frame = pd.read_excel(
        path, sheet_name=_sheet_to_read(path, sheet), engine="openpyxl", dtype=str, nrows=rows
    )
    headers = [str(c) for c in frame.columns]
    return headers, [["" if pd.isna(v) else str(v) for v in row] for row in frame.to_numpy()]


def load(path: Path, sheet: str | None = None) -> pd.DataFrame:
    """
    Load a metadata file (CSV or XLSX) and return a cleaned DataFrame.

    Parameters
    ----------
    path:
        Path to a ``.csv`` or ``.xlsx`` file (the old ``.xls`` format is refused).
    sheet:
        Name of the sheet to read from a workbook. ``None`` (the default) reads the first sheet,
        as before. Ignored for a CSV.

    Returns
    -------
    pd.DataFrame
        Cleaned DataFrame with lowercased, stripped column names.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    ValueError
        If the file extension is not recognised, or *sheet* is not in the workbook (the message
        lists the sheets there are).
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Metadata file not found: {path}")

    if _check_suffix(path) == ".csv":
        df = pd.read_csv(path, encoding="utf-8-sig")
    else:
        df = pd.read_excel(path, sheet_name=_sheet_to_read(path, sheet), engine="openpyxl")

    # Normalise column names: strip whitespace + lowercase.
    df.columns = [str(c).strip().lower() for c in df.columns]

    # Strip whitespace from all string columns.
    for col in df.select_dtypes(include=["object", "string"]).columns:
        df[col] = df[col].str.strip()

    # Coerce obvious date columns to datetime.
    date_hints = {"trial_date", "date", "exp_date"}
    for col in df.columns:
        if col in date_hints:
            with contextlib.suppress(Exception):
                df[col] = pd.to_datetime(df[col], errors="coerce")

    return df

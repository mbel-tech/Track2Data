"""
CSV / XLSX metadata loader with type coercion.

``load(path, sheet=None)`` returns a cleaned ``pandas.DataFrame`` (``sheet`` picks a sheet of an
Excel workbook; the first one by default). ``list_sheets`` names a workbook's sheets and
``preview`` gives the header and first rows exactly as stored, for the metadata screen:
  - Column names are stripped and lowercased.
  - String cells are stripped of leading/trailing whitespace (other cells untouched).
  - Date columns are parsed to ``datetime64`` only when every value is an ISO date
    (YYYY-MM-DD); otherwise the text is kept as written.
"""

from __future__ import annotations

import csv
import re
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


_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?")


def _all_iso_dates(column: pd.Series) -> bool:
    """True when the column is text and every non-blank value is an ISO date."""
    if not (pd.api.types.is_object_dtype(column) or pd.api.types.is_string_dtype(column)):
        return False
    values = [v for v in column if not (v is None or (isinstance(v, float) and v != v))]
    values = [v for v in values if not (isinstance(v, str) and v == "")]
    return bool(values) and all(
        isinstance(v, str) and _ISO_DATE_RE.fullmatch(v) is not None for v in values
    )


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

    # Strip whitespace from string cells only: ``.str.strip()`` on an object column
    # crashed on booleans and blanked numbers sitting in a mixed column.
    for col in df.select_dtypes(include=["object", "string"]).columns:
        df[col] = df[col].map(lambda v: v.strip() if isinstance(v, str) else v)

    # Parse date columns only when every value is an unambiguous ISO date
    # (YYYY-MM-DD, optionally with a time). Anything else -- 15/03/2024, 5.3.2024 --
    # is left as the text the user wrote rather than guessed month-first or blanked.
    date_hints = {"trial_date", "date", "exp_date"}
    for col in df.columns:
        if col in date_hints and _all_iso_dates(df[col]):
            df[col] = pd.to_datetime(df[col], format="ISO8601")

    return df

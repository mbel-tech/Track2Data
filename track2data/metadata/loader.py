"""
CSV / XLSX metadata loader with type coercion.

``load(path)`` returns a cleaned ``pandas.DataFrame``:
  - Column names are stripped and lowercased.
  - String columns are stripped of leading/trailing whitespace.
  - Date-like columns are parsed to ``datetime64``.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

import pandas as pd


def load(path: Path) -> pd.DataFrame:
    """
    Load a metadata file (CSV or XLSX) and return a cleaned DataFrame.

    Parameters
    ----------
    path:
        Path to a ``.csv``, ``.xlsx``, or ``.xls`` file.

    Returns
    -------
    pd.DataFrame
        Cleaned DataFrame with lowercased, stripped column names.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    ValueError
        If the file extension is not recognised.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Metadata file not found: {path}")

    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        df = pd.read_excel(path, sheet_name=0, engine="openpyxl")
    elif suffix == ".csv":
        df = pd.read_csv(path, encoding="utf-8-sig")
    else:
        raise ValueError(f"Unsupported metadata file format: {suffix!r}")

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

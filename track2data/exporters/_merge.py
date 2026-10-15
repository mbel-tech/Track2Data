"""One merge for metric frames, shared by every exporter.

Metric frames are joined on identity keys only. Any other column that two
frames both carry (session-level metadata such as ``treatment`` is broadcast
onto every frame) is kept once when its values agree, instead of becoming
``treatment_x`` / ``treatment_y``; when the values differ, pandas' suffixes
are left in place so nothing is silently dropped.
"""

from __future__ import annotations

import pandas as pd

#: Columns that identify a row. ``bin_index`` is only a key when both frames have it.
KEY_COLS = ("session_id", "individual_id", "bin_index")
_DROP_COLS = ("metric_id",)


def _conflicts(left: pd.DataFrame, right: pd.DataFrame, keys: list[str], col: str) -> bool:
    """True if *col* disagrees between the frames on some shared key (NaN == NaN).

    Frames that share no key rows cannot disagree, so that is False -- but it also means the
    columns carry different rows' values, which is why the caller coalesces them rather than
    dropping one side.
    """
    both = left[[*keys, col]].merge(
        right[[*keys, col]], on=keys, how="inner", suffixes=("_l", "_r")
    )
    a, b = both[f"{col}_l"], both[f"{col}_r"]
    return not bool(((a == b) | (a.isna() & b.isna())).all())


def merge_metric_frames(metrics: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Outer-merge metric frames on their identity key columns.

    Returns an empty DataFrame when *metrics* is empty.
    """
    dfs = [
        df.drop(columns=[c for c in _DROP_COLS if c in df.columns]) for df in metrics.values()
    ]
    if not dfs:
        return pd.DataFrame()
    result = dfs[0]
    for other in dfs[1:]:
        keys = [c for c in KEY_COLS if c in result.columns and c in other.columns]
        if not keys:
            result = pd.concat([result, other], axis=1)
            continue
        dup = [c for c in other.columns if c in result.columns and c not in keys]
        agree = [c for c in dup if not _conflicts(result, other, keys, c)]
        # An agreeing column is kept once, but filled from *other* on the rows only it has:
        # dropping it would leave those rows empty (e.g. the bin boundaries of a binned
        # frame merged after a whole-session one).
        renamed = {c: f"{c}__other" for c in agree}
        result = result.merge(other.rename(columns=renamed), on=keys, how="outer")
        for c, tmp in renamed.items():
            result[c] = result[c].where(result[c].notna(), result[tmp])
            result = result.drop(columns=tmp)
    sort_keys = [k for k in KEY_COLS if k in result.columns]
    return result.sort_values(sort_keys).reset_index(drop=True) if sort_keys else result

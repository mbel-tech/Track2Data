"""Validate the blob-layer body length, D-13/D-14 and D-15 against real sessions.

Run this on the real idtracker.ai corpus (the 70 "Checked sessions GOT"
folders, or any directory of ``session_*`` folders). It answers the
questions that were left open when these features shipped:

* **Body length (issue #72).** How far does the per-identity blob-derived
  body length sit from the session-wide value the reader uses today (the
  tracker's own ``body_length``)? If they agree to within a few percent the
  ``body_length_source="blobs"`` option changes little; if they do not, it
  decides whether the default should change.
* **D-13 / D-14.** Are fragment ``identity`` and ``certainty`` actually
  populated, what do the certainty values look like, and how sensitive is the
  certain-fragment fraction to the 0.5 cut?
* **D-15.** Does ``identity_corrected_solving_jumps`` exist in real blob
  pickles, and how many frames does it flag?

Reading the blob layer unpickles ``list_of_blobs.pickle`` (through the
restricted, allow-listed unpickler), so it needs ``--allow-pickle``. Without
it the blob-dependent columns are left empty and the fragment/D-14 part still
runs.

    python scripts/validate_blob_diagnostics.py "Checked sessions GOT" \\
        --allow-pickle --out validation_report

Writes ``<out>.csv`` (one row per session) and ``<out>.md`` (the summary).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from track2data.readers import read_session
from track2data.readers.idtrackerai.blobs import (
    _load_blobs_in_video,
    compute_body_length_px_per_identity,
    find_identity_corrected_frames,
)
from track2data.readers.idtrackerai.fragments import individual_fragments

CERTAINTY_CUTS = (0.1, 0.5, 0.9)
NAN = float("nan")


def _fragment_stats(session: Any) -> dict[str, Any]:
    """Population and certainty statistics of the individual fragments."""
    out: dict[str, Any] = {"fragments_present": session.fragments is not None}
    if session.fragments is None:
        return out
    frags = individual_fragments(session.fragments)
    denom = session.n_frames * session.n_animals
    lengths, certainties, fixed = [], [], 0.0
    with_identity = with_certainty = 0
    cut_frames = dict.fromkeys(CERTAINTY_CUTS, 0.0)
    for f in frags:
        start, end = f.get("start_frame"), f.get("end_frame")
        if not isinstance(start, int) or not isinstance(end, int) or end <= start:
            continue
        length = float(end - start)
        lengths.append(length)
        with_identity += f.get("identity") is not None
        c = f.get("certainty")
        if isinstance(c, (int, float)) and not isinstance(c, bool):
            with_certainty += 1
            certainties.append((length, float(c)))
            for cut in CERTAINTY_CUTS:
                if c >= cut:
                    cut_frames[cut] += length
        if f.get("identity_is_fixed") is True:
            fixed += length
    n = len(lengths)
    out.update(
        n_individual_fragments=n,
        frac_fragments_with_identity=with_identity / n if n else NAN,
        frac_fragments_with_certainty=with_certainty / n if n else NAN,
        frac_frames_identity_fixed=min(fixed / denom, 1.0) if denom else NAN,
    )
    if certainties:
        values = np.array([c for _, c in certainties])
        out.update(
            certainty_min=float(values.min()),
            certainty_p50=float(np.percentile(values, 50)),
            certainty_p90=float(np.percentile(values, 90)),
            certainty_max=float(values.max()),
            n_negative_certainty=int((values < 0).sum()),
        )
    for cut in CERTAINTY_CUTS:
        out[f"frac_frames_certain_{cut}"] = (
            min(cut_frames[cut] / denom, 1.0) if denom and n else NAN
        )
    return out


def _blob_stats(session: Any, folder: Path) -> dict[str, Any]:
    """Body length (blob vs session-wide) and the D-15 attribute, if readable."""
    out: dict[str, Any] = {"blob_layer_read": False}
    loaded = _load_blobs_in_video(folder)
    if loaded is None:
        return out
    blobs, source_file = loaded
    out.update(blob_layer_read=True, blob_source_file=source_file)

    per_identity = compute_body_length_px_per_identity(blobs, session.n_animals)
    scalar = session.body_length_px
    if per_identity is not None and scalar is not None:
        scalar = np.asarray(scalar, dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = per_identity / scalar
        ratio = ratio[np.isfinite(ratio)]
        out.update(
            body_length_session_px=float(np.nanmedian(scalar)),
            body_length_blob_px=float(np.nanmedian(per_identity)),
            blob_to_session_ratio_median=float(np.median(ratio)) if ratio.size else NAN,
            blob_to_session_ratio_min=float(ratio.min()) if ratio.size else NAN,
            blob_to_session_ratio_max=float(ratio.max()) if ratio.size else NAN,
        )
    corrected = find_identity_corrected_frames(blobs)
    out["corrected_attribute_present"] = corrected is not None
    if corrected is not None:
        out["n_corrected_frames"] = len(corrected)
        out["frac_corrected_frames"] = (
            len(corrected) / session.n_frames if session.n_frames else NAN
        )
    return out


def validate_session(folder: Path, *, allow_pickle: bool) -> dict[str, Any]:
    row: dict[str, Any] = {"session_id": folder.name}
    try:
        session = read_session(folder, allow_pickle=allow_pickle)
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"
        return row
    row.update(n_frames=session.n_frames, n_animals=session.n_animals)
    row.update(_fragment_stats(session))
    if allow_pickle:
        row.update(_blob_stats(session, folder))
    return row


def _share(df: pd.DataFrame, col: str, predicate: Callable[[pd.Series], pd.Series]) -> str:
    if col not in df.columns:
        return "n/a"
    values = df[col].dropna()
    if values.empty:
        return "n/a"
    return f"{int(predicate(values).sum())}/{len(values)}"


def summarise(df: pd.DataFrame, *, allow_pickle: bool) -> str:
    n = len(df)
    ok = df[df["error"].isna()] if "error" in df.columns else df
    lines = [
        "# Blob-layer / D-13..D-15 validation",
        "",
        f"Sessions scanned: {n}; read without error: {len(ok)}.",
        "",
    ]
    if "error" in df.columns and df["error"].notna().any():
        lines += ["Failed sessions:", ""]
        lines += [f"- `{r.session_id}`: {r.error}" for r in df[df["error"].notna()].itertuples()]
        lines.append("")

    lines += ["## Fragments (D-13 / D-14)", ""]
    present = _share(ok, "fragments_present", lambda v: v.astype(bool))
    lines.append(f"- Sessions with `list_of_fragments.json`: {present}")
    for col, label in (
        ("frac_fragments_with_identity", "individual fragments carrying an `identity`"),
        ("frac_fragments_with_certainty", "individual fragments carrying a `certainty`"),
    ):
        if col in ok.columns and ok[col].notna().any():
            s = ok[col].dropna()
            lines.append(f"- Share of {label}: median {s.median():.2f}, min {s.min():.2f}")
    if "certainty_min" in ok.columns and ok["certainty_min"].notna().any():
        lines.append(
            f"- Certainty range across sessions: {ok['certainty_min'].min():.4f} "
            f"to {ok['certainty_max'].max():.4f}; sessions with negative values: "
            f"{_share(ok, 'n_negative_certainty', lambda v: v > 0)}"
        )
    lines += ["", "D-14 sensitivity to the certainty cut (median over sessions):", ""]
    lines += ["| cut | frac_frames_certain |", "|---|---|"]
    for cut in CERTAINTY_CUTS:
        col = f"frac_frames_certain_{cut}"
        if col in ok.columns and ok[col].notna().any():
            lines.append(f"| {cut} | {ok[col].median():.3f} |")
    lines.append("")

    lines += ["## Blob layer (body length, D-15)", ""]
    if not allow_pickle:
        lines.append("Not read: re-run with `--allow-pickle`.")
    else:
        read = _share(ok, "blob_layer_read", lambda v: v.astype(bool))
        lines.append(f"- Sessions whose blob pickle was read: {read}")
        col = "blob_to_session_ratio_median"
        if col in ok.columns and ok[col].notna().any():
            r = ok[col].dropna()
            dev = (r - 1).abs()
            lines += [
                f"- Blob / session-wide body length (median of per-identity ratios): "
                f"median {r.median():.3f}, range {r.min():.3f} to {r.max():.3f}",
                f"- Sessions differing by more than 5%: {int((dev > 0.05).sum())}/{len(r)}; "
                f"by more than 10%: {int((dev > 0.10).sum())}/{len(r)}",
            ]
            if "blob_to_session_ratio_max" in ok.columns:
                spread = (
                    ok["blob_to_session_ratio_max"] - ok["blob_to_session_ratio_min"]
                ).dropna()
                if not spread.empty:
                    lines.append(
                        f"- Within-session spread between identities (max - min ratio): "
                        f"median {spread.median():.3f}, max {spread.max():.3f}"
                    )
        lines.append(
            f"- Sessions whose blobs expose `identity_corrected_solving_jumps`: "
            f"{_share(ok, 'corrected_attribute_present', lambda v: v.astype(bool))}"
        )
        if "frac_corrected_frames" in ok.columns and ok["frac_corrected_frames"].notna().any():
            s = ok["frac_corrected_frames"].dropna()
            lines.append(
                f"- Fraction of frames flagged as corrected: median {s.median():.4f}, "
                f"max {s.max():.4f}; sessions with any: {int((s > 0).sum())}/{len(s)}"
            )
    lines += [
        "",
        "## How to read this",
        "",
        "- **Body length:** ratios near 1.0 with a small within-session spread mean "
        "`body_length_source=\"blobs\"` changes little and the default can stay. A "
        "systematic offset, or a wide spread between identities, is the case for "
        "changing it, and `docs/dev/EXTRACT_BBOXES_FIX.md` explains how to split "
        "genuine size differences from segmentation contamination.",
        "- **D-14:** if the medians barely move between the 0.1, 0.5 and 0.9 cuts the "
        "choice of 0.5 is immaterial; if they swing, the cut needs a defensible value.",
        "- **D-15:** `corrected_attribute_present` false on real sessions means the "
        "attribute does not exist in that pickle layout and D-15 should be removed or "
        "re-sourced; all-zero counts mean the attribute exists but is never set.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("corpus", type=Path, help="directory containing session_* folders")
    ap.add_argument("--allow-pickle", action="store_true",
                    help="read list_of_blobs.pickle and pickled trajectories")
    ap.add_argument("--out", type=Path, default=Path("validation_report"),
                    help="output path without extension (default: validation_report)")
    args = ap.parse_args(argv)

    folders = sorted(p for p in args.corpus.glob("session_*") if p.is_dir())
    if not folders:
        print(f"No session_* folders found in {args.corpus}", file=sys.stderr)
        return 2
    rows = []
    for i, folder in enumerate(folders, 1):
        print(f"[{i}/{len(folders)}] {folder.name}", file=sys.stderr)
        rows.append(validate_session(folder, allow_pickle=args.allow_pickle))
    df = pd.DataFrame(rows)
    df.to_csv(args.out.with_suffix(".csv"), index=False)
    args.out.with_suffix(".md").write_text(
        summarise(df, allow_pickle=args.allow_pickle), encoding="utf-8"
    )
    print(f"Wrote {args.out.with_suffix('.csv')} and {args.out.with_suffix('.md')}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

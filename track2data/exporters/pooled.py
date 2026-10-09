"""The run-root ``all_sessions/`` folder: every session's tables, concatenated.

Each session folder is written independently (and possibly by a worker
process), so this runs afterwards and reads the files back from disk rather
than holding every session's tables in memory -- ``master_fish_by_frame.csv``
alone can be millions of rows per session.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

#: Folder name, at the run root next to the per-session folders.
POOLED_DIRNAME = "all_sessions"

#: The tables a session folder can hold. Every one carries ``session_id``, so
#: stacking them loses no information.
POOLED_TABLES = (
    "metrics_long.csv",
    "trial_activity_summary.csv",
    "group_dynamics_summary.csv",
    "master_fish_by_frame.csv",
)

_CHUNK_ROWS = 200_000


def _header(path: Path) -> list[str]:
    """Column names of *path*; empty for a table the exporter wrote with no columns."""
    try:
        return list(pd.read_csv(path, nrows=0).columns)
    except pd.errors.EmptyDataError:
        return []


def _concat_csv(paths: list[Path], dest: Path) -> Path:
    """Stack *paths* into *dest* over the union of their columns.

    Cells are copied as text, so a value is byte-identical to the one in its
    session file. A column a session lacks is left blank (e.g. sessions run
    with different metric selections). Streamed in chunks.
    """
    columns: list[str] = []
    paths = [p for p in paths if _header(p)]
    for path in paths:
        columns += [c for c in _header(path) if c not in columns]
    if not columns:
        dest.write_text("\n", encoding="utf-8")  # same as the empty tables it pools
        return dest

    first = True
    with open(dest, "w", encoding="utf-8", newline="") as out:
        for path in paths:
            for chunk in pd.read_csv(path, dtype=str, keep_default_na=False, chunksize=_CHUNK_ROWS):
                chunk.reindex(columns=columns, fill_value="").to_csv(
                    out, header=first, index=False, lineterminator="\n"
                )
                first = False
    if first:  # every file was header-only: keep the header
        pd.DataFrame(columns=columns).to_csv(dest, index=False, lineterminator="\n")
    return dest


def _load_manifest(folder: Path) -> dict | None:
    path = folder / "manifest.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_manifest_and_readme(
    out_dir: Path, session_ids: list[str], manifests: dict[str, dict]
) -> list[Path]:
    """Pooled manifest.json + README.md, built from the per-session ones."""
    base = dict(next(iter(manifests.values())))
    runs = {sid: m.get("run_metadata", {}) for sid, m in manifests.items()}
    first = next(iter(runs.values()))
    metrics = sorted({m for r in runs.values() for m in r.get("metrics_computed", [])})
    timestamp = datetime.now(tz=UTC).isoformat()
    base["run_metadata"] = {
        "pooled": True,
        "sessions": session_ids,
        "project_hash": first.get("project_hash"),
        "app_version": first.get("app_version"),
        "generated_at": timestamp,
        "metrics_computed": metrics,
        "session_provenance": {sid: r.get("session_provenance") for sid, r in runs.items()},
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(base, indent=2, default=str), encoding="utf-8")

    lines = [
        f"# Track2Data pooled export — {base.get('project_name', '')}",
        "",
        f"Generated at {timestamp}.",
        "",
        f"The tables in this folder are the {len(session_ids)} sessions' tables of the "
        "same name stacked one after another, with no recomputation. "
        "`session_id` says which session each row came from. A column a session "
        "does not have is blank for its rows.",
        "",
        "Stacking is not the same as pooling: sessions can differ in frame rate, "
        "group size or calibration. Read `PROJECT_SUMMARY.md` and `sessions.csv` "
        "one level up before analysing these together, and treat `session_id` as "
        "a random effect rather than counting every row as independent.",
        "",
        "## Sessions",
        "",
        *[f"- {sid}" for sid in session_ids],
        "",
        "## Metrics computed",
        "",
        *([f"- {m}" for m in metrics] or ["*(none)*"]),
        "",
        "`manifest.json` holds the project parameters and each session's input "
        "checksums under `run_metadata.session_provenance`.",
        "",
    ]
    readme_path = out_dir / "README.md"
    readme_path.write_text("\n".join(lines), encoding="utf-8")
    return [manifest_path, readme_path]


def write_all_sessions(
    run_dir: Path, session_ids: list[str], *, min_sessions: int = 2
) -> list[Path]:
    """Write ``run_dir/all_sessions/`` from the given sessions' folders.

    Nothing is written for fewer than *min_sessions* sessions: the folder
    would only duplicate the one session. Returns the paths written.
    """
    folders = {sid: run_dir / sid for sid in session_ids if (run_dir / sid).is_dir()}
    if len(folders) < min_sessions:
        return []

    out_dir = run_dir / POOLED_DIRNAME
    out_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for table in POOLED_TABLES:
        sources = [f / table for f in folders.values() if (f / table).is_file()]
        if sources:
            written.append(_concat_csv(sources, out_dir / table))

    manifests = {sid: m for sid, f in folders.items() if (m := _load_manifest(f)) is not None}
    if manifests:
        written += _write_manifest_and_readme(out_dir, list(manifests), manifests)
    return written

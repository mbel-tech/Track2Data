"""track2data command-line interface.

Provides headless access to the full Track2Data pipeline.

Commands
--------
run          Run the full pipeline for a project manifest.
validate     Validate schema and check reachability without running.
list-metrics Print all registered metric IDs and descriptions.
list-readers Print the registered readers and the options each needs.
scan         Look at a folder and say which tracking software wrote it.
add          Scan a folder, confirm the software, and add its sessions to a project.
cache        Wipe the cache directory.
new          Scaffold an empty project manifest.

Example::

    # Scaffold a project, then run it
    track2data new my_experiment
    # edit my_experiment.t2d.json to add sessions + metrics
    track2data run my_experiment.t2d.json --out-dir results/
"""

from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

if TYPE_CHECKING:
    from track2data.api import Engine
    from track2data.core.models import ProjectManifest
    from track2data.metrics.base import Metric
    from track2data.readers.base import SessionReader
    from track2data.readers.confirm import ConfirmDraft
    from track2data.readers.detection import Detection
    from track2data.readers.scan import ScanResult

logger = logging.getLogger(__name__)


# ── helpers ───────────────────────────────────────────────────────────────────


def _load_manifest(project: str) -> ProjectManifest:
    """Load and return a ProjectManifest; exit on failure."""
    from track2data.core.manifest import read as manifest_read

    try:
        return manifest_read(Path(project))
    except Exception as exc:
        click.echo(f"[error] Cannot read manifest: {exc}", err=True)
        sys.exit(1)


def _refuse_3d_sensitivity(engine: Engine) -> None:
    """Exit 2 before any output is made: a sensitivity sweep refuses every 3-D project. (``run``
    gates on the run plan itself; see :func:`run`.)"""
    from track2data.core.models import SENSITIVITY_3D_REFUSAL

    if engine.manifest.mode.dimension == "3d":
        click.echo(f"[error] {SENSITIVITY_3D_REFUSAL}", err=True)
        sys.exit(2)


# ── CLI group ─────────────────────────────────────────────────────────────────


@click.group()
@click.option("-v", "--verbose", is_flag=True, default=False,
              help="Enable DEBUG-level logging.")
def cli(verbose: bool) -> None:
    """Track2Data — headless pipeline runner."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )


# ── run ───────────────────────────────────────────────────────────────────────


@cli.command()
@click.argument("project", type=click.Path(exists=True))
@click.option("--out-dir", "-o", default=None,
              help="Output directory. Defaults to <project>_output/.")
@click.option("--exporter", "-e", "exporters", multiple=True,
              help="Exporter(s) to use. Repeat for multiple.")
@click.option("--cache-dir", default=None,
              help="Reuse preprocessed sessions from this directory (off by default).")
def run(
    project: str, out_dir: str | None, exporters: tuple[str, ...], cache_dir: str | None
) -> None:
    """Run the full pipeline for a project manifest.

    Reads PROJECT (a .t2d.json file), imports all sessions, preprocesses,
    computes all selected metrics, and writes output to OUT_DIR.
    """
    from track2data.api import Engine

    manifest = _load_manifest(project)

    # Resolve output directory.
    if out_dir is None:
        out_path = Path(project).with_suffix("").with_suffix("") / "output"
    else:
        out_path = Path(out_dir)

    # Validate before running. The run plan is built once, here (in a 3-D project that fuses
    # every pair), and handed to engine.run(); a 3-D project with nothing to run exits 2
    # before anything is written.
    engine = Engine(manifest, cache_dir=Path(cache_dir) if cache_dir else None)
    try:
        plan = engine.require_computable()
    except ValueError as exc:
        click.echo(f"[error] {exc}", err=True)
        sys.exit(2)
    issues, _notes = engine.validation_issues(plan)
    if issues:
        for issue in issues:
            click.echo(f"[warn] {issue}", err=True)
    # Left out of a 3-D run: in no pair, or in a pair that does not fuse.
    for skip in plan.skipped:
        click.echo(f"[skipped] {skip.session_id}: {skip.reason}", err=True)

    exporter_list = list(exporters) if exporters else None

    if manifest.mode.dimension == "3d":
        size = f"{len(plan.units)} fused pair(s), {len(plan.skipped)} session(s) skipped"
    else:
        size = f"{len(manifest.sessions)} session(s)"
    click.echo(f"Running project '{manifest.project_name}' ({size})…")

    try:
        result = engine.run(out_path, exporters=exporter_list, plan=plan)
    except Exception as exc:
        click.echo(f"[error] Pipeline failed: {exc}", err=True)
        logger.exception("Pipeline failed")
        sys.exit(2)

    # A session that fails (import, preprocess, metrics, or export) is
    # captured as its own SessionRunResult.error rather than aborting the
    # batch -- but per FR-IMP-3 that failure must still be flagged loudly
    # here, not left for the user to notice only from a lower file count.
    failed = [s for s in result.sessions if s.error]
    for s in failed:
        click.echo(f"[error] Session '{s.session_id}' failed: {s.error}", err=True)

    written = result.written
    if written:
        click.echo(f"Wrote {len(written)} file(s) to {out_path}:")
        for p in written:
            click.echo(f"  {p}")
    else:
        click.echo("[warn] No output files written.", err=True)

    if failed:
        sys.exit(1)


# ── validate ──────────────────────────────────────────────────────────────────


@cli.command()
@click.argument("project", type=click.Path(exists=True))
def validate(project: str) -> None:
    """Validate schema and reachability without running the pipeline.

    Exits with code 0 when the manifest is valid, 1 otherwise. In a 3-D project a pair that does
    not fuse, or a session in no pair, is listed but does not fail validation: the run leaves it
    out. Only a 3-D project with no fusable pair at all fails.
    """
    from track2data.api import Engine

    manifest = _load_manifest(project)
    engine = Engine(manifest)
    issues, notes = engine.validation_issues()

    # Non-blocking, and printed whether or not there are blocking issues:
    # a mixed-frame-rate project is a legitimate design, but silently
    # pooling it is the mistake this exists to prevent.
    for warning in engine.consistency_warnings():
        click.echo(f"[consistency] {warning}", err=True)
    for note in notes:
        click.echo(f"[issue] {note}", err=True)

    if not issues:
        click.echo(f"OK — '{manifest.project_name}' is ready to run.")
    else:
        for issue in issues:
            click.echo(f"[issue] {issue}", err=True)
        sys.exit(1)


# ── list-metrics ──────────────────────────────────────────────────────────────


def _natural_sort_key(metric_cls: type[Metric]) -> tuple[str, int]:
    """Sort metrics naturally: GL-1, GL-2, GL-10 (not GL-1, GL-10, GL-2)."""
    prefix, _, number = metric_cls.id.rpartition("-")
    return (prefix, int(number))


@cli.command("list-metrics")
@click.option("--level", default=None,
              type=click.Choice(["individual", "group", "zone", "diagnostic"]),
              help="Filter by metric level.")
def list_metrics(level: str | None) -> None:
    """Print all registered metric IDs, levels, and descriptions.

    Triggers lazy loading of all built-in metric modules before listing.
    """
    from track2data.metrics import _load_builtins, _registry
    from track2data.metrics.availability import required_views_text

    _load_builtins()  # ensure builtins are registered

    metrics = sorted(_registry.values(), key=_natural_sort_key)
    if level is not None:
        metrics = [m for m in metrics if m.level == level]

    if not metrics:
        click.echo("No metrics registered.")
        return

    # Column widths
    id_w = max(len(m.id) for m in metrics)
    lvl_w = max(len(m.level) for m in metrics)
    # There is no metric-selection UI on the CLI path (metrics are edited
    # by hand in the manifest), so this column is the only place a CLI
    # user can see which metrics an identity-free session will refuse.
    idy_w = len("IDENTITY")
    # Likewise for the camera view: the CLI user declares it by editing the manifest, so this is
    # where they find out which metrics a declared view switches on.
    def _view_text(m: Any) -> str:
        if getattr(m, "requires_depth_scale", False):
            return "fused 3-D + cm scale"
        return required_views_text(m) or "any"

    view_w = max(len("VIEW"), *(len(_view_text(m)) for m in metrics))

    click.echo(
        f"{'ID':<{id_w}}  {'LEVEL':<{lvl_w}}  {'IDENTITY':<{idy_w}}  {'VIEW':<{view_w}}  NAME"
    )
    click.echo("-" * (id_w + lvl_w + idy_w + view_w + 34))
    for m in metrics:
        label = getattr(m, "label", getattr(m, "name", ""))
        needs = "required" if m.requires_identity else "free"
        view = _view_text(m)
        click.echo(
            f"{m.id:<{id_w}}  {m.level:<{lvl_w}}  {needs:<{idy_w}}  {view:<{view_w}}  {label}"
        )


# ── cache ─────────────────────────────────────────────────────────────────────


@cli.command()
@click.argument("subcommand", type=click.Choice(["clear", "stats"]))
@click.option("--cache-dir", default=".t2d_cache",
              help="Path to the cache directory.", show_default=True)
def cache(subcommand: str, cache_dir: str) -> None:
    """Manage the preprocessed-session cache.

    \b
    Subcommands:
      clear   Delete all cached files.
      stats   Print the number of entries and total size.
    """
    from track2data.cache.store import CacheStore

    store = CacheStore(Path(cache_dir))

    if subcommand == "clear":
        n = store.clear()
        click.echo(f"Cache cleared — {n} file(s) deleted from {cache_dir}.")

    elif subcommand == "stats":
        parquet_files = [
            f for pat in ("*.parquet", "*.pkl") for f in Path(cache_dir).rglob(pat)
        ]
        total_bytes = sum(f.stat().st_size for f in parquet_files)
        click.echo(
            f"Cache at {cache_dir}: "
            f"{len(parquet_files)} file(s), "
            f"{total_bytes / 1024:.1f} KiB"
        )


# ── new ───────────────────────────────────────────────────────────────────────


@cli.command()
@click.argument("name")
@click.option("--out", "-o", default=None,
              help="Output path (default: <name>.t2d.json).")
def new(name: str, out: str | None) -> None:
    """Scaffold an empty project manifest and write it to disk.

    Creates NAME.t2d.json (or --out path) with default preprocessing,
    no sessions, bodylength calibration, and no metrics selected.
    """
    from track2data.core.manifest import write as manifest_write
    from track2data.core.models import ProjectManifest

    now = datetime.now(tz=UTC)
    manifest = ProjectManifest(
        project_name=name,
        created_at=now,
        updated_at=now,
    )

    out_path = Path(out) if out else Path(f"{name}.t2d.json")
    if out_path.exists():
        click.confirm(
            f"{out_path} already exists. Overwrite?",
            abort=True,
        )

    try:
        manifest_write(manifest, out_path)
        click.echo(f"Created '{name}' manifest at {out_path}")
        click.echo("Next steps:")
        click.echo(
            "  1. Edit the manifest to add session folders "
            "(sessions[].folder)"
        )
        click.echo(
            "  2. Select metrics in metrics.individual / metrics.group / "
            "metrics.zone"
        )
        click.echo(f"  3. Run:  track2data run {out_path}")
    except Exception as exc:
        click.echo(f"[error] Failed to write manifest: {exc}", err=True)
        sys.exit(1)


# ── list-readers ──────────────────────────────────────────────────────────────

_VERIFICATION_NOTE = {
    "real_sample": "tested against real tracker output",
    "synthetic_only": "UNVERIFIED: written from the format's documentation, not yet checked "
    "against real output",
}


def _reader_facts(cls: type[SessionReader]) -> dict[str, Any]:
    return {
        "name": cls.name,
        "display_name": cls.display_name or cls.name,
        "priority": cls.priority,
        "verification": cls.verification,
        "accepts_allow_pickle": cls.accepts_allow_pickle,
        "parameters": [p.model_dump(mode="json") for p in cls.parameters],
    }


@cli.command("list-readers")
@click.option("--json", "as_json", is_flag=True, default=False, help="Machine-readable output.")
def list_readers(as_json: bool) -> None:
    """List the registered readers: which software each reads and what it must be told."""
    import json

    from track2data.readers import get_reader, reader_names

    facts = [_reader_facts(get_reader(name)) for name in reader_names()]
    if as_json:
        click.echo(json.dumps(facts, indent=2))
        return
    click.echo("Registered readers (highest priority first):")
    for f in facts:
        options = ", ".join(
            f"{p['name']}*" if p["required"] else p["name"] for p in f["parameters"]
        )
        click.echo(
            f"  {f['name']:<18}{f['display_name']:<30}{f['verification']:<16}"
            f"{options or '(no options)'}"
        )
    click.echo("  * = required: the files do not record it, so it has to be given.")


# ── scan / add ────────────────────────────────────────────────────────────────

_LISTED = 8


def _detection_json(d: Detection) -> dict[str, Any]:
    return {
        "reader": d.reader,
        "display_name": d.display_name,
        "confidence": d.confidence.name,
        "verification": d.verification,
        "evidence": list(d.evidence),
        "parameters": [p.model_dump(mode="json") for p in d.parameters],
        "proposed": {k: v.model_dump(mode="json") for k, v in d.proposed.items()},
        "sessions": [
            {"session_id": s.session_id, "source": str(s.source), "warnings": list(s.warnings)}
            for s in d.sessions
        ],
    }


def _scan_json(result: ScanResult) -> dict[str, Any]:
    return {
        "roots": [str(r) for r in result.roots],
        "entries": result.entries,
        "seconds": round(result.seconds, 3),
        "truncated": result.truncated,
        "warnings": list(result.warnings),
        "file_types": dict(result.file_types),
        "recognised": [
            {
                "key": r.key,
                "display_name": r.display_name,
                "count": r.count,
                "example": str(r.example),
                "remediation": r.remediation,
            }
            for r in result.recognised
        ],
        "groups": [
            {"index": i + 1, "detections": [_detection_json(d) for d in g.detections]}
            for i, g in enumerate(result.groups)
        ],
    }


def _names(ids: list[str]) -> str:
    shown = ", ".join(ids[:_LISTED])
    return f"{shown}, and {len(ids) - _LISTED} more" if len(ids) > _LISTED else shown


def _echo_scan_header(result: ScanResult) -> None:
    click.echo(f"Scanned {result.entries} entries in {result.seconds:.1f} s.")
    if result.truncated:
        click.echo("[warn] The scan stopped at its budget; the folder may hold more.", err=True)
    for warning in result.warnings:
        click.echo(f"[warn] {warning}", err=True)


def _echo_nothing_found(result: ScanResult) -> None:
    roots = ", ".join(str(r) for r in result.roots)
    click.echo(f"No tracking output was recognised in {roots}.")
    for found in result.recognised:
        click.echo(f"Found {found.display_name} x{found.count}: {found.remediation}")
    if result.file_types:
        seen = ", ".join(f"{ext or '(none)'} x{n}" for ext, n in sorted(result.file_types.items()))
        click.echo(f"Files seen: {seen}")
    click.echo("Folders are searched 4 levels deep; use --max-depth N for a deeper tree.")
    click.echo("See `track2data list-readers` for what can be read.")


def _echo_detection(d: Detection, *, label: str) -> None:
    ids = [s.session_id for s in d.sessions]
    click.echo(
        f"{label} {d.display_name}  -  {d.confidence.name} confidence  -  {len(ids)} sessions"
    )
    note = _VERIFICATION_NOTE.get(d.verification, d.verification)
    click.echo(f"    reader:    {d.reader} ({note})")
    for line in d.evidence:
        click.echo(f"    why:       {line}")
    click.echo(f"    sessions:  {_names(ids)}")
    needed = [p for p in d.parameters if p.required and p.name not in d.proposed]
    if needed:
        click.echo("    needs:     " + ", ".join(f"{p.name} ({p.label})" for p in needed))


@cli.command()
@click.argument("roots", nargs=-1, required=True, type=click.Path(exists=True))
@click.option("--max-depth", type=int, default=None,
              help="Directory levels to look into (default 4).")
@click.option("--json", "as_json", is_flag=True, default=False, help="Machine-readable output.")
def scan(roots: tuple[str, ...], max_depth: int | None, as_json: bool) -> None:
    """Look at ROOTS and say which tracking software wrote what is in them.

    Read-only: nothing is opened except file headers, and nothing is unpickled. This is the
    first step of adding sessions; `track2data add` does the rest.
    """
    import json

    from track2data.api import Engine
    from track2data.readers.index import ScanBudget

    budget = ScanBudget(max_depth=max_depth) if max_depth is not None else None
    result = Engine.scan([Path(r) for r in roots], budget=budget)
    if as_json:
        click.echo(json.dumps(_scan_json(result), indent=2))
        return
    _echo_scan_header(result)
    if not result.groups:
        _echo_nothing_found(result)
        return
    for i, group in enumerate(result.groups, start=1):
        _echo_detection(group.best, label=f"[{i}]")
        others = [f"{d.display_name} ({d.confidence.name})" for d in group.detections[1:]]
        if others:
            click.echo(f"    also recognised by: {', '.join(others)}")


def _echo_plan(draft: ConfirmDraft) -> None:
    group = draft.result.groups[draft.group_index]
    detection = next(d for d in group.detections if d.reader == draft.reader)
    _echo_detection(detection, label="Detected:" if draft.chosen_by == "detected" else "Chosen:")
    shared = draft.options
    if shared:
        click.echo("    options:   " + ", ".join(f"{k}={v}" for k, v in sorted(shared.items())))
    for row in draft.rows:
        note = (
            "  (already in the project)" if row.already_added
            else "" if row.included else "  (left out)"
        )
        click.echo(f"      {row.session_id:<28}<- {row.source}{note}")


@cli.command()
@click.argument("project", type=click.Path(exists=True, dir_okay=False))
@click.argument("roots", nargs=-1, required=True, type=click.Path(exists=True))
@click.option("--group", "group_number", type=int, default=1,
              help="Which detected group to add, as numbered by `scan` (default 1, the best).")
@click.option("--reader", default=None,
              help="Read it with this reader instead of the suggestion "
                   "(one of those that recognised it).")
@click.option("--option", "options", multiple=True, metavar="NAME=VALUE",
              help="An option the files do not record, e.g. --option fps=30 (repeatable).")
@click.option("--exclude", "excluded", multiple=True, metavar="ID",
              help="Leave this session out (repeatable).")
@click.option("--rename", "renames", multiple=True, metavar="OLD=NEW",
              help="Call a session something else in the project (repeatable).")
@click.option("--max-depth", type=int, default=None,
              help="Directory levels to look into (default 4).")
@click.option("--yes", "-y", is_flag=True, default=False, help="Do not ask for confirmation.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Show what would be added; add nothing.")
def add(
    project: str,
    roots: tuple[str, ...],
    group_number: int,
    reader: str | None,
    options: tuple[str, ...],
    excluded: tuple[str, ...],
    renames: tuple[str, ...],
    max_depth: int | None,
    yes: bool,
    dry_run: bool,
) -> None:
    """Scan ROOTS, confirm which software wrote them, and add their sessions to PROJECT.

    The same steps as the app: the suggestion is shown, you can amend it (--reader, --option,
    --exclude, --rename), and nothing is added until you confirm (or pass --yes). The reader
    and its options are saved on each session, so the project never has to guess again.
    """
    from track2data.api import Engine
    from track2data.core.errors import Track2DataError
    from track2data.core.manifest import write as manifest_write
    from track2data.readers.confirm import ConfirmDraft
    from track2data.readers.index import ScanBudget
    from track2data.readers.params import parse_assignments

    manifest = _load_manifest(project)
    budget = ScanBudget(max_depth=max_depth) if max_depth is not None else None
    result = Engine.scan([Path(r) for r in roots], budget=budget)
    _echo_scan_header(result)
    draft = ConfirmDraft(result, existing=manifest.sessions)
    if draft.is_empty:
        _echo_nothing_found(result)
        sys.exit(1)

    try:
        draft.select_group(group_number - 1)
        if reader is not None:
            draft.select_reader(reader)
        shared = [p for p in draft.parameters if p.scope == "group"]
        for name, value in parse_assignments(shared, options, reader=draft.reader).items():
            draft.set_option(name, value)
        for session_id in excluded:
            draft.set_included(session_id, False)
        for item in renames:
            old, separator, new = item.partition("=")
            if not separator or not old or not new:
                raise ValueError(f"--rename {item!r} is not of the form OLD=NEW")
            draft.rename(old, new)
    except KeyError as exc:
        click.echo(f"[error] {exc.args[0]}", err=True)
        sys.exit(1)
    except (ValueError, Track2DataError) as exc:
        click.echo(f"[error] {exc}", err=True)
        sys.exit(1)

    _echo_plan(draft)
    rows = draft.rows
    if rows and all(row.already_added for row in rows):
        click.echo(f"Nothing to add: all {len(rows)} sessions found are already in the project.")
        sys.exit(1)
    problems = draft.problems()
    if problems:
        for problem in problems:
            click.echo(f"[problem] {problem.message}", err=True)
        if any(p.code == "OPTION_MISSING" for p in problems):
            click.echo("Give each with --option NAME=VALUE, e.g. --option fps=30.", err=True)
        sys.exit(1)
    chosen = [row for row in rows if row.included]
    if dry_run:
        click.echo(f"Dry run: would add {len(chosen)} session(s); nothing was changed.")
        return
    if not yes:
        click.confirm(f"Add {len(chosen)} session(s) to {project}?", abort=True)
    refs = draft.to_session_refs()
    updated = manifest.model_copy(
        update={
            "sessions": [*manifest.sessions, *refs],
            "updated_at": datetime.now(tz=UTC),
        }
    )
    manifest_write(updated, Path(project))
    click.echo(f"Added {len(refs)} session(s) to {project}.")


# ── entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    cli()


# ── sensitivity ───────────────────────────────────────────────────────────────


@cli.command()
@click.argument("project", type=click.Path(exists=True, dir_okay=False))
@click.option("--out-dir", "-o", default="sensitivity",
              help="Output directory (default: ./sensitivity).")
@click.option("--smoothing-windows", default=None,
              help="Comma-separated odd window sizes (default: 3,5,9,15).")
@click.option("--max-gap-frames", "gap_frames", default=None,
              help="Comma-separated gap limits (default: 5,15,30,60).")
@click.option("--metric", "-m", "metric_ids", multiple=True,
              help="Restrict to these metric IDs (repeatable).")
def sensitivity(
    project: str,
    out_dir: str,
    smoothing_windows: str | None,
    gap_frames: str | None,
    metric_ids: tuple[str, ...],
) -> None:
    """Recompute metrics across a grid of preprocessing settings.

    Answers the question a reviewer will ask: how much of this result is the
    animals, and how much is the smoothing window? Writes the raw sweep and
    a per-column summary of how far each value moved.

    The summary's headline is the coefficient of variation, which is
    unitless and so comparable across columns in different units. Where the
    line between "robust" and "not" sits depends on the effect size being
    claimed, so no verdict is printed -- only the number.
    """
    from track2data.api import Engine
    from track2data.sensitivity import SensitivityGrid, run_sensitivity, summarise

    manifest = _load_manifest(project)
    engine = Engine(manifest)
    _refuse_3d_sensitivity(engine)

    def _ints(raw: str | None, default: tuple[int, ...]) -> tuple[int, ...]:
        if raw is None:
            return default
        return tuple(int(part) for part in raw.split(",") if part.strip())

    grid = SensitivityGrid(
        smoothing_windows=_ints(smoothing_windows, (3, 5, 9, 15)),
        max_gap_frames=_ints(gap_frames, (5, 15, 30, 60)),
        metric_ids=list(metric_ids),
    )

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    n_points = len(grid.points())
    frames = []
    for ref in manifest.sessions:
        click.echo(f"Sweeping {ref.session_id} over {n_points} settings...")
        try:
            session = engine.import_ref(ref)
        except Exception as exc:
            click.echo(f"[warn] {ref.session_id}: {exc}", err=True)
            continue
        frames.append(run_sensitivity(engine, session, grid))

    if not frames:
        click.echo("No sessions could be read; nothing written.", err=True)
        sys.exit(1)

    import pandas as pd

    sweep = pd.concat(frames, ignore_index=True)
    sweep.to_csv(out_path / "sensitivity.csv", index=False, encoding="utf-8")

    summary = summarise(sweep)
    summary.to_csv(out_path / "sensitivity_summary.csv", index=False, encoding="utf-8")

    click.echo(f"\nWrote {out_path / 'sensitivity.csv'}")
    click.echo(f"Wrote {out_path / 'sensitivity_summary.csv'}")

    if not summary.empty:
        click.echo("\nMost setting-dependent columns (coefficient of variation):")
        for _, row in summary.head(10).iterrows():
            click.echo(
                f"  {row['cv']:>7.3f}  {row['metric_id']:<6} {row['column']} "
                f"({row['unit']})"
            )
        click.echo(
            "\nA value near 0 means the preprocessing choice barely moved that "
            "column.\nA large one means the number is substantially a statement "
            "about the settings."
        )

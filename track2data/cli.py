"""track2data command-line interface.

Provides headless access to the full Track2Data pipeline.

Commands
--------
run          Run the full pipeline for a project manifest.
validate     Validate schema and check reachability without running.
list-metrics Print all registered metric IDs and descriptions.
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
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from track2data.core.models import ProjectManifest

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
def run(project: str, out_dir: str | None, exporters: tuple[str, ...]) -> None:
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

    # Validate before running.
    engine = Engine(manifest)
    issues = engine.validate()
    if issues:
        for issue in issues:
            click.echo(f"[warn] {issue}", err=True)

    exporter_list = list(exporters) if exporters else None

    click.echo(
        f"Running project '{manifest.project_name}' "
        f"({len(manifest.sessions)} session(s))…"
    )

    try:
        result = engine.run(out_path, exporters=exporter_list)
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

    Exits with code 0 when the manifest is valid, 1 otherwise.
    """
    from track2data.api import Engine

    manifest = _load_manifest(project)
    engine = Engine(manifest)
    issues = engine.validate()

    if not issues:
        click.echo(f"OK — '{manifest.project_name}' is ready to run.")
    else:
        for issue in issues:
            click.echo(f"[issue] {issue}", err=True)
        sys.exit(1)


# ── list-metrics ──────────────────────────────────────────────────────────────


def _natural_sort_key(metric_cls):
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

    click.echo(
        f"{'ID':<{id_w}}  {'LEVEL':<{lvl_w}}  NAME"
    )
    click.echo("-" * (id_w + lvl_w + 30))
    for m in metrics:
        label = getattr(m, "label", getattr(m, "name", ""))
        click.echo(f"{m.id:<{id_w}}  {m.level:<{lvl_w}}  {label}")


# ── cache ─────────────────────────────────────────────────────────────────────


@cli.command()
@click.argument("subcommand", type=click.Choice(["clear", "stats"]))
@click.option("--cache-dir", default=".t2d_cache",
              help="Path to the cache directory.", show_default=True)
def cache(subcommand: str, cache_dir: str) -> None:
    """Manage the preprocessed-session cache.

    \b
    Subcommands:
      clear   Delete all cached Parquet files.
      stats   Print the number of entries and total size.
    """
    from track2data.cache.store import CacheStore

    store = CacheStore(Path(cache_dir))

    if subcommand == "clear":
        n = store.clear()
        click.echo(f"Cache cleared — {n} file(s) deleted from {cache_dir}.")

    elif subcommand == "stats":
        parquet_files = list(Path(cache_dir).rglob("*.parquet"))
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


# ── entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    cli()

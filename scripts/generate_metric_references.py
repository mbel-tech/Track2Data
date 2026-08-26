"""
Regenerate ``docs/METRIC_REFERENCES.csv`` from the metric registry.

Each metric's ``documentation.citation`` / ``documentation.citation_doi``
in the code is the single source of truth; this script only publishes
them in a citable, spreadsheet-readable form. Never hand-edit the CSV --
edit the metric's ``MetricDocumentation`` and re-run this.

``tests/test_metric_references_consistency.py`` fails if the committed
CSV and a fresh regeneration differ, so adding or changing a metric
without re-running this is caught in CI rather than silently publishing
a stale reference list.

Usage::

    python scripts/generate_metric_references.py           # rewrite the CSV
    python scripts/generate_metric_references.py --check   # exit 1 if stale
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from pathlib import Path

from track2data.metrics.references import Reference

REPO_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = REPO_ROOT / "docs" / "METRIC_REFERENCES.csv"
BIB_PATH = REPO_ROOT / "docs" / "references.bib"

HEADER = [
    "metric_id",
    "level",
    "priority",
    "metric_name",
    "reference",
    "doi",
    "supporting_references",
]

# Every module that registers built-in metrics. `metrics._load_builtins()`
# imports each of these under `contextlib.suppress(ImportError)`, which is
# right for the library (a user without scipy can still run the metrics
# that don't need it) and wrong for this script: a partly-loaded registry
# would publish a CSV that quietly omits whole levels.
_BUILTIN_METRIC_MODULES = (
    "track2data.metrics.diagnostic",
    "track2data.metrics.individual",
    "track2data.metrics.group",
    "track2data.metrics.zone",
)


def assert_registry_is_complete() -> None:
    """Exit with a diagnosis unless every built-in metric module imported.

    Without this, running the script on a venv missing scipy or shapely
    rewrites the published CSV with whole levels of metrics deleted --
    and prints a success line while doing it. CI's drift test would fail
    later, but by then the damage is committed and the cause is
    invisible. Fail here, where the missing dependency can still be
    named.
    """
    import importlib

    for module_name in _BUILTIN_METRIC_MODULES:
        try:
            importlib.import_module(module_name)
        except ImportError as exc:
            raise SystemExit(
                f"cannot regenerate {CSV_PATH.name}: {module_name} failed to import "
                f"({exc}).\n"
                "The metric registry would be incomplete and the CSV would silently "
                "lose every metric from that module.\n"
                "Install the full dev environment first:  pip install -e \".[dev]\""
            ) from exc


def render_csv() -> str:
    """Return the full CSV text for the current metric registry.

    Written with an explicit "\\n" lineterminator rather than csv's
    "\\r\\n" default so the committed file has one canonical form on
    every platform -- otherwise the drift test would fail on Windows
    against a file generated on Linux, or vice versa.
    """
    # Imported here, not at module scope, so `--help` works even if an
    # optional metric dependency (scipy, shapely) is missing.
    from track2data import metrics

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(HEADER)

    from track2data.metrics.references import format_supporting_references

    for metric_id in metrics.all_ids():
        metric_cls = metrics.get(metric_id)
        doc = metric_cls.documentation
        supporting = format_supporting_references(doc.supporting_references)
        writer.writerow(
            [
                metric_cls.id,
                metric_cls.level,
                metric_cls.priority,
                metric_cls.label,
                doc.citation or "",
                doc.citation_doi or "",
                supporting,
            ]
        )

    return buffer.getvalue()


def _bibtex_entry(ref: Reference) -> str:
    """Render one ``Reference`` as a BibTeX entry."""
    fields = [("author", ref.author), ("title", ref.title), ("year", str(ref.year))]
    if ref.journal:
        fields.append(("journal", ref.journal))
    if ref.volume:
        fields.append(("volume", ref.volume))
    if ref.pages:
        fields.append(("pages", ref.pages))
    if ref.publisher:
        fields.append(("publisher", ref.publisher))
    if ref.doi:
        fields.append(("doi", ref.doi))

    body = ",\n".join(f"  {name} = {{{value}}}" for name, value in fields)
    return f"@{ref.entry_type}{{{ref.key},\n{body}\n}}"


def render_bib() -> str:
    """Return the full BibTeX text for every ``Reference`` reachable from
    the current metric registry -- primary and supporting alike.

    Walking the registry (rather than importing ``references.py`` and
    dumping every module-level ``Reference``) means an unused entry in
    that module -- e.g. one whose metric assignment was reverted --
    quietly drops out of the published bibliography instead of being
    published as though something still cited it.
    """
    from track2data import metrics

    seen: dict[str, object] = {}
    for metric_id in metrics.all_ids():
        doc = metrics.get(metric_id).documentation
        for ref in ([doc.primary_reference] if doc.primary_reference else []) + list(
            doc.supporting_references
        ):
            seen[ref.key] = ref

    entries = [_bibtex_entry(seen[key]) for key in sorted(seen)]
    return "\n\n".join(entries) + "\n" if entries else ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if the committed CSV is stale, without rewriting it",
    )
    args = parser.parse_args()

    assert_registry_is_complete()
    generated_csv = render_csv()
    generated_bib = render_bib()

    if args.check:
        stale = []
        current_csv = CSV_PATH.read_text(encoding="utf-8") if CSV_PATH.exists() else ""
        if current_csv != generated_csv:
            stale.append(CSV_PATH.relative_to(REPO_ROOT))
        current_bib = BIB_PATH.read_text(encoding="utf-8") if BIB_PATH.exists() else ""
        if current_bib != generated_bib:
            stale.append(BIB_PATH.relative_to(REPO_ROOT))
        if stale:
            names = ", ".join(str(p) for p in stale)
            print(f"{names} out of date; re-run without --check")
            return 1
        print(
            f"{CSV_PATH.relative_to(REPO_ROOT)} and "
            f"{BIB_PATH.relative_to(REPO_ROOT)} are up to date"
        )
        return 0

    CSV_PATH.write_text(generated_csv, encoding="utf-8", newline="")
    BIB_PATH.write_text(generated_bib, encoding="utf-8", newline="")
    row_count = generated_csv.count("\n") - 1
    print(f"wrote {CSV_PATH.relative_to(REPO_ROOT)} ({row_count} metrics)")
    print(f"wrote {BIB_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

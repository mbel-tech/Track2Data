"""
``docs/METRIC_REFERENCES.csv`` is generated from the metric registry --
it must never drift from the code that produces it.

This is a provenance-correctness test, not a tidiness one, for the same
reason as ``test_version_consistency.py``. The CSV is the published,
citable list of the scientific reference behind every metric
Track2Data computes; a researcher reads it to know what to cite in a
paper. `Metric.documentation.citation` in the code is the single source
of truth, so if someone adds a metric, changes a citation, or corrects
a DOI without regenerating the CSV, the published references would
silently describe a different set of metrics than the ones that
actually run -- with nothing failing to indicate it.

Regenerating is one command::

    python scripts/generate_metric_references.py
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from track2data import metrics

REPO_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = REPO_ROOT / "docs" / "METRIC_REFERENCES.csv"
GENERATOR_PATH = REPO_ROOT / "scripts" / "generate_metric_references.py"

EXPECTED_HEADER = ["metric_id", "level", "priority", "metric_name", "reference", "doi"]


def _load_generator():
    """Load the generator by path rather than importing `scripts.…`.

    `scripts/` is a repo-local dev directory, deliberately not one of
    the wheel packages (pyproject's `tool.hatch.build.targets.wheel`),
    so it isn't importable from an installed Track2Data -- which is
    exactly how CI runs the suite.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("_generate_metric_references", GENERATOR_PATH)
    assert spec is not None and spec.loader is not None, f"cannot load {GENERATOR_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _committed_rows() -> list[dict[str, str]]:
    with CSV_PATH.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def test_the_csv_exists_and_has_the_documented_columns() -> None:
    assert CSV_PATH.exists(), f"{CSV_PATH} is missing; run scripts/generate_metric_references.py"

    with CSV_PATH.open(encoding="utf-8", newline="") as fh:
        header = next(csv.reader(fh))

    assert header == EXPECTED_HEADER


def test_regenerating_the_csv_is_byte_identical_to_the_committed_file() -> None:
    """The drift guard. If this fails, the code and the published CSV
    disagree -- regenerate rather than hand-editing the CSV."""
    committed = CSV_PATH.read_text(encoding="utf-8")
    regenerated = _load_generator().render_csv()

    assert regenerated == committed, (
        "docs/METRIC_REFERENCES.csv is out of date with the metric registry. "
        "Run: python scripts/generate_metric_references.py"
    )


def test_every_registered_metric_has_a_row() -> None:
    rows_by_id = {row["metric_id"]: row for row in _committed_rows()}
    missing = [mid for mid in metrics.all_ids() if mid not in rows_by_id]

    assert not missing, (
        f"registered metrics with no row in METRIC_REFERENCES.csv: {', '.join(missing)}. "
        "Run: python scripts/generate_metric_references.py"
    )


def test_no_orphan_rows_for_unregistered_metrics() -> None:
    registered = set(metrics.all_ids())
    orphans = [row["metric_id"] for row in _committed_rows() if row["metric_id"] not in registered]

    assert not orphans, (
        f"METRIC_REFERENCES.csv has rows for metrics that are no longer registered: "
        f"{', '.join(orphans)}. Run: python scripts/generate_metric_references.py"
    )


def test_every_metric_declares_a_citation() -> None:
    """A metric with no citation at all publishes an empty reference
    cell -- which reads as "this measure has no scientific basis"
    rather than "we haven't written one down yet". Every metric must
    say something, even if that something is an honest "standard
    kinematics; no single originating work"."""
    uncited = [
        mid
        for mid in metrics.all_ids()
        if not (metrics.get(mid).documentation.citation or "").strip()
    ]

    assert not uncited, f"metrics with no citation: {', '.join(uncited)}"


def test_every_declared_doi_looks_like_a_doi() -> None:
    """Catches a citation text accidentally pasted into the DOI field,
    or a full https://doi.org/... URL where the bare DOI belongs."""
    import re

    bad = [
        (mid, doi)
        for mid in metrics.all_ids()
        if (doi := metrics.get(mid).documentation.citation_doi)
        and not re.fullmatch(r"10\.\d{4,9}/\S+", doi)
    ]

    assert not bad, (
        "citation_doi values that aren't a bare DOI (expected '10.xxxx/...', "
        f"not a URL or free text): {bad}"
    )


def test_the_spec_reference_row_matches_the_code_citation() -> None:
    """``METRICS_SPEC.md`` restates each metric's reference inline, so
    a reader of the spec and a reader of the ⓘ dialog must not be shown
    different sources. Before this test the two disagreed on 14 of 33
    metrics -- including GL-1, where the spec named Pitcher 1973 while
    the code cited Couzin et al. 2002 with a DOI copy-pasted from
    another metric."""
    import re

    spec = (REPO_ROOT / "docs" / "METRICS_SPEC.md").read_text(encoding="utf-8")

    heading = re.compile(r"^#### ([A-Z]+-\d+)\s", re.MULTILINE)
    mismatches: list[str] = []

    for match in heading.finditer(spec):
        metric_id = match.group(1)
        metric_cls = metrics.get(metric_id)
        if metric_cls is None:
            continue

        section = spec[match.end() : match.end() + 4000]
        row = re.search(r"^\| \*\*Reference\*\* \| (.*?) \|$", section, re.MULTILINE)
        if row is None:
            mismatches.append(f"{metric_id}: spec section has no Reference row")
            continue

        doc = metric_cls.documentation
        expected = doc.citation or ""
        if doc.citation_doi:
            expected += f" — DOI [{doc.citation_doi}](https://doi.org/{doc.citation_doi})"

        if row.group(1) != expected:
            mismatches.append(
                f"{metric_id}:\n  spec: {row.group(1)}\n  code: {expected}"
            )

    assert not mismatches, "METRICS_SPEC.md disagrees with the code:\n" + "\n".join(mismatches)


def test_every_metric_has_a_spec_section() -> None:
    """METRICS_SPEC.md §6.6 requires a section per metric. D-6..D-9
    shipped without one, so the doc silently described 29 of the 33
    metrics that actually run."""
    import re

    spec = (REPO_ROOT / "docs" / "METRICS_SPEC.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"^#### ([A-Z]+-\d+)\s", spec, re.MULTILINE))
    missing = [mid for mid in metrics.all_ids() if mid not in documented]

    assert not missing, (
        f"metrics with no '#### <ID> — ...' section in METRICS_SPEC.md: {', '.join(missing)}"
    )


def test_no_doi_is_shared_by_metrics_citing_different_works() -> None:
    """Regression: GL-1 (Nearest-Neighbour Distance) used to carry
    Couzin et al. 2002's DOI while its own citation text named a
    different paper entirely -- the DOI had been copy-pasted from
    GL-3/GL-8. Reusing one DOI across metrics is legitimate when they
    genuinely cite the same work; it is a bug when the citation texts
    disagree."""
    by_doi: dict[str, set[str]] = {}
    for mid in metrics.all_ids():
        doc = metrics.get(mid).documentation
        if doc.citation_doi:
            by_doi.setdefault(doc.citation_doi, set()).add(doc.citation or "")

    conflicts = {doi: texts for doi, texts in by_doi.items() if len(texts) > 1}

    assert not conflicts, (
        f"the same DOI is attached to metrics whose citation texts differ: {conflicts}"
    )


def test_generator_refuses_to_write_a_truncated_csv() -> None:
    """`metrics._load_builtins()` wraps each submodule import in
    `contextlib.suppress(ImportError)`, so on a venv missing scipy or
    shapely the registry silently holds 23 metrics instead of 33 --
    and the generator would cheerfully rewrite the published CSV with
    ten rows deleted, printing a reassuring success line. CI catches
    the drift afterwards, but the damage is done locally and the
    contributor has no idea why.

    The generator must therefore verify its own inputs are complete
    before writing anything.
    """
    generator = _load_generator()

    assert hasattr(generator, "assert_registry_is_complete"), (
        "the generator must verify the registry is complete before writing"
    )


def test_generator_completeness_check_names_the_missing_module(monkeypatch) -> None:
    """Simulates the minimal-venv case: shapely absent, so
    track2data.metrics.zone won't import and every Z-* row would vanish
    from the CSV."""
    import importlib

    generator = _load_generator()
    real_import_module = importlib.import_module

    def _fail_zone(name, *args, **kwargs):
        if name == "track2data.metrics.zone":
            raise ImportError("No module named 'shapely'")
        return real_import_module(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", _fail_zone)

    with pytest.raises(SystemExit) as excinfo:
        generator.assert_registry_is_complete()

    message = str(excinfo.value)
    assert "track2data.metrics.zone" in message
    assert "shapely" in message
    assert "pip install" in message  # tells the contributor how to fix it


def test_generator_completeness_check_passes_on_a_full_environment() -> None:
    """The guard must not cry wolf in the environment CI actually uses."""
    _load_generator().assert_registry_is_complete()

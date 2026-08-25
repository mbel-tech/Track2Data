"""
The "Request a metric" issue form must stay usable and must keep
speaking the engine's own vocabulary.

`.github/ISSUE_TEMPLATE/metric_request.yml` collects exactly the fields
a `MetricDocumentation` needs, so a submitted request arrives
pre-shaped for implementation. Its "Metric type" dropdown therefore has
to offer exactly the four values of `Metric.level` -- if someone adds a
fifth level to the engine, or renames one, a request submitted against
the stale form would name a level that doesn't exist.

GitHub validates these files only when rendering them on github.com,
where a malformed form silently falls back to a blank issue. That is
why this is a test rather than something noticed at review time.
"""

from __future__ import annotations

import typing
from pathlib import Path

# A hard import, not pytest.importorskip: pyyaml is a declared dev
# dependency (pyproject.toml). An importorskip here would turn "the CI
# image is missing pyyaml" into "all these checks silently pass".
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = REPO_ROOT / ".github" / "ISSUE_TEMPLATE"
METRIC_REQUEST = TEMPLATE_DIR / "metric_request.yml"

# The block types GitHub's issue-form schema accepts.
VALID_TYPES = {"markdown", "input", "textarea", "dropdown", "checkboxes"}


def _form() -> dict:
    with METRIC_REQUEST.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_the_metric_request_form_exists_and_parses() -> None:
    assert METRIC_REQUEST.exists()
    form = _form()
    assert form["name"]
    assert form["description"]
    assert form["body"]


def test_the_form_is_labelled_and_title_prefixed() -> None:
    """The label is what `metric-request-check.yml` keys off; without it
    the DOI check never runs on these issues."""
    form = _form()
    assert "metric-request" in form["labels"]
    assert form["title"].startswith("[Metric]")


def test_every_block_uses_a_valid_type() -> None:
    for block in _form()["body"]:
        assert block["type"] in VALID_TYPES, f"unknown block type: {block['type']}"


def test_markdown_blocks_carry_no_id_or_validations() -> None:
    """GitHub rejects the whole form if a markdown block has either."""
    for block in _form()["body"]:
        if block["type"] == "markdown":
            assert "id" not in block
            assert "validations" not in block


def test_field_ids_are_unique() -> None:
    ids = [b["id"] for b in _form()["body"] if "id" in b]
    assert len(ids) == len(set(ids)), f"duplicate field ids: {ids}"


def test_the_three_mandated_fields_are_present_and_required() -> None:
    """Metric type, metric name, and a DOI -- the three the request was
    specified to collect. All three must be required, or the form can
    produce a request with nothing to act on."""
    form = _form()
    required = {
        b["id"] for b in form["body"] if b.get("validations", {}).get("required") is True
    }
    assert {"metric_type", "metric_name", "citation_doi"} <= required


def test_the_metric_type_dropdown_matches_metric_level_exactly() -> None:
    """One option per `Metric.level` value, in the same order, each
    labelled with the engine's own term first so a submission maps 1:1
    onto the vocabulary the code uses."""
    from track2data.metrics.base import Metric

    # get_type_hints, not __annotations__: the module uses
    # `from __future__ import annotations`, so the raw annotation is a
    # string and get_args() would return ().
    levels = list(typing.get_args(typing.get_type_hints(Metric)["level"]))
    assert levels, "could not resolve Metric.level's Literal values"

    dropdown = next(b for b in _form()["body"] if b["type"] == "dropdown")
    options = dropdown["attributes"]["options"]

    # Options read "Individual — one value per animal (...)"; the part
    # before the dash is the engine's own level name.
    offered = [opt.split("—")[0].strip().lower() for opt in options]

    assert offered == levels, (
        f"the form's Metric type dropdown ({offered}) has drifted from "
        f"Metric.level ({levels})"
    )


def test_the_doi_field_asks_for_a_bare_doi() -> None:
    """Issue forms have no regex validation, so the wording is the only
    thing steering people away from pasting a URL. The placeholder must
    show a bare DOI, since that is what people copy."""
    doi_field = next(b for b in _form()["body"] if b.get("id") == "citation_doi")
    attrs = doi_field["attributes"]

    assert "DOI" in attrs["label"]
    assert attrs["placeholder"].startswith("10.")
    assert "/" in attrs["placeholder"]


def test_blank_issues_stay_enabled() -> None:
    """Adding this form must not take away the plain "open an issue"
    path -- CONTRIBUTING.md §9 sends bug reports through it."""
    config = TEMPLATE_DIR / "config.yml"
    assert config.exists()
    with config.open(encoding="utf-8") as fh:
        assert yaml.safe_load(fh)["blank_issues_enabled"] is True


def test_the_doi_check_workflow_regex_accepts_and_rejects_the_right_things() -> None:
    """The workflow's DOI regex is the second layer behind the form's
    wording (issue forms can't validate a pattern). Pinned here because
    it lives inside a JS string in YAML, where nothing else would catch
    a typo until a real submission was mislabelled."""
    import re

    workflow = (REPO_ROOT / ".github" / "workflows" / "metric-request-check.yml").read_text(
        encoding="utf-8"
    )
    match = re.search(r"const hasDoi = /(.+?)/\.test\(body\);", workflow)
    assert match is not None, "could not find the DOI regex in the workflow"

    pattern = re.compile(match.group(1))

    assert pattern.search("10.1006/jtbi.2002.3065")
    assert pattern.search("The DOI is 10.1038/s41592-018-0295-5, thanks")
    assert pattern.search("https://doi.org/10.1016/j.jtbi.2004.03.016")

    assert not pattern.search("no doi here")
    assert not pattern.search("Couzin et al. 2002, J. Theor. Biol.")
    assert not pattern.search("10.1006")  # no suffix

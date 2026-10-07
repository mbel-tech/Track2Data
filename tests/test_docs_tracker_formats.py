"""The research files in docs/tracker-formats/ are pinned to the bytes supplied.

Reader specifications are written from these files, and a reader's fixtures are
chosen from ``tracker_test_datasets.csv``. If one of them changed silently, the
specs would drift away from the source they cite. To update a file on purpose:
re-copy it, then update its pin here and its row in
``docs/tracker-formats/README.md`` (a test below keeps the two in step).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[1] / "docs" / "tracker-formats"

#: file name -> sha256 of the exact bytes supplied.
PINNED = {
    "animal_tracking_output_formats.md": (
        "4b6832404c823c3c14c6c06cd27de377db7b5e08efa20d3f7e3c4f5d8828a308"
    ),
    "animal_tracking_formats_table.csv": (
        "9c9f3df70f04a821bf8e765f130e65c565f9499bd5dc3dec082b4720a606c0c1"
    ),
    "importer_priority.csv": (
        "b4307f31271f0781e1c84086a6773b1209e22832041da793b71a3c04d0819a7c"
    ),
    "tracker_test_datasets.csv": (
        "195247aaa0929773ab35a30a267699a06750167dc518675beca5f548ff4fc9d5"
    ),
}


@pytest.mark.parametrize("name", sorted(PINNED))
def test_research_file_is_byte_identical_to_the_supplied_copy(name: str) -> None:
    path = DOCS / name
    assert path.is_file(), f"{path} is missing"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == PINNED[name], (
        f"{name} no longer matches the supplied copy. If the change is deliberate, "
        "update PINNED here and the sha256 prefix in docs/tracker-formats/README.md."
    )


def test_readme_lists_every_pinned_file_with_its_hash_prefix() -> None:
    readme = (DOCS / "README.md").read_text(encoding="utf8")
    for name, digest in PINNED.items():
        assert f"`{name}`" in readme, f"README.md does not mention {name}"
        assert f"`{digest[:8]}…`" in readme, f"README.md has a stale hash prefix for {name}"


def test_priority_file_still_sums_to_the_cumulative_share_the_plan_quotes() -> None:
    """The rollout order and the "80.5 %" figure come from this file."""
    import csv

    with (DOCS / "importer_priority.csv").open(newline="", encoding="utf8") as handle:
        rows = list(csv.DictReader(handle))
    assert [r["priority"] for r in rows] == [str(i) for i in range(1, len(rows) + 1)]
    assert float(rows[-1]["cumulative_pct"]) == pytest.approx(80.5)
    assert sum(float(r["pct_of_animal_tracker_citations"]) for r in rows) == pytest.approx(
        80.5, abs=0.11
    )

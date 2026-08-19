"""Local-only R-parity smoke tests for the choice-pipeline fixtures.

These tests are skipped automatically in CI and whenever the fixture
files are absent (the data are externally sourced and not stored in the
repository — see tests/fixtures/r_outputs/from_choice_pipeline/README.md).

To run locally once fixtures are present:

    pytest tests/test_r_parity/test_choice_fixtures_local.py -v -m r_parity_local
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

pytestmark = [pytest.mark.r_parity, pytest.mark.r_parity_local]

FIXTURE_DIR = (
    Path(__file__).parent.parent / "fixtures" / "r_outputs" / "from_choice_pipeline"
)

EXPECTED_FILES: dict[str, list[str]] = {
    "trial_activity_summary.csv": ["trial_id", "timepoint", "total_time_s", "treatment"],
    "trial_occupancy_long.csv": ["trial_id", "timepoint", "zone", "prop_time"],
    "jump_detection_summary.csv": ["trial_id", "fish_id", "n_jumps"],
    "master_fish_by_frame_trial1_t1.csv": ["trial_id", "frame", "fish_id"],
}


def _all_fixtures_present() -> bool:
    return all((FIXTURE_DIR / name).exists() for name in EXPECTED_FILES)


# Applied at collection time — tests are skipped gracefully when files are absent.
pytestmark.append(
    pytest.mark.skipif(
        not _all_fixtures_present(),
        reason=(
            "Choice-pipeline fixtures not present locally (external/embargoed). "
            f"See {FIXTURE_DIR / 'README.md'} for setup instructions."
        ),
    )
)


@pytest.mark.parametrize("filename,required_cols", EXPECTED_FILES.items())
def test_fixture_columns_present(filename: str, required_cols: list[str]) -> None:
    """Each fixture file must contain the expected header columns."""
    path = FIXTURE_DIR / filename
    with path.open(newline="", encoding="utf-8") as fh:
        header = next(csv.reader(fh))
    for col in required_cols:
        assert col in header, (
            f"Column '{col}' missing from {filename}; found columns: {header}"
        )


@pytest.mark.parametrize("filename", EXPECTED_FILES)
def test_fixture_not_empty(filename: str) -> None:
    """Each fixture file must have at least one data row."""
    path = FIXTURE_DIR / filename
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        next(reader)  # skip header
        first_row = next(reader, None)
    assert first_row is not None, f"{filename} has a header but no data rows"

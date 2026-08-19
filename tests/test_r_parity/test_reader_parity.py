"""
R-parity tests for the reader layer.

These tests form the CI gate: a reader that passes here produces the same
per-session data that the R Step-1 pipeline would extract from identical
idtracker.ai output folders.

Strategy
────────
• The 'golden_reader_tiny_v5.csv' fixture documents expected values for
  the synthetic tiny_v5 session (created in conftest.py).
• Tests load that CSV, read the synthetic session, and compare field-by-field.
• Any discrepancy here means the reader is interpreting the trajectory or
  metadata files differently from the R pipeline — a real parity failure.

Numeric tolerance: float fields compared with atol=1e-9 (exact arithmetic
from simple linear / trigonometric formulas).
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from track2data.core.models import Session
from track2data.readers.idtrackerai_v5 import IDTrackerAiV5Reader

GOLDEN_CSV = Path(__file__).parent.parent / "fixtures" / "r_outputs" / "golden_reader_tiny_v5.csv"
ATOL = 1e-9

pytestmark = pytest.mark.r_parity


def _load_golden() -> dict[str, str]:
    with GOLDEN_CSV.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return {row["field"]: row["expected_value"] for row in reader}


@pytest.fixture(scope="module")
def session(tiny_v5_session: Path) -> Session:
    return IDTrackerAiV5Reader().read(tiny_v5_session)


@pytest.fixture(scope="module")
def golden() -> dict[str, str]:
    return _load_golden()


class TestReaderParity:
    """Each test checks one golden row against the Session produced by the reader."""

    def test_n_animals(self, session: Session, golden: dict) -> None:
        assert session.n_animals == int(golden["n_animals"])

    def test_n_frames(self, session: Session, golden: dict) -> None:
        assert session.n_frames == int(golden["n_frames"])

    def test_fps(self, session: Session, golden: dict) -> None:
        assert session.video.fps == pytest.approx(float(golden["fps"]), abs=ATOL)

    def test_width_px(self, session: Session, golden: dict) -> None:
        assert session.video.width_px == int(golden["width_px"])

    def test_height_px(self, session: Session, golden: dict) -> None:
        assert session.video.height_px == int(golden["height_px"])

    def test_trajectory_variant(self, session: Session, golden: dict) -> None:
        assert session.trajectory_variant == golden["trajectory_variant"]

    def test_has_stable_identities(self, session: Session, golden: dict) -> None:
        assert session.has_stable_identities is (golden["has_stable_identities"] == "True")

    def test_raw_xy_shape(self, session: Session, golden: dict) -> None:
        expected = tuple(int(x) for x in golden["raw_xy_shape"].strip("()").split(","))
        assert session.raw_xy.shape == expected

    def test_raw_xy_dtype(self, session: Session, golden: dict) -> None:
        assert str(session.raw_xy.dtype) == golden["raw_xy_dtype"]

    def test_frame0_animal0_x(self, session: Session, golden: dict) -> None:
        assert session.raw_xy[0, 0, 0] == pytest.approx(float(golden["frame0_animal0_x"]), abs=ATOL)

    def test_frame0_animal0_y(self, session: Session, golden: dict) -> None:
        assert session.raw_xy[0, 0, 1] == pytest.approx(float(golden["frame0_animal0_y"]), abs=ATOL)

    def test_frame0_animal1_x(self, session: Session, golden: dict) -> None:
        assert session.raw_xy[0, 1, 0] == pytest.approx(float(golden["frame0_animal1_x"]), abs=ATOL)

    def test_frame0_animal1_y(self, session: Session, golden: dict) -> None:
        assert session.raw_xy[0, 1, 1] == pytest.approx(float(golden["frame0_animal1_y"]), abs=ATOL)

    def test_frame0_animal2_x(self, session: Session, golden: dict) -> None:
        assert session.raw_xy[0, 2, 0] == pytest.approx(float(golden["frame0_animal2_x"]), abs=ATOL)

    def test_frame0_animal2_y(self, session: Session, golden: dict) -> None:
        assert session.raw_xy[0, 2, 1] == pytest.approx(float(golden["frame0_animal2_y"]), abs=ATOL)

    def test_frame0_animal3_x(self, session: Session, golden: dict) -> None:
        assert session.raw_xy[0, 3, 0] == pytest.approx(float(golden["frame0_animal3_x"]), abs=ATOL)

    def test_frame0_animal3_y(self, session: Session, golden: dict) -> None:
        assert session.raw_xy[0, 3, 1] == pytest.approx(float(golden["frame0_animal3_y"]), abs=ATOL)

    def test_frame19_animal0_x(self, session: Session, golden: dict) -> None:
        val = float(golden["frame19_animal0_x"])
        assert session.raw_xy[19, 0, 0] == pytest.approx(val, abs=ATOL)

    def test_gap_frame20_animal0_x(self, session: Session, golden: dict) -> None:
        val = float(golden["gap_frame20_animal0_x"])
        assert session.raw_xy[20, 0, 0] == pytest.approx(val, abs=ATOL)

    def test_gap_frame22_animal0_x(self, session: Session, golden: dict) -> None:
        val = float(golden["gap_frame22_animal0_x"])
        assert session.raw_xy[22, 0, 0] == pytest.approx(val, abs=ATOL)

    def test_gap_frame24_animal0_x(self, session: Session, golden: dict) -> None:
        val = float(golden["gap_frame24_animal0_x"])
        assert session.raw_xy[24, 0, 0] == pytest.approx(val, abs=ATOL)

    def test_frame25_animal0_x(self, session: Session, golden: dict) -> None:
        val = float(golden["frame25_animal0_x"])
        assert session.raw_xy[25, 0, 0] == pytest.approx(val, abs=ATOL)

    def test_body_length_is_none(self, session: Session, golden: dict) -> None:
        assert session.body_length_px is None

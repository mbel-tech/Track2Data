"""The run README says how many samples the water column left out of the 3-D metrics."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_integration.test_native_3d import _manifest, _native_project
from track2data.api import Engine
from track2data.core.models import WaterColumn


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _native_project(tmp_path_factory.mktemp("readme_outside"))


def _readme(project: Path, out: Path, session: str, water: WaterColumn | None) -> str:
    Engine(_manifest(project, water)).run(out, exporters=["csv_long", "readme"])
    return (out / session / "README.md").read_text(encoding="utf-8")


def test_the_readme_counts_the_samples_below_the_floor(project: Path, tmp_path: Path) -> None:
    # fish2 climbs to z = 22 cm; a floor at 20 cm leaves its last two frames outside
    text = _readme(project, tmp_path / "o", "fish2", WaterColumn(surface_z=0.0, floor_z=20.0))
    assert "| Samples outside the water column | 2 (left out of" in text


def test_the_readme_says_zero_when_nothing_is_outside(project: Path, tmp_path: Path) -> None:
    text = _readme(project, tmp_path / "o", "fish1", WaterColumn(surface_z=-1.0, floor_z=20.0))
    assert "| Samples outside the water column | 0 (left out of" in text


def test_the_readme_has_no_such_row_without_a_water_column(project: Path, tmp_path: Path) -> None:
    text = _readme(project, tmp_path / "o", "fish2", None)
    assert "Samples outside the water column" not in text

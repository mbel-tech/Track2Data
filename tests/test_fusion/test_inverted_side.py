"""A side camera mounted upside down: the surface is the larger image row."""

from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from track2data.core.models import FusionSettings
from track2data.fusion.align import side_horizontal_cm
from track2data.fusion.fuse import fuse

from .builders import make_pair, settings


def test_an_inverted_pair_of_rows_is_accepted() -> None:
    fs = FusionSettings(surface_row=300.0, floor_row=100.0, tank_height_cm=20.0)
    assert (fs.surface_row, fs.floor_row) == (300.0, 100.0)


@pytest.mark.parametrize("rows", [(100.0, 100.0)])
def test_the_same_row_for_surface_and_floor_is_still_refused(rows) -> None:
    with pytest.raises(ValidationError, match="surface_row and floor_row must differ"):
        FusionSettings(surface_row=rows[0], floor_row=rows[1], tank_height_cm=20.0)


def test_depth_of_an_inverted_view_counts_from_the_larger_row() -> None:
    top, side, pair = make_pair(fusion=settings(surface_row=300.0, floor_row=100.0))
    side.xy[:, 0, 1] = 280.0  # 20 px below the surface in the image's reverse direction
    fused = fuse(top, side, pair, same_video=False)
    np.testing.assert_allclose(fused.psess.depth[:, 0], 0.1)  # (280 - 300) / (100 - 300)


def test_an_inverted_view_mirrors_the_upright_depth() -> None:
    upright_top, upright_side, upright_pair = make_pair()
    inv_top, inv_side, inv_pair = make_pair(fusion=settings(surface_row=300.0, floor_row=100.0))
    up = fuse(upright_top, upright_side, upright_pair, same_video=False).psess.depth
    inv = fuse(inv_top, inv_side, inv_pair, same_video=False).psess.depth
    np.testing.assert_allclose(inv, 1.0 - up)


def test_outside_the_inverted_column_is_still_outside() -> None:
    top, side, pair = make_pair(fusion=settings(surface_row=300.0, floor_row=100.0))
    side.xy[0, 0, 1] = 350.0  # beyond the surface
    side.xy[1, 0, 1] = 50.0  # beyond the floor
    fused = fuse(top, side, pair, same_video=False)
    assert fused.report.n_outside_column == 2
    assert np.isnan(fused.psess.depth[:2, 0]).all()


def test_the_side_scale_does_not_change_sign_when_inverted() -> None:
    _, side, pair = make_pair()
    _, _, inv_pair = make_pair(fusion=settings(surface_row=300.0, floor_row=100.0))
    rows = np.arange(5)
    upright = side_horizontal_cm(side, pair, rows, [0, 1, 2])
    inverted = side_horizontal_cm(side, inv_pair, rows, [0, 1, 2])
    np.testing.assert_allclose(inverted, upright)

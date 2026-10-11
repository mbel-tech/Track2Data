"""The water column bounds z for every 3-D metric, not only IL-15."""

from __future__ import annotations

import numpy as np
import pytest

from tests.test_api import _make_psess, _make_session
from track2data.calibration.water_column import apply_water_column
from track2data.core.models import WaterColumn
from track2data.metrics.geometry3d import positions_cm, vertical_cm
from track2data.metrics.group import NearestNeighbourDistance3D
from track2data.metrics.individual import PathLength3D, Speed3D

PX_PER_CM = 10.0


def _native(z, *, column: WaterColumn | None = None, n_animals: int = 1):
    """A native 3-D psess: x = 3 cm/frame, y = 4 cm/frame, z as given, 10 px/cm."""
    z = np.asarray(z, dtype=float)
    n = z.shape[0]
    z = np.broadcast_to(z.reshape(n, 1), (n, n_animals)).copy()
    psess = _make_psess(_make_session(n_frames=n, n_animals=n_animals))
    t = np.arange(n, dtype=float)[:, None]
    psess.xy = np.stack(
        [np.broadcast_to(3.0 * t * PX_PER_CM, (n, n_animals)),
         np.broadcast_to(4.0 * t * PX_PER_CM, (n, n_animals))],
        axis=-1,
    )
    psess.px_per_cm = PX_PER_CM
    psess.z = z
    return apply_water_column(psess, column) if column is not None else psess


def test_vertical_cm_is_z_when_there_is_no_water_column() -> None:
    psess = _native([0.0, 1.0, 5.0, 2.0])
    np.testing.assert_array_equal(vertical_cm(psess)[:, 0], [0.0, 1.0, 5.0, 2.0])


def test_vertical_cm_drops_samples_outside_the_water_column() -> None:
    psess = _native([0.0, 1.0, 5.0, 2.0], column=WaterColumn(surface_z=0.0, floor_z=3.0))
    np.testing.assert_array_equal(vertical_cm(psess)[:, 0], [0.0, 1.0, np.nan, 2.0])
    # the stored z is the data and is not modified
    np.testing.assert_array_equal(psess.z[:, 0], [0.0, 1.0, 5.0, 2.0])


def test_vertical_cm_of_a_fused_session_is_depth_times_height() -> None:
    psess = _make_psess(_make_session(n_frames=3, n_animals=1))
    psess.depth = np.array([[0.1], [0.5], [np.nan]])
    psess.depth_height_cm = 20.0
    np.testing.assert_allclose(vertical_cm(psess)[:, 0], [2.0, 10.0, np.nan])


def test_vertical_cm_is_none_without_a_vertical_coordinate() -> None:
    assert vertical_cm(_make_psess(_make_session(n_frames=3, n_animals=1))) is None


def test_positions_cm_has_no_position_where_z_is_outside_the_column() -> None:
    psess = _native([0.0, 1.0, 5.0, 2.0], column=WaterColumn(surface_z=0.0, floor_z=3.0))
    pos = positions_cm(psess)
    assert np.isnan(pos[2]).all() and np.isfinite(pos[[0, 1, 3]]).all()


def test_il16_leaves_out_every_step_touching_an_outside_sample() -> None:
    # steps: 0->1 (3,4,1) = 5.099, 1->2 and 2->3 touch the outside sample, so only one is valid
    inside = _native([0.0, 1.0, 5.0, 2.0], column=WaterColumn(surface_z=0.0, floor_z=3.0))
    row = PathLength3D().compute(inside).iloc[0]
    assert row["n_valid_steps"] == 1
    assert row["path_length_3d_cm"] == pytest.approx(np.sqrt(9 + 16 + 1))


def test_il16_is_unchanged_when_the_column_contains_every_sample() -> None:
    z = [0.0, 1.0, 5.0, 2.0]
    plain = PathLength3D().compute(_native(z)).iloc[0]
    wide = PathLength3D().compute(
        _native(z, column=WaterColumn(surface_z=0.0, floor_z=10.0))
    ).iloc[0]
    assert plain["path_length_3d_cm"] == wide["path_length_3d_cm"]
    assert plain["n_valid_steps"] == wide["n_valid_steps"] == 3


def test_il17_has_no_speed_where_z_is_outside_the_column() -> None:
    z = [0.0, 1.0, 5.0, 2.0, 3.0, 2.0, 1.0]
    column = WaterColumn(surface_z=0.0, floor_z=3.0)
    with_column = Speed3D().compute(_native(z, column=column)).iloc[0]
    without = Speed3D().compute(_native(z)).iloc[0]
    assert with_column["max_speed_3d_cm_s"] < without["max_speed_3d_cm_s"]  # the spike is gone
    assert np.isfinite(with_column["mean_speed_3d_cm_s"])


def test_gl16_leaves_out_frames_with_an_animal_outside_the_column() -> None:
    column = WaterColumn(surface_z=0.0, floor_z=3.0)
    psess = _native([0.0, 1.0, 5.0, 2.0], column=column, n_animals=2)
    psess.xy[:, 1] += 50.0  # separate the two animals in the horizontal plane
    row = NearestNeighbourDistance3D().compute(psess).iloc[0]
    assert row["n_skipped_frames_3d"] == 1
    assert row["frac_frames_used_3d"] == pytest.approx(0.75)

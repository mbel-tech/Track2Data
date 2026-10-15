"""GL-19, 3-D group cohesion: GL-6 in (X, Y, Z) cm, from NND or IID."""

from __future__ import annotations

import numpy as np
import pytest

from tests.test_metrics.test_iid_3d import _fused, _three_fish
from track2data.metrics import get
from track2data.metrics.group import GroupCohesion, GroupCohesion3D


def _cohesion(psess, source: str | None = None) -> float:
    cfg = None if source is None else {"cohesion_source": source}
    return float(GroupCohesion3D().compute(psess, cfg).iloc[0]["cohesion_index_3d"])


def test_is_registered_with_the_agreed_identity() -> None:
    cls = get("GL-19")
    assert cls is GroupCohesion3D
    assert (cls.name, cls.label, cls.level) == ("group_cohesion_3d", "3-D Group Cohesion", "group")
    assert cls.requires_identity is False and cls.requires_depth_scale is True
    assert cls.output_columns == ["session_id", "metric_id", "cohesion_index_3d"]
    assert [p.name for p in cls.parameters] == ["cohesion_source"]


def test_cohesion_is_the_reciprocal_of_the_mean_distance_for_both_sources() -> None:
    psess = _fused(_three_fish())
    # NND: A->B 5, B->A 5, C->A 12, mean 22/3; IID: (5 + 12 + 13) / 3 = 10
    assert _cohesion(psess) == pytest.approx(3 / 22)
    assert _cohesion(psess, "nnd") == pytest.approx(3 / 22)
    assert _cohesion(psess, "iid") == pytest.approx(1 / 10)


def test_an_unknown_cohesion_source_is_refused() -> None:
    with pytest.raises(ValueError, match="cohesion_source"):
        _cohesion(_fused(_three_fish()), "IID")


def test_vertical_separation_lowers_the_3d_index_below_gl6() -> None:
    pos = np.zeros((5, 2, 3))
    pos[:, 1, 0] = 4.0
    pos[:, 1, 2] = 3.0  # 5 cm apart in 3-D, 4 cm in the plane
    psess = _fused(pos)
    assert _cohesion(psess) == pytest.approx(1 / 5)
    # GL-6 is per pixel (4 cm = 32 px), a different unit, but sees only the plane
    assert GroupCohesion().compute(psess).iloc[0]["cohesion_index"] == pytest.approx(1 / 32)


def test_zero_distance_and_single_animal_are_nan() -> None:
    assert np.isnan(_cohesion(_fused(np.zeros((4, 2, 3)))))
    assert np.isnan(_cohesion(_fused(np.zeros((4, 1, 3)))))


def test_frames_with_a_nan_are_skipped() -> None:
    psess = _fused(_three_fish(5))
    psess.depth[1, 2] = np.nan
    assert _cohesion(psess) == pytest.approx(3 / 22)


@pytest.mark.parametrize("missing", ["depth", "px_per_cm", "depth_height_cm"])
def test_without_depth_or_scale_it_is_nan(missing: str) -> None:
    psess = _fused(_three_fish())
    setattr(psess, missing, None)
    assert np.isnan(_cohesion(psess))

"""``to_movement_dataset``: a preprocessed session as a movement-style xarray Dataset."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

from track2data.core.errors import ImportError_
from track2data.core.models import (
    KinematicsArrays,
    PreprocessedSession,
    PreprocessReport,
    Session,
    VideoInfo,
)
from track2data.interop.movement import to_movement_dataset

FPS = 25.0


def make_psess(
    n_frames: int = 10,
    n_animals: int = 2,
    *,
    labels: list[str] | None = None,
    intervals: list[tuple[int, int]] | None = None,
    reader: str = "idtrackerai",
    probabilities: np.ndarray | None = None,
    z: np.ndarray | None = None,
    native_unit: str | None = None,
    **extra,
) -> PreprocessedSession:
    xy = np.random.default_rng(0).uniform(0, 100, size=(n_frames, n_animals, 2))
    session = Session(
        session_id="s",
        folder=Path("/tmp/s"),
        reader=reader,
        video=VideoInfo(fps=FPS, n_frames=n_frames, width_px=640, height_px=480),
        n_animals=n_animals,
        trajectory_variant="wo_gaps",
        has_stable_identities=True,
        raw_xy=xy,
        identities_labels=labels,
        tracking_intervals=intervals,
        id_probabilities=probabilities,
        has_pixel_frame=native_unit is None,
        coordinate_unit=native_unit,
    )
    speed = np.ones((n_frames, n_animals))
    kine = KinematicsArrays(
        speed_px_s=speed, accel_px_s2=np.zeros_like(speed), heading_rad=np.zeros_like(speed)
    )
    return PreprocessedSession(
        session=session, xy=xy, kinematics=kine, report=PreprocessReport(), z=z, **extra
    )


def test_a_missing_xarray_raises_a_coded_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "xarray", None)
    with pytest.raises(ImportError_) as caught:
        to_movement_dataset(make_psess())
    assert caught.value.code == "XARRAY_MISSING"
    assert "track2data[xarray]" in caught.value.remediation


needs_xarray = pytest.mark.skipif(
    importlib.util.find_spec("xarray") is None, reason="needs the optional xarray package"
)


@needs_xarray
def test_dims_and_shapes_for_a_two_animal_session() -> None:
    psess = make_psess(10, 2, labels=["a", "b"])
    ds = to_movement_dataset(psess)
    assert ds["position"].dims == ("time", "individuals", "keypoints", "space")
    assert ds["position"].shape == (10, 2, 1, 2)
    assert list(ds["individuals"].values) == ["a", "b"]
    assert list(ds["keypoints"].values) == ["centroid"]
    assert list(ds["space"].values) == ["x", "y"]
    np.testing.assert_allclose(ds["position"].values[:, :, 0, :], psess.xy)
    np.testing.assert_allclose(ds["time"].values, np.arange(10) / FPS)


@needs_xarray
def test_unlabelled_animals_are_numbered() -> None:
    ds = to_movement_dataset(make_psess(5, 3))
    assert list(ds["individuals"].values) == ["0", "1", "2"]


@needs_xarray
def test_time_follows_the_timeline_across_a_tracking_gap() -> None:
    psess = make_psess(10, 1, intervals=[(0, 5), (10, 15)])
    ds = to_movement_dataset(psess)
    frames = np.array([0, 1, 2, 3, 4, 10, 11, 12, 13, 14])
    np.testing.assert_allclose(ds["time"].values, frames / FPS)
    assert np.all(np.diff(ds["time"].values) > 0)


@needs_xarray
def test_separator_rows_are_dropped_by_default_and_kept_on_request() -> None:
    separator = np.zeros(6, dtype=bool)
    separator[3] = True
    psess = make_psess(
        6,
        1,
        frame_index=np.array([0, 1, 2, 3, 10, 11]),
        tracked_mask=~separator,
        separator_mask=separator,
    )
    psess.xy[3] = np.nan
    dropped = to_movement_dataset(psess)
    assert dropped["position"].shape[0] == 5
    assert not np.isnan(dropped["position"].values).any()
    np.testing.assert_allclose(dropped["time"].values, np.array([0, 1, 2, 10, 11]) / FPS)
    kept = to_movement_dataset(psess, include_separator_rows=True)
    assert kept["position"].shape[0] == 6
    assert np.isnan(kept["position"].values[3]).all()


@needs_xarray
def test_identity_confidence_is_not_called_confidence() -> None:
    probabilities = np.full((10, 2), 0.9)
    ds = to_movement_dataset(make_psess(10, 2, probabilities=probabilities))
    assert "confidence" not in ds
    assert ds["identity_confidence"].dims == ("time", "individuals")
    np.testing.assert_allclose(ds["identity_confidence"].values, 0.9)
    assert "identity_confidence" not in to_movement_dataset(make_psess(10, 2))


@needs_xarray
def test_a_native_3d_session_gets_a_z_space_coordinate() -> None:
    z = np.linspace(0, 9, 10)[:, None]
    ds = to_movement_dataset(make_psess(10, 1, z=z, native_unit="cm"))
    assert list(ds["space"].values) == ["x", "y", "z"]
    assert ds["position"].shape == (10, 1, 1, 3)
    np.testing.assert_allclose(ds["position"].values[:, 0, 0, 2], z[:, 0])
    assert ds.attrs["length_unit"] == "cm"


@needs_xarray
def test_attrs_carry_source_software_and_unit() -> None:
    ds = to_movement_dataset(make_psess())
    assert ds.attrs["fps"] == FPS
    assert ds.attrs["source_software"] == "idtracker.ai"
    assert ds.attrs["reader_verification"] in ("real_sample", "synthetic_only")
    assert ds.attrs["length_unit"] == "px"
    assert np.isnan(ds.attrs["px_per_cm"])
    calibrated = to_movement_dataset(make_psess(px_per_cm=12.5))
    assert calibrated.attrs["px_per_cm"] == 12.5

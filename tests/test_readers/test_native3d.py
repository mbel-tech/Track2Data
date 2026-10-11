"""Helpers shared by the native 3-D readers."""

from __future__ import annotations

import numpy as np
import pytest

from track2data.readers.native3d import (
    NATIVE_3D_READERS,
    UNIT_FACTORS_M,
    convert_units,
    horizontal_axes,
    native_parameters,
    reduce_native,
)


def test_convert_units_table() -> None:
    v = np.array([10.0, 250.0, np.nan])
    np.testing.assert_allclose(convert_units(v, "mm", "cm"), [1.0, 25.0, np.nan])
    np.testing.assert_allclose(convert_units(np.array([2.0]), "m", "cm"), [200.0])
    np.testing.assert_allclose(convert_units(np.array([2.0]), "in", "mm"), [50.8])
    same = convert_units(v, "cm", "cm")
    np.testing.assert_array_equal(same, v)
    assert same is not v
    assert UNIT_FACTORS_M == {"mm": 0.001, "cm": 0.01, "m": 1.0, "in": 0.0254}
    with pytest.raises(ValueError):
        convert_units(v, "ft", "cm")


def test_convert_units_is_exact_for_common_cases() -> None:
    assert convert_units(np.array([19.0]), "mm", "cm")[0] == 1.9
    assert convert_units(np.array([1.0]), "m", "cm")[0] == 100.0
    assert convert_units(np.array([1.0]), "in", "mm")[0] == 25.4
    assert convert_units(np.array([7.0]), "mm", "m")[0] == 0.007


def test_horizontal_axes() -> None:
    assert horizontal_axes("z") == (0, 1)
    assert horizontal_axes("y") == (0, 2)
    assert horizontal_axes("x") == (1, 2)
    with pytest.raises(ValueError):
        horizontal_axes("w")


def test_native_parameters_order_and_requirements() -> None:
    params = native_parameters("mm")
    assert [p.name for p in params] == [
        "fps",
        "unit",
        "target_unit",
        "keypoint",
        "likelihood_cutoff",
        "vertical_axis",
        "flip",
        "keep_skeleton",
    ]
    by = {p.name: p for p in params}
    assert by["fps"].required and by["unit"].required
    assert by["unit"].default is None  # never defaulted, only proposed
    assert by["target_unit"].default == "cm" and by["vertical_axis"].default == "z"
    assert by["likelihood_cutoff"].default == 0.0 and by["flip"].default is False


def test_native_reader_names() -> None:
    assert {"anipose", "deeplabcut_3d"} == set(NATIVE_3D_READERS)


def test_reduce_native_picks_the_vertical_coordinate() -> None:
    xyz = np.arange(2 * 1 * 2 * 3, dtype=float).reshape(2, 1, 2, 3)
    red, z = reduce_native(
        xyz, ["a", "b"], None, keypoint="b", cutoff=None, vertical_axis="y", flip=True
    )
    np.testing.assert_array_equal(red.raw_xy[:, 0, :], xyz[:, 0, 1, [0, 2]])
    np.testing.assert_array_equal(z[:, 0], -xyz[:, 0, 1, 1])
    assert red.selection.plane == ("x", "z")


def _assemble(**over):
    from pathlib import Path

    from track2data.readers.assemble import assemble_native_session

    args = dict(
        session_id="s",
        folder=Path("."),
        reader="anipose",
        fps=30.0,
        raw_xy=np.zeros((4, 1, 2)),
        raw_z=np.zeros((4, 1)),
        source_unit="mm",
        target_unit="cm",
        vertical_axis="z",
        flip=False,
        keypoints=None,
        tracking_intervals=None,
        trajectory_source=None,
        trajectory_format="anipose_pose3d_csv",
    )
    return assemble_native_session(**{**args, **over})


def test_assemble_native_session_fields() -> None:
    s = _assemble()
    assert s.has_pixel_frame is False and s.length_unit == 1.0 and s.coordinate_unit == "cm"
    assert s.video.width_px == 0 == s.video.height_px and s.video.n_frames == 4
    assert s.raw_z is not None and s.raw_z.shape == (4, 1)


@pytest.mark.parametrize(
    "over",
    [
        {"fps": 0.0},
        {"fps": float("nan")},
        {"raw_xy": np.zeros((4, 1, 3))},
        {"raw_xy": np.zeros((0, 1, 2)), "raw_z": np.zeros((0, 1))},
        {"raw_z": np.zeros((3, 1))},
        {"tracking_intervals": [(0, 2), (5, 8)]},
        {"tracking_intervals": [(0, 3)]},
    ],
)
def test_assemble_native_session_rejects_bad_input(over) -> None:
    from track2data.core.errors import DataValidationError

    with pytest.raises(DataValidationError) as err:
        _assemble(**over)
    assert err.value.code == "READER_OUTPUT_INVALID"


def test_assemble_native_session_accepts_gap_intervals() -> None:
    assert _assemble(tracking_intervals=[(0, 2), (5, 7)]).tracking_intervals == [(0, 2), (5, 7)]


def test_union_keypoints_and_frame_intervals() -> None:
    from track2data.readers.native3d import frame_intervals, union_keypoints

    assert union_keypoints([["a", "b"], ["c", "a"], []]) == ("a", "b", "c")
    assert union_keypoints([]) == ()
    assert frame_intervals(np.array([0, 1, 2])) is None
    assert frame_intervals(np.array([0, 1, 4, 5])) == [(0, 2), (4, 6)]
    assert frame_intervals(np.array([3, 4])) == [(3, 5)]


def test_read_header_lines_is_whole_lines_and_bounded(tmp_path) -> None:
    from track2data.readers.peek import read_header_lines

    path = tmp_path / "f.csv"
    path.write_bytes(b"\xef\xbb\xbf" + b"x" * 200_000 + b"\r\nsecond\nthird")
    first, second = read_header_lines(path, 2) or []
    assert len(first) == 200_000 and second == "second"
    assert read_header_lines(path, 2, limit=100_000) is None  # past the cap: undetected
    assert read_header_lines(tmp_path / "missing.csv", 1) is None

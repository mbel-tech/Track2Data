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
    # cyclic order after the vertical axis: x -> (y, z), y -> (z, x), z -> (x, y)
    assert horizontal_axes("z") == (0, 1)
    assert horizontal_axes("y") == (2, 0)
    assert horizontal_axes("x") == (1, 2)
    with pytest.raises(ValueError):
        horizontal_axes("w")


@pytest.mark.parametrize("vertical", ["x", "y", "z"])
def test_the_horizontal_plane_is_right_handed_with_the_vertical_axis_up(vertical: str) -> None:
    """first x second = up, so a counterclockwise turn seen from above stays counterclockwise."""
    first, second = horizontal_axes(vertical)
    unit = np.eye(3)
    np.testing.assert_array_equal(
        np.cross(unit[first], unit[second]), unit["xyz".index(vertical)]
    )


@pytest.mark.parametrize(
    ("vertical", "permutation"), [("z", (0, 1, 2)), ("x", (2, 0, 1)), ("y", (1, 2, 0))]
)
def test_a_proper_rotation_of_the_scene_leaves_the_horizontal_track_unchanged(
    vertical: str, permutation: tuple[int, int, int]
) -> None:
    """The same physical track, with up on each axis in turn (cyclic permutations of the file
    axes are proper rotations): the horizontal track the reader returns must not change, not
    even by a mirror, or every signed heading and turn would."""
    rng = np.random.default_rng(0)
    base = rng.normal(size=(12, 1, 1, 3))  # (frames, animals, keypoints, xyz), z up
    rotated = base[..., list(permutation)]
    red, z = reduce_native(
        rotated, ["a"], None, keypoint="a", cutoff=None, vertical_axis=vertical, flip=False
    )
    np.testing.assert_array_equal(red.raw_xy[:, 0, :], base[:, 0, 0, :2])
    np.testing.assert_array_equal(z[:, 0], base[:, 0, 0, 2])


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
    np.testing.assert_array_equal(red.raw_xy[:, 0, :], xyz[:, 0, 1, [2, 0]])
    np.testing.assert_array_equal(z[:, 0], -xyz[:, 0, 1, 1])
    assert red.selection.plane == ("z", "x")


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


def test_read_header_lines_never_reads_past_the_cap(tmp_path) -> None:
    from track2data.readers import peek

    path = tmp_path / "huge.csv"
    path.write_bytes(b"x" * 1_000_000)  # no newline at all
    reads: list[int] = []
    real_open = open

    class Counting:
        def __init__(self, handle):
            self._h = handle

        def read(self, n=-1):
            data = self._h.read(n)
            reads.append(len(data))
            return data

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self._h.close()

    import builtins

    original = builtins.open
    builtins.open = lambda *a, **k: Counting(real_open(*a, **k))  # type: ignore[assignment]
    try:
        assert peek.read_header_lines(path, 1, limit=300_000) is None
    finally:
        builtins.open = original
    assert sum(reads) <= 300_000

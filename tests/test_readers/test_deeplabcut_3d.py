"""The DeepLabCut-3D reader, on triangulated tables in the published layout."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tests.support.dlc import random_pose, write_dlc_csv
from tests.test_readers.native3d_files import write_dlc3d_csv
from track2data import readers
from track2data.core.errors import Track2DataError
from track2data.readers.deeplabcut import DeepLabCutReader
from track2data.readers.deeplabcut_3d import DeepLabCut3DReader
from track2data.readers.scan import scan

KPS = ["snout", "spine", "tail-tip"]
OPTS = {"fps": 30.0, "unit": "mm"}


def read(path: Path, **options):
    return readers.read_session(path, reader="deeplabcut_3d", options={**OPTS, **options})


def test_detects_only_the_3d_header(tmp_path: Path) -> None:
    good = write_dlc3d_csv(tmp_path / "good.csv", KPS, 3)
    assert DeepLabCut3DReader.detect(good)
    assert DeepLabCut3DReader.detect(tmp_path)
    two_d = write_dlc_csv(tmp_path / "d2.csv", random_pose(5, 1, 3), None, bodyparts=KPS)
    assert not DeepLabCut3DReader.detect(two_d)
    xy_only = write_dlc3d_csv(tmp_path / "xy.csv", KPS, 3, coords=("x", "y"))
    assert not DeepLabCut3DReader.detect(xy_only)
    renamed = write_dlc3d_csv(tmp_path / "ren.csv", KPS, 3, coords=("x", "y", "w"))
    assert not DeepLabCut3DReader.detect(renamed)
    assert not DeepLabCut3DReader.detect(tmp_path / "missing.csv")
    # and the 2-D reader does not claim the 3-D file (it needs a likelihood)
    assert not DeepLabCutReader.detect(good)


def test_the_2d_reader_does_not_discover_the_3d_header(tmp_path: Path) -> None:
    write_dlc3d_csv(tmp_path / "a.csv", KPS, 4)
    (group,) = scan([tmp_path]).groups
    assert [d.reader for d in group.detections] == ["deeplabcut_3d"]
    assert scan([tmp_path]).recognised == ()  # no longer listed as an unreadable format
    assert readers.detect_reader(tmp_path / "a.csv") is DeepLabCut3DReader


def test_reads_exact_values_and_units(tmp_path: Path) -> None:
    path = write_dlc3d_csv(tmp_path / "v.csv", KPS, 5)
    s = read(path, keypoint="spine", target_unit="cm")
    f = np.arange(5)
    assert s.keypoints is not None and s.keypoints.xy.shape == (5, 1, 3, 3)
    np.testing.assert_allclose(s.raw_xy[:, 0, 0], (f + 100.0) / 10, rtol=1e-6)
    np.testing.assert_allclose(s.raw_xy[:, 0, 1], (f + 110.0) / 10, rtol=1e-6)
    assert s.raw_z is not None and s.raw_z.shape == (5, 1)
    np.testing.assert_allclose(s.raw_z[:, 0], (f + 120.0) / 10, rtol=1e-6)
    np.testing.assert_allclose(s.keypoints.xy[3, 0, 2], [(3 + 200 + 10 * a) / 10 for a in range(3)])
    assert s.tracking_intervals is None and s.video.n_frames == 5 and s.video.fps == 30.0
    assert s.raw_xy.dtype == np.float64 and s.n_animals == 1
    assert s.keypoints.names == KPS


def test_all_zero_row_is_missing_but_a_single_zero_is_real(tmp_path: Path) -> None:
    xyz = np.array(
        [
            [[1.0, 2.0, 3.0]],
            [[0.0, 0.0, 0.0]],  # DLC-3D writes 0,0,0 for a point it could not triangulate
            [[0.0, 5.0, 3.0]],  # a real x of 0
            [[4.0, 0.0, 0.0]],
            [[np.nan, 1.0, 1.0]],  # a partial NaN triple is missing as a whole
        ]
    )
    s = read(write_dlc3d_csv(tmp_path / "z.csv", ["a"], 5, xyz=xyz), target_unit="mm")
    assert s.raw_z is not None and s.keypoints is not None
    assert np.isnan(s.raw_xy[[1, 4]]).all() and np.isnan(s.raw_z[[1, 4]]).all()
    np.testing.assert_array_equal(s.raw_xy[2, 0], [0, 5])
    assert s.raw_z[2, 0] == 3
    np.testing.assert_array_equal(s.raw_xy[3, 0], [4, 0])
    assert s.raw_z[3, 0] == 0
    assert np.isnan(s.keypoints.xy[1, 0, 0]).all()
    np.testing.assert_array_equal(s.keypoints.xy[2, 0, 0], [0, 5, 3])


def test_vertical_axis_and_flip(tmp_path: Path) -> None:
    xyz = np.array([[[1.0, 2.0, 3.0]], [[4.0, 5.0, 6.0]]])
    path = write_dlc3d_csv(tmp_path / "a.csv", ["a"], 2, xyz=xyz)
    s = read(path, target_unit="mm", vertical_axis="y")
    assert s.raw_z is not None and s.keypoints is not None
    np.testing.assert_array_equal(s.raw_xy[:, 0, :], [[1, 3], [4, 6]])
    np.testing.assert_array_equal(s.raw_z[:, 0], [2, 5])
    f = read(path, target_unit="mm", vertical_axis="y", flip=True)
    assert f.raw_z is not None and f.keypoints is not None
    np.testing.assert_array_equal(f.raw_z[:, 0], [-2, -5])
    np.testing.assert_array_equal(f.raw_xy, s.raw_xy)
    assert f.raw_attrs is not None
    assert f.raw_attrs["native_3d"]["vertical_axis"] == "y" and f.raw_attrs["native_3d"]["flip"]
    # the stored skeleton keeps the file's axes
    np.testing.assert_array_equal(f.keypoints.xy[:, 0, 0, :], xyz[:, 0, :])


@pytest.mark.parametrize("missing", ["fps", "unit"])
def test_requires_fps_and_unit(tmp_path: Path, missing: str) -> None:
    path = write_dlc3d_csv(tmp_path / "r.csv", ["a"], 3)
    options = {k: v for k, v in OPTS.items() if k != missing}
    with pytest.raises(Track2DataError) as err:
        readers.read_session(path, reader="deeplabcut_3d", options=options)
    assert err.value.code == "READER_OPTION_MISSING" and err.value.subject == missing


def test_has_no_likelihood_option(tmp_path: Path) -> None:
    assert "likelihood_cutoff" not in {p.name for p in DeepLabCut3DReader.parameters}
    path = write_dlc3d_csv(tmp_path / "l.csv", ["a"], 3)
    with pytest.raises(Track2DataError):
        read(path, likelihood_cutoff=0.5)


def test_multi_frame_index_from_the_first_column(tmp_path: Path) -> None:
    s = read(write_dlc3d_csv(tmp_path / "g.csv", ["a"], [0, 1, 2, 5, 6]), target_unit="mm")
    assert s.tracking_intervals == [(0, 3), (5, 7)]
    assert s.raw_xy.shape == (5, 1, 2) and s.raw_z is not None and s.raw_z.shape == (5, 1)
    assert s.raw_xy[3, 0, 0] == 3.0  # the stored row after the gap is the row of frame 5
    assert s.keypoints is not None and s.keypoints.xy.shape[0] == 5
    off = read(write_dlc3d_csv(tmp_path / "o.csv", ["a"], [4, 3, 5]), target_unit="mm")
    assert off.tracking_intervals == [(3, 6)]
    np.testing.assert_array_equal(off.raw_xy[:, 0, 0], [1, 0, 2])
    bad = write_dlc3d_csv(tmp_path / "dup.csv", ["a"], [0, 1, 1])
    with pytest.raises(Track2DataError) as err:
        read(bad)
    assert err.value.code == "DLC3D_BAD_FRAME_INDEX"


def test_session_flags(tmp_path: Path) -> None:
    path = write_dlc3d_csv(tmp_path / "f.csv", KPS, 6)
    s = read(path, unit="in", target_unit="mm", keypoint="spine")
    assert s.has_pixel_frame is False and s.length_unit == 1.0
    assert s.coordinate_unit == "mm"
    assert s.video.width_px == 0 and s.video.height_px == 0
    assert s.raw_attrs is not None
    assert s.raw_attrs["native_3d"] == {
        "source_unit": "in",
        "target_unit": "mm",
        "vertical_axis": "z",
        "flip": False,
    }
    assert s.reader == "deeplabcut_3d" and s.has_stable_identities
    assert s.identities_labels is None
    assert s.trajectory_format == "deeplabcut_3d_csv" and s.trajectory_source == path
    assert DeepLabCut3DReader.provides_native_3d
    assert DeepLabCut3DReader.coordinate_frame == "physical_unaligned"
    assert DeepLabCut3DReader.verification == "synthetic_only"
    assert s.raw_z is not None
    assert s.raw_z[2, 0] == pytest.approx((2 + 100.0 + 20) * 25.4, rel=1e-6)


def test_registered_discovered_and_proposes_no_unit(tmp_path: Path) -> None:
    write_dlc3d_csv(tmp_path / "m1.csv", KPS, 5)
    write_dlc3d_csv(tmp_path / "m2.csv", KPS, 5)
    assert readers.get_reader("deeplabcut_3d") is DeepLabCut3DReader
    (group,) = scan([tmp_path]).groups
    det = group.best
    assert det.reader == "deeplabcut_3d" and len(det.sessions) == 2
    assert "unit" not in det.proposed or det.proposed["unit"].source == "required"
    keypoint = next(p for p in det.parameters if p.name == "keypoint")
    assert keypoint.choices == tuple(KPS)
    assert det.verification == "synthetic_only"


def test_skeleton_can_be_dropped_and_input_untouched(tmp_path: Path) -> None:
    path = write_dlc3d_csv(tmp_path / "k.csv", KPS, 3)
    before = path.read_bytes()
    assert read(path, keep_skeleton=False).keypoints is None
    assert path.read_bytes() == before


def test_empty_file_and_ambiguous_folder(tmp_path: Path) -> None:
    empty = write_dlc3d_csv(tmp_path / "empty.csv", ["a"], 0)
    with pytest.raises(Track2DataError) as err:
        read(empty)
    assert err.value.code == "READER_OUTPUT_INVALID"
    empty.unlink()
    write_dlc3d_csv(tmp_path / "a.csv", ["a"], 3)
    write_dlc3d_csv(tmp_path / "b.csv", ["a"], 3)
    with pytest.raises(Track2DataError) as err2:
        read(tmp_path)
    assert err2.value.code == "SESSION_AMBIGUOUS"


def test_header_longer_than_the_peek_is_still_detected(tmp_path: Path) -> None:
    names = [f"part-{i:05d}" for i in range(2500)]  # three columns each: > 64 KB of header
    path = write_dlc3d_csv(tmp_path / "wide.csv", names, 2)
    assert len(path.read_text().splitlines()[1]) > 65_536
    assert DeepLabCut3DReader.detect(path)
    (group,) = scan([tmp_path]).groups
    (detection,) = group.detections
    assert detection.reader == "deeplabcut_3d"
    keypoint = next(p for p in detection.parameters if p.name == "keypoint")
    assert keypoint.choices == tuple(names)
    assert read(path, keypoint=names[-1]).raw_xy.shape == (2, 1, 2)


def test_keypoint_choices_are_the_union_when_files_share_none(tmp_path: Path) -> None:
    write_dlc3d_csv(tmp_path / "a.csv", ["nose", "tail"], 3)
    write_dlc3d_csv(tmp_path / "b.csv", ["fin", "eye"], 3)
    (group,) = scan([tmp_path]).groups
    (detection,) = group.detections
    keypoint = next(p for p in detection.parameters if p.name == "keypoint")
    assert keypoint.choices == ("nose", "tail", "fin", "eye")
    with pytest.raises(Track2DataError) as err:
        read(tmp_path / "a.csv", keypoint="fin")
    assert err.value.code == "READER_OPTION_INVALID"


@pytest.mark.parametrize("bad", ["dup", "negative", "text"])
def test_dlc3d_frame_index_errors_say_deeplabcut_3d(tmp_path: Path, bad: str) -> None:
    frames: list = {"dup": [0, 1, 1], "negative": [-1, 0, 1], "text": [0, 1, 2]}[bad]
    path = write_dlc3d_csv(tmp_path / "f.csv", ["a"], frames)
    if bad == "text":
        path.write_text(path.read_text().replace("\n2,", "\nsecond,"))
    with pytest.raises(Track2DataError) as err:
        read(path)
    assert err.value.code == "DLC3D_BAD_FRAME_INDEX"
    assert "DeepLabCut 3-D" in str(err.value) and not err.value.code.startswith("DLC_")
    assert "DeepLabCut 3-D" in err.value.remediation


def test_dlc3d_bad_value_and_unreadable_have_their_own_codes(tmp_path: Path) -> None:
    path = write_dlc3d_csv(tmp_path / "v.csv", ["a"], 3)
    lines = path.read_text().splitlines()
    lines[4] = lines[4].replace("11.0", "oops")  # frame 1, a cell that is not a number
    path.write_text("\n".join(lines) + "\n")
    with pytest.raises(Track2DataError) as err:
        read(path)
    assert err.value.code == "DLC3D_BAD_VALUE" and "DeepLabCut 3-D" in str(err.value)
    broken = write_dlc3d_csv(tmp_path / "u.csv", ["a"], 3)
    broken.write_bytes(broken.read_bytes() + b"\xff\xfe\n")
    with pytest.raises(Track2DataError) as err:
        read(broken)
    assert err.value.code == "DLC3D_UNREADABLE" and "DeepLabCut 3-D" in str(err.value)


def test_dlc3d_duplicate_column_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "d.csv"
    path.write_text(
        "scorer,s,s,s,s\nbodyparts,a,a,a,a\ncoords,x,y,z,x\n0,1,2,3,4\n1,2,3,4,5\n"
    )
    assert DeepLabCut3DReader.detect(path)  # still recognised; the read explains the problem
    with pytest.raises(Track2DataError) as err:
        read(path)
    assert err.value.code == "DLC3D_DUPLICATE_COLUMN"
    assert "a x" in str(err.value)


def test_a_2d_table_with_z_and_likelihood_is_not_claimed_by_dlc3d(tmp_path: Path) -> None:
    path = tmp_path / "t.csv"
    path.write_text(
        "scorer,s,s,s,s\nbodyparts,a,a,a,a\ncoords,x,y,z,likelihood\n0,1,2,3,0.9\n1,2,3,4,0.9\n"
    )
    assert not DeepLabCut3DReader.detect(path)
    assert readers.detect_reader(path) is DeepLabCutReader
    (group,) = scan([tmp_path]).groups
    assert [d.reader for d in group.detections] == ["deeplabcut"]


def test_the_3d_readers_texts_all_say_deeplabcut_3d(tmp_path: Path) -> None:
    plain = tmp_path / "notes.csv"
    plain.write_text("a,b\n1,2\n")
    with pytest.raises(Track2DataError) as err:
        read(plain)
    assert err.value.code == "DLC3D_NOT_A_3D_FILE"
    assert "DeepLabCut 3-D" in str(err.value) and "DeepLabCut 3-D" in err.value.remediation
    folder = tmp_path / "two"
    folder.mkdir()
    write_dlc3d_csv(folder / "a.csv", ["a"], 3)
    write_dlc3d_csv(folder / "b.csv", ["a"], 3)
    with pytest.raises(Track2DataError) as err:
        read(folder)
    assert err.value.code == "SESSION_AMBIGUOUS" and "DeepLabCut 3-D" in str(err.value)
    empty = tmp_path / "empty.csv"
    empty.write_text("scorer,s,s,s\nbodyparts,a,a,a\ncoords,x,y,z\n")
    with pytest.raises(Track2DataError) as err:
        read(empty)
    assert "DeepLabCut 3-D" in err.value.remediation


def test_display_name_is_exported_provenance_and_must_not_change() -> None:
    # display_name is exported as source_software (README, manifest.json, PROJECT_SUMMARY.md,
    # run log); changing it would change the exports of existing native DLC-3D projects.
    assert DeepLabCut3DReader.display_name == "DeepLabCut 3D (triangulated CSV)"


def test_overlong_header_read_says_so(tmp_path: Path) -> None:
    from track2data.readers.peek import MAX_HEADER_BYTES

    path = tmp_path / "wide.csv"
    path.write_text("scorer," + "s," * (9 * 1024 * 1024 // 2) + "\nbodyparts,a\ncoords,x\n0,1\n")
    assert path.stat().st_size > MAX_HEADER_BYTES
    assert not DeepLabCut3DReader.detect(path)  # detection stays False
    with pytest.raises(Track2DataError) as err:
        read(path)
    assert err.value.code == "HEADER_TOO_LONG"
    assert "wide.csv" in str(err.value) and "8 MB" in str(err.value)


def test_discover_warns_about_a_duplicate_column(tmp_path: Path) -> None:
    path = tmp_path / "d.csv"
    path.write_text(
        "scorer,s,s,s,s\nbodyparts,a,a,a,a\ncoords,x,y,z,x\n0,1,2,3,4\n1,2,3,4,5\n"
    )
    (group,) = scan([tmp_path]).groups
    (detection,) = group.detections
    (candidate,) = detection.sessions
    assert candidate.warnings == ("duplicate column a x: the file will be refused when read",)
    other = tmp_path / "clean"
    other.mkdir()
    write_dlc3d_csv(other / "c.csv", KPS, 3)
    (group,) = scan([other]).groups
    assert group.detections[0].sessions[0].warnings == ()

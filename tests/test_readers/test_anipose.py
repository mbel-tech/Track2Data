"""The Anipose pose-3d reader, on tables written in the published layout."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tests.support.dlc import random_pose, write_dlc_csv
from tests.test_readers.native3d_files import write_anipose_csv
from track2data import readers
from track2data.core.errors import Track2DataError
from track2data.readers.anipose import AniposeReader
from track2data.readers.scan import scan

KPS = ["l-base", "r-middle", "tail_tip"]
OPTS = {"fps": 50.0, "unit": "mm"}


def read(path: Path, **options):
    return readers.read_session(path, reader="anipose", options={**OPTS, **options})


def hand(frame: int, k: int, axis: int) -> float:
    """The default value write_anipose_csv puts at (row, keypoint, axis), in mm."""
    return frame + 100.0 * k + 10.0 * axis


def test_anipose_detects_layout_and_rejects_near_misses(tmp_path: Path) -> None:
    good = write_anipose_csv(tmp_path / "good.csv", KPS, 3)
    assert AniposeReader.detect(good)
    dlc = write_dlc_csv(tmp_path / "dlc.csv", random_pose(5, 1, 3), None, bodyparts=KPS)
    assert not AniposeReader.detect(dlc)
    no_z = tmp_path / "no_z.csv"
    no_z.write_text("a_x,a_y,fnum\n1,2,0\n3,4,1\n")
    assert not AniposeReader.detect(no_z)
    no_fnum = write_anipose_csv(tmp_path / "no_fnum.csv", KPS, 3, frame_column=False)
    assert not AniposeReader.detect(no_fnum)
    assert not AniposeReader.detect(tmp_path / "missing.csv")


def test_anipose_hyphenated_keypoint_names(tmp_path: Path) -> None:
    path = write_anipose_csv(tmp_path / "h.csv", ["l-base", "r_edge"], 4)
    s = read(path, keypoint="l-base")
    assert s.keypoints is not None and s.keypoints.names == ["l-base", "r_edge"]
    assert s.keypoints.selection.keypoint == "l-base"


def test_anipose_reads_exact_values(tmp_path: Path) -> None:
    path = write_anipose_csv(tmp_path / "v.csv", KPS, 5)
    s = read(path, keypoint="r-middle", target_unit="cm")
    assert s.keypoints is not None and s.keypoints.xy.shape == (5, 1, 3, 3)
    f = np.arange(5)
    np.testing.assert_allclose(s.raw_xy[:, 0, 0], (f + 100.0 + 0.0) / 10, rtol=1e-6)
    np.testing.assert_allclose(s.raw_xy[:, 0, 1], (f + 100.0 + 10.0) / 10, rtol=1e-6)
    assert s.raw_z is not None and s.raw_z.shape == (5, 1)
    np.testing.assert_allclose(s.raw_z[:, 0], (f + 100.0 + 20.0) / 10, rtol=1e-6)
    np.testing.assert_allclose(s.keypoints.xy[3, 0, 2], [(3 + 200 + 10 * a) / 10 for a in range(3)])
    assert s.tracking_intervals is None and s.video.n_frames == 5 and s.video.fps == 50.0
    assert s.raw_xy.dtype == np.float64 and s.n_animals == 1


def test_anipose_nan_triple_is_missing(tmp_path: Path) -> None:
    xyz = np.arange(4 * 1 * 3, dtype=float).reshape(4, 1, 3) + 1
    xyz[1] = np.nan
    xyz[2, 0, 1] = np.nan  # a partial triple is missing as a whole
    s = read(write_anipose_csv(tmp_path / "n.csv", ["a"], 4, xyz=xyz), target_unit="mm")
    assert s.raw_z is not None
    assert np.isnan(s.raw_xy[[1, 2]]).all() and np.isnan(s.raw_z[[1, 2]]).all()
    np.testing.assert_array_equal(s.raw_xy[0, 0], [1, 2])
    assert s.raw_z[0, 0] == 3 and s.raw_z[3, 0] == 12
    assert s.keypoints is not None and np.isnan(s.keypoints.xy[2, 0, 0]).all()


def test_anipose_fnum_gap_gives_tracking_intervals(tmp_path: Path) -> None:
    path = write_anipose_csv(tmp_path / "g.csv", ["a"], [0, 1, 2, 5, 6])
    s = read(path, target_unit="mm")
    assert s.tracking_intervals == [(0, 3), (5, 7)]
    assert s.raw_xy.shape == (5, 1, 2) and s.raw_z is not None and s.raw_z.shape == (5, 1)
    assert s.raw_xy[3, 0, 0] == 3.0  # the stored row after the gap is the row of fnum 5
    assert s.keypoints is not None and s.keypoints.xy.shape[0] == 5


def test_anipose_unsorted_and_offset_fnum(tmp_path: Path) -> None:
    s = read(write_anipose_csv(tmp_path / "o.csv", ["a"], [4, 3, 5]), target_unit="mm")
    assert s.tracking_intervals == [(3, 6)]
    np.testing.assert_array_equal(s.raw_xy[:, 0, 0], [1, 0, 2])
    bad = write_anipose_csv(tmp_path / "dup.csv", ["a"], [0, 1, 1])
    with pytest.raises(Track2DataError) as err:
        read(bad)
    assert err.value.code == "ANIPOSE_BAD_FRAME_INDEX"


def test_anipose_vertical_axis_and_flip(tmp_path: Path) -> None:
    xyz = np.array([[[1.0, 2.0, 3.0]], [[4.0, 5.0, 6.0]]])
    path = write_anipose_csv(tmp_path / "a.csv", ["a"], 2, xyz=xyz)
    s = read(path, target_unit="mm", vertical_axis="y")
    assert s.raw_z is not None
    np.testing.assert_array_equal(s.raw_xy[:, 0, :], [[1, 3], [4, 6]])
    np.testing.assert_array_equal(s.raw_z[:, 0], [2, 5])
    f = read(path, target_unit="mm", vertical_axis="y", flip=True)
    assert f.raw_z is not None
    np.testing.assert_array_equal(f.raw_z[:, 0], [-2, -5])
    np.testing.assert_array_equal(f.raw_xy, s.raw_xy)
    assert f.raw_attrs is not None
    assert f.raw_attrs["native_3d"]["vertical_axis"] == "y" and f.raw_attrs["native_3d"]["flip"]
    x = read(path, target_unit="mm", vertical_axis="x")
    np.testing.assert_array_equal(x.raw_xy[:, 0, :], [[2, 3], [5, 6]])


def test_anipose_keypoint_and_score_cutoff(tmp_path: Path) -> None:
    score = np.ones((4, 2))
    score[1, 0] = 0.2
    path = write_anipose_csv(tmp_path / "s.csv", ["a", "b"], 4, score=score)
    s = read(path, keypoint="a", likelihood_cutoff=0.5, target_unit="mm")
    assert s.raw_z is not None
    assert np.isnan(s.raw_xy[1]).all() and np.isnan(s.raw_z[1]).all()
    assert np.isfinite(s.raw_xy[[0, 2, 3]]).all()
    assert s.keypoints is not None and s.keypoints.selection.cutoff == 0.5
    assert s.keypoints.selection.chosen_by == "user"
    kept = read(path, keypoint="a", target_unit="mm")  # no cutoff by default
    assert np.isfinite(kept.raw_xy).all()
    auto = read(path, likelihood_cutoff=0.5)  # the better covered keypoint
    assert auto.keypoints is not None and auto.keypoints.selection.keypoint == "b"
    with pytest.raises(Track2DataError) as err:
        read(path, keypoint="nope")
    assert err.value.code == "READER_OPTION_INVALID"


@pytest.mark.parametrize("missing", ["fps", "unit"])
def test_anipose_requires_fps_and_unit(tmp_path: Path, missing: str) -> None:
    path = write_anipose_csv(tmp_path / "r.csv", ["a"], 3)
    options = {k: v for k, v in OPTS.items() if k != missing}
    with pytest.raises(Track2DataError) as err:
        readers.read_session(path, reader="anipose", options=options)
    assert err.value.code == "READER_OPTION_MISSING" and err.value.subject == missing
    with pytest.raises(Track2DataError) as err2:
        readers.read_session(path, reader="anipose", options={"fps": 50.0, "unit": "km"})
    assert err2.value.code == "READER_OPTION_INVALID" and err2.value.subject == "unit"


def test_anipose_session_flags(tmp_path: Path) -> None:
    path = write_anipose_csv(tmp_path / "f.csv", KPS, 6)
    s = read(path, unit="in", target_unit="mm", keypoint="r-middle")
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
    assert s.reader == "anipose" and s.has_stable_identities and s.identities_labels is None
    assert s.trajectory_format == "anipose_pose3d_csv" and s.trajectory_source == path
    assert AniposeReader.provides_native_3d
    assert AniposeReader.coordinate_frame == "physical_unaligned"
    assert AniposeReader.verification == "synthetic_only"
    # inches to mm on keypoint "r-middle" (index 1 in the file): frame 2, axis z
    assert s.raw_z is not None
    assert s.raw_z[2, 0] == pytest.approx((2 + 100.0 + 20) * 25.4, rel=1e-6)


def test_anipose_skeleton_can_be_dropped(tmp_path: Path) -> None:
    path = write_anipose_csv(tmp_path / "k.csv", KPS, 3)
    assert read(path, keep_skeleton=False).keypoints is None


def test_anipose_input_is_not_modified_and_empty_file_is_refused(tmp_path: Path) -> None:
    path = write_anipose_csv(tmp_path / "m.csv", ["a"], 3)
    before = path.read_bytes()
    read(path)
    assert path.read_bytes() == before
    empty = tmp_path / "empty.csv"
    empty.write_text("a_x,a_y,a_z,fnum\n")
    with pytest.raises(Track2DataError) as err:
        read(empty)
    assert err.value.code == "READER_OUTPUT_INVALID"


def test_anipose_folder_with_two_files_is_ambiguous(tmp_path: Path) -> None:
    write_anipose_csv(tmp_path / "a.csv", ["a"], 3)
    write_anipose_csv(tmp_path / "b.csv", ["a"], 3)
    with pytest.raises(Track2DataError) as err:
        read(tmp_path)
    assert err.value.code == "SESSION_AMBIGUOUS"


def test_anipose_registered_and_discovered(tmp_path: Path) -> None:
    write_anipose_csv(tmp_path / "mouse1.csv", KPS, 5)
    write_anipose_csv(tmp_path / "mouse2.csv", KPS, 5)
    assert readers.get_reader("anipose") is AniposeReader
    (group,) = scan([tmp_path]).groups
    det = group.best
    assert det.reader == "anipose" and len(det.sessions) == 2
    assert det.proposed["unit"].value == "mm" and det.proposed["unit"].source == "tool-default"
    keypoint = next(p for p in det.parameters if p.name == "keypoint")
    assert keypoint.choices == tuple(KPS)
    assert det.verification == "synthetic_only"


def test_anipose_cutoff_without_scores_is_refused(tmp_path: Path) -> None:
    path = write_anipose_csv(tmp_path / "p.csv", ["a", "b"], 3)
    text = path.read_text().replace("b_score", "b_other")
    path.write_text(text)
    assert AniposeReader.detect(path)
    with pytest.raises(Track2DataError) as err:
        read(path, likelihood_cutoff=0.5)
    assert err.value.code == "READER_OPTION_INVALID" and err.value.subject == "likelihood_cutoff"
    assert "0" in err.value.remediation
    assert read(path, keypoint="a").raw_xy.shape == (3, 1, 2)  # no cutoff: fine


def test_anipose_skeleton_keeps_the_file_axes(tmp_path: Path) -> None:
    xyz = np.array([[[1.0, 2.0, 3.0]], [[4.0, 5.0, 6.0]]])
    path = write_anipose_csv(tmp_path / "sk.csv", ["a"], 2, xyz=xyz)
    s = read(path, target_unit="mm", vertical_axis="y", flip=True)
    assert s.raw_z is not None and s.keypoints is not None
    np.testing.assert_array_equal(s.raw_z[:, 0], [-2, -5])
    np.testing.assert_array_equal(s.keypoints.xy[:, 0, 0, :], xyz[:, 0, :])


def test_header_longer_than_the_peek_is_still_detected(tmp_path: Path) -> None:
    """A header line past the 64 KB peek is read whole, not cut mid-column (no misparse)."""
    names = [f"keypoint-{i:05d}" for i in range(2500)]  # ~ 6 columns x 2500 x 17 bytes > 64 KB
    path = write_anipose_csv(tmp_path / "wide.csv", names, 2)
    assert len(path.read_text().splitlines()[0]) > 65_536
    assert AniposeReader.detect(path)
    (group,) = scan([tmp_path]).groups
    (detection,) = group.detections
    assert detection.reader == "anipose"
    keypoint = next(p for p in detection.parameters if p.name == "keypoint")
    assert keypoint.choices == tuple(names)  # the last keypoint (past 64 KB) is there too
    s = read(path, keypoint=names[-1])
    assert s.raw_xy.shape == (2, 1, 2)


def test_keypoint_choices_are_the_union_when_files_share_none(tmp_path: Path) -> None:
    write_anipose_csv(tmp_path / "a.csv", ["nose", "tail"], 3)
    write_anipose_csv(tmp_path / "b.csv", ["fin", "eye"], 3)
    (group,) = scan([tmp_path]).groups
    (detection,) = group.detections
    keypoint = next(p for p in detection.parameters if p.name == "keypoint")
    assert keypoint.choices == ("nose", "tail", "fin", "eye")
    with pytest.raises(Track2DataError) as err:  # the per-file check stays
        read(tmp_path / "a.csv", keypoint="fin")
    assert err.value.code == "READER_OPTION_INVALID"
    assert "nose" in err.value.remediation and "tail" in err.value.remediation


def test_overlong_header_read_says_so(tmp_path: Path) -> None:
    from track2data.readers.peek import MAX_HEADER_BYTES

    path = tmp_path / "wide.csv"
    path.write_text("fnum," + "a_x," * (9 * 1024 * 1024 // 4) + "\n0\n")
    assert path.stat().st_size > MAX_HEADER_BYTES
    assert not AniposeReader.detect(path)  # detection stays False
    with pytest.raises(Track2DataError) as err:
        read(path)
    assert err.value.code == "HEADER_TOO_LONG"
    assert "wide.csv" in str(err.value) and "8 MB" in str(err.value)


def test_discover_warns_about_a_duplicate_column(tmp_path: Path) -> None:
    path = tmp_path / "d.csv"
    path.write_text("a_x,a_y,a_z,a_x,fnum\n1,2,3,4,0\n2,3,4,5,1\n")
    assert AniposeReader.detect(path)  # still recognised
    (group,) = scan([tmp_path]).groups
    (detection,) = group.detections
    (candidate,) = detection.sessions
    assert candidate.warnings == ("duplicate column a_x: the file will be refused when read",)
    with pytest.raises(Track2DataError) as err:
        read(path)
    assert err.value.code == "ANIPOSE_DUPLICATE_COLUMN"

    other = tmp_path / "clean"
    other.mkdir()
    write_anipose_csv(other / "c.csv", KPS, 3)
    (group,) = scan([other]).groups
    assert group.detections[0].sessions[0].warnings == ()

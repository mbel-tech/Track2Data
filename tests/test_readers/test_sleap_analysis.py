"""The SLEAP analysis HDF5 reader.

Built from files written in the real GUI-export layout (tests/support/sleap.py); the real files
they imitate are exercised by the opt-in suite in tests/real_samples. Pinned here: what counts
as a SLEAP analysis file (and what must not), how tracks and nodes become animals and a
position, what a missing name means for identity, and that the layout is checked, not guessed.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import h5py
import numpy as np
import pytest

from tests.support.dlc import random_pose, write_dlc_csv
from tests.support.sleap import random_tracks, write_sleap_analysis
from track2data import readers
from track2data.core.errors import Track2DataError
from track2data.readers.detection import Confidence
from track2data.readers.scan import scan
from track2data.readers.sleap_analysis import SleapAnalysisReader

NODES = ["snout", "ear", "tail"]
VIDEO = {"fps": 30.0, "width_px": 640, "height_px": 480}


def analysis(path: Path, *, n_tracks: int = 2, names="auto", **kw) -> Path:
    tracks = kw.pop("tracks", None)
    if tracks is None:
        tracks = random_tracks(40, n_tracks, len(NODES))
    if names == "auto":
        names = [f"mouse{i}" for i in range(tracks.shape[0])]
    return write_sleap_analysis(path, tracks, node_names=NODES, track_names=names, **kw)


def read(path: Path, **options):
    return readers.read_session(path, reader="sleap_analysis", options={**VIDEO, **options})


def detection_for(root: Path):
    (group,) = scan([root]).groups
    return group.best


def tree_hash(folder: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(Path(folder).rglob("*")):
        if p.is_file():
            h.update(p.name.encode() + p.read_bytes())
    return h.hexdigest()


class TestWhatIsASleapAnalysisFile:
    def test_a_gui_export_is_recognised_with_high_confidence(self, tmp_path: Path) -> None:
        analysis(tmp_path / "trial1.analysis.h5")
        d = detection_for(tmp_path)
        assert d.reader == "sleap_analysis" and d.confidence is Confidence.HIGH
        assert [s.session_id for s in d.sessions] == ["trial1"]  # not "trial1.analysis"

    def test_a_file_without_the_analysis_suffix_is_still_recognised(self, tmp_path: Path) -> None:
        analysis(tmp_path / "export.h5")
        assert [s.session_id for s in detection_for(tmp_path).sessions] == ["export"]

    def test_every_file_in_a_folder_is_its_own_session(self, tmp_path: Path) -> None:
        for name in ("a", "b"):
            analysis(tmp_path / f"{name}.analysis.h5")
        assert [s.session_id for s in detection_for(tmp_path).sessions] == ["a", "b"]

    def test_the_nodes_are_offered_as_the_choices_for_the_animal_position(
        self, tmp_path: Path
    ) -> None:
        analysis(tmp_path / "a.analysis.h5")
        params = {p.name: p for p in detection_for(tmp_path).parameters}
        assert params["keypoint"].choices == tuple(NODES) and not params["keypoint"].required
        for needed in ("fps", "width_px", "height_px"):
            assert params[needed].required

    def test_it_is_tested_against_real_output(self) -> None:
        assert SleapAnalysisReader.verification == "real_sample"

    def test_a_deeplabcut_h5_is_not_a_sleap_file(self, tmp_path: Path) -> None:
        with h5py.File(tmp_path / "dlc.h5", "w") as f:
            f.create_dataset("df_with_missing", data=np.zeros((3, 3)))
        assert scan([tmp_path]).groups == ()

    def test_a_stitched_tracklet_file_whose_tracks_is_a_group_is_not_one(
        self, tmp_path: Path
    ) -> None:
        with h5py.File(tmp_path / "x_el.h5", "w") as f:
            f.create_group("tracks")
            f.create_dataset("track_names", data=np.array([b"a"]))
            f.create_dataset("node_names", data=np.array([b"n"]))
            f.create_dataset("track_occupancy", data=np.zeros((3, 1), dtype=np.uint8))
        assert scan([tmp_path]).groups == ()

    @pytest.mark.parametrize("missing", ["track_occupancy", "node_names", "track_names"])
    def test_a_file_missing_one_of_the_markers_is_not_claimed(
        self, tmp_path: Path, missing: str
    ) -> None:
        f = analysis(tmp_path / "a.analysis.h5")
        with h5py.File(f, "a") as handle:
            del handle[missing]
        assert scan([tmp_path]).groups == ()

    def test_tracks_that_are_not_four_dimensional_are_not_claimed(self, tmp_path: Path) -> None:
        f = analysis(tmp_path / "a.analysis.h5")
        with h5py.File(f, "a") as handle:
            del handle["tracks"]
            handle.create_dataset("tracks", data=np.zeros((2, 40)))
        assert scan([tmp_path]).groups == ()

    def test_a_damaged_file_is_not_claimed_and_never_raises(self, tmp_path: Path) -> None:
        f = analysis(tmp_path / "a.analysis.h5")
        data = f.read_bytes()
        f.write_bytes(data[: len(data) // 3])
        (tmp_path / "empty.h5").write_bytes(b"")
        assert scan([tmp_path]).groups == ()

    def test_detect_accepts_a_file_or_a_folder_holding_one(self, tmp_path: Path) -> None:
        f = analysis(tmp_path / "a.analysis.h5")
        assert SleapAnalysisReader.detect(f) and SleapAnalysisReader.detect(tmp_path)
        assert not SleapAnalysisReader.detect(tmp_path / "nothing")

    def test_synthetic_track_names_are_flagged(self, tmp_path: Path) -> None:
        analysis(tmp_path / "a.analysis.h5", names=["track_0", "track_1"])
        (session,) = detection_for(tmp_path).sessions
        assert any("not identities" in w for w in session.warnings)

    def test_real_names_and_a_single_slot_raise_no_warning(self, tmp_path: Path) -> None:
        analysis(tmp_path / "named.analysis.h5")
        analysis(tmp_path / "solo.analysis.h5", n_tracks=1, names=None)
        assert all(s.warnings == () for s in detection_for(tmp_path).sessions)

    def test_a_deeplabcut_csv_next_to_it_is_a_separate_group(self, tmp_path: Path) -> None:
        analysis(tmp_path / "a.analysis.h5")
        write_dlc_csv(tmp_path / "d.csv", random_pose(10, 1, 3), bodyparts=NODES)
        readers_found = {g.best.reader for g in scan([tmp_path]).groups}
        assert readers_found == {"sleap_analysis", "deeplabcut"}


class TestReading:
    def test_tracks_become_animals_and_the_node_becomes_the_position(self, tmp_path: Path) -> None:
        tracks = random_tracks(40, 2, 3)
        f = analysis(tmp_path / "trial.analysis.h5", tracks=tracks)
        s = read(f, keypoint="ear")
        assert (s.n_frames, s.n_animals) == (40, 2) and s.raw_xy.shape == (40, 2, 2)
        assert np.allclose(s.raw_xy[:, 1, :], tracks[1, :, 1, :].T)  # (frames, xy) of node "ear"
        assert s.session_id == "trial" and s.folder == f and s.reader == "sleap_analysis"
        assert (s.video.fps, s.video.width_px, s.video.height_px) == (30.0, 640, 480)
        assert s.trajectory_source == f

    def test_a_folder_holding_the_file_reads_the_same_as_the_file(self, tmp_path: Path) -> None:
        f = analysis(tmp_path / "a.analysis.h5")
        assert np.array_equal(read(f).raw_xy, read(tmp_path).raw_xy, equal_nan=True)

    def test_the_whole_skeleton_is_kept_with_edges_and_scores(self, tmp_path: Path) -> None:
        tracks = random_tracks(40, 2, 3)
        scores = np.random.default_rng(1).uniform(0.5, 1, size=(2, 3, 40))
        f = analysis(tmp_path / "a.analysis.h5", tracks=tracks, edges=[(0, 1), (1, 2)],
                     point_scores=scores)  # fmt: skip
        kp = read(f, keypoint="snout").keypoints
        assert kp.names == NODES and kp.xy.shape == (40, 2, 3, 2) and kp.edges == [(0, 1), (1, 2)]
        assert kp.confidence.shape == (40, 2, 3)
        assert np.allclose(kp.confidence[:, 1, 2], scores[1, 2, :], atol=1e-6)
        assert np.allclose(kp.xy[:, 0, 1, 0], tracks[0, 0, 1, :], atol=1e-3)

    def test_a_skeleton_with_no_edges_is_fine(self, tmp_path: Path) -> None:
        assert read(analysis(tmp_path / "a.analysis.h5")).keypoints.edges == []

    def test_no_scores_means_no_confidence(self, tmp_path: Path) -> None:
        assert read(analysis(tmp_path / "a.analysis.h5")).keypoints.confidence is None

    def test_the_skeleton_can_be_declined(self, tmp_path: Path) -> None:
        assert read(analysis(tmp_path / "a.analysis.h5"), keep_skeleton=False).keypoints is None

    def test_without_a_named_node_the_best_covered_one_is_used(self, tmp_path: Path) -> None:
        tracks = random_tracks(40, 1, 3)
        tracks[:, :, 0, :20] = np.nan
        s = read(analysis(tmp_path / "a.analysis.h5", tracks=tracks, names=None))
        assert s.keypoints.selection.keypoint != "snout"
        assert s.keypoints.selection.chosen_by == "coverage"

    def test_missing_positions_stay_missing(self, tmp_path: Path) -> None:
        tracks = random_tracks(40, 2, 3)
        tracks[1, :, :, 5:9] = np.nan
        s = read(analysis(tmp_path / "a.analysis.h5", tracks=tracks), keypoint="snout")
        assert np.isnan(s.raw_xy[5:9, 1]).all() and np.isfinite(s.raw_xy[5:9, 0]).all()

    def test_scores_are_not_a_cutoff_unless_asked(self, tmp_path: Path) -> None:
        scores = np.full((2, 3, 40), 0.1)
        f = analysis(tmp_path / "a.analysis.h5", point_scores=scores)
        s = read(f, keypoint="snout")
        assert np.isfinite(s.raw_xy).all() and s.keypoints.selection.cutoff is None

    def test_a_cutoff_that_removes_everything_says_so(self, tmp_path: Path) -> None:
        f = analysis(tmp_path / "a.analysis.h5", point_scores=np.full((2, 3, 40), 0.1))
        with pytest.raises(Track2DataError) as caught:
            read(f, score_cutoff=0.5)
        assert caught.value.code == "POSE_NO_POSITIONS"

    def test_a_cutoff_masks_low_scoring_positions(self, tmp_path: Path) -> None:
        scores = np.ones((2, 3, 40))
        scores[0, 0, 3:6] = 0.1
        f = analysis(tmp_path / "a.analysis.h5", point_scores=scores)
        s = read(f, keypoint="snout", score_cutoff=0.5)
        assert np.isnan(s.raw_xy[3:6, 0]).all() and np.isfinite(s.raw_xy[3:6, 1]).all()

    def test_reading_never_modifies_the_input(self, tmp_path: Path) -> None:
        analysis(tmp_path / "s" / "a.analysis.h5")
        before = tree_hash(tmp_path / "s")
        read(tmp_path / "s")
        assert tree_hash(tmp_path / "s") == before


class TestWhatAMissingNameMeans:
    def test_named_tracks_are_stable_identities_with_labels(self, tmp_path: Path) -> None:
        s = read(analysis(tmp_path / "a.analysis.h5", names=["AEON_A", "AEON_B"]))
        assert s.has_stable_identities and s.identities_labels == ["AEON_A", "AEON_B"]
        assert s.track_wo_identities is None

    def test_a_project_with_no_tracks_and_one_slot_is_one_animal(self, tmp_path: Path) -> None:
        s = read(analysis(tmp_path / "a.analysis.h5", n_tracks=1, names=None))
        assert s.n_animals == 1 and s.has_stable_identities and s.identities_labels is None

    def test_no_names_but_several_slots_is_identity_free(self, tmp_path: Path) -> None:
        s = read(analysis(tmp_path / "a.analysis.h5", n_tracks=3, names=None))
        assert s.n_animals == 3
        assert s.has_stable_identities is False and s.track_wo_identities is True
        assert s.identities_labels is None

    def test_synthetic_track_names_are_not_identities_either(self, tmp_path: Path) -> None:
        s = read(analysis(tmp_path / "a.analysis.h5", names=["track_0", "track_1"]))
        assert s.has_stable_identities is False and s.track_wo_identities is True


class TestTheLayoutIsCheckedNotGuessed:
    def test_the_standard_dims_attribute_is_accepted(self, tmp_path: Path) -> None:
        f = analysis(tmp_path / "a.analysis.h5", dims='["track", "xy", "node", "frame"]')
        assert read(f).n_frames == 40

    def test_a_different_axis_order_is_refused_not_guessed(self, tmp_path: Path) -> None:
        f = analysis(tmp_path / "a.analysis.h5", dims='["frame", "node", "xy", "track"]')
        with pytest.raises(Track2DataError) as caught:
            read(f)
        assert caught.value.code == "SLEAP_LAYOUT_UNSUPPORTED" and caught.value.remediation

    def test_shapes_that_disagree_with_the_occupancy_are_refused(self, tmp_path: Path) -> None:
        f = analysis(tmp_path / "a.analysis.h5", occupancy=np.ones((7, 2), dtype=np.uint8))
        with pytest.raises(Track2DataError) as caught:
            read(f)
        assert caught.value.code == "SLEAP_LAYOUT_AMBIGUOUS"

    def test_a_node_count_that_disagrees_with_the_names_is_refused(self, tmp_path: Path) -> None:
        f = write_sleap_analysis(
            tmp_path / "a.analysis.h5",
            random_tracks(40, 2, 3),
            node_names=["only", "two"],
            track_names=["a", "b"],
        )
        with pytest.raises(Track2DataError) as caught:
            read(f)
        assert caught.value.code == "SLEAP_LAYOUT_AMBIGUOUS"


class TestWhatIsNeverInvented:
    @pytest.mark.parametrize("missing", ["fps", "width_px", "height_px"])
    def test_a_video_fact_the_file_does_not_record_must_be_given(
        self, tmp_path: Path, missing: str
    ) -> None:
        f = analysis(tmp_path / "a.analysis.h5")
        options = {k: v for k, v in VIDEO.items() if k != missing}
        with pytest.raises(Track2DataError) as caught:
            readers.read_session(f, reader="sleap_analysis", options=options)
        assert caught.value.code == "READER_OPTION_MISSING" and caught.value.subject == missing

    def test_an_unknown_node_lists_the_ones_there_are(self, tmp_path: Path) -> None:
        f = analysis(tmp_path / "a.analysis.h5")
        with pytest.raises(Track2DataError) as caught:
            read(f, keypoint="wing")
        assert caught.value.code == "READER_OPTION_INVALID" and "snout" in caught.value.remediation


class TestDamagedAndAmbiguousInput:
    def test_a_folder_with_two_files_asks_which(self, tmp_path: Path) -> None:
        analysis(tmp_path / "a.analysis.h5")
        analysis(tmp_path / "b.analysis.h5")
        with pytest.raises(Track2DataError) as caught:
            read(tmp_path)
        err = caught.value
        assert err.code == "SESSION_AMBIGUOUS" and "a.analysis.h5" in err.remediation

    def test_an_h5_that_is_not_a_sleap_file_is_a_coded_error(self, tmp_path: Path) -> None:
        with h5py.File(tmp_path / "x.h5", "w") as f:
            f.create_dataset("other", data=np.zeros(3))
        with pytest.raises(Track2DataError) as caught:
            SleapAnalysisReader().read(tmp_path / "x.h5", options={**VIDEO, "keypoint": None})
        assert caught.value.code == "SLEAP_NOT_AN_ANALYSIS_FILE" and caught.value.remediation

    @pytest.mark.parametrize("how", ["empty", "truncated"])
    def test_a_damaged_file_is_a_coded_error(self, tmp_path: Path, how: str) -> None:
        f = analysis(tmp_path / "a.analysis.h5")
        data = f.read_bytes()
        f.write_bytes(b"" if how == "empty" else data[: len(data) // 2])
        with pytest.raises(Track2DataError) as caught:
            SleapAnalysisReader().read(f, options={**VIDEO, "keypoint": None})
        assert caught.value.code != "UNKNOWN" and caught.value.remediation

    def test_no_such_path_is_a_coded_error(self, tmp_path: Path) -> None:
        with pytest.raises(Track2DataError) as caught:
            SleapAnalysisReader().read(tmp_path / "gone", options={**VIDEO, "keypoint": None})
        assert caught.value.code == "SLEAP_NO_FILE"

    def test_no_frames_is_a_coded_error(self, tmp_path: Path) -> None:
        f = analysis(tmp_path / "a.analysis.h5", tracks=np.zeros((2, 2, 3, 0)))
        with pytest.raises(Track2DataError) as caught:
            read(f)
        assert caught.value.code == "READER_OUTPUT_INVALID"


class TestThroughTheRestOfTheApp:
    def test_it_is_registered_and_listed(self) -> None:
        assert "sleap_analysis" in readers.reader_names()
        assert readers.find_reader("sleap_analysis") is SleapAnalysisReader

    def test_auto_detection_picks_it_for_a_folder_with_one_file(self, tmp_path: Path) -> None:
        analysis(tmp_path / "a.analysis.h5")
        assert readers.detect_reader(tmp_path) is SleapAnalysisReader

    def test_idtracker_folders_are_not_claimed(self, tiny_real_session: Path) -> None:
        assert not SleapAnalysisReader.detect(tiny_real_session)

    def test_only_it_claims_a_sleap_file(self, tmp_path: Path) -> None:
        analysis(tmp_path / "a.analysis.h5")
        assert [c.name for c in readers._REGISTRY if c.detect(tmp_path)] == ["sleap_analysis"]

    def test_probe_reads_it_too(self, tmp_path: Path) -> None:
        f = analysis(tmp_path / "a.analysis.h5")
        s = readers.probe_session(f, reader="sleap_analysis", options=VIDEO)
        assert s.n_animals == 2


class TestMoreLayoutChecks:
    def test_a_track_count_that_disagrees_with_the_names_is_refused(self, tmp_path: Path) -> None:
        f = write_sleap_analysis(
            tmp_path / "a.analysis.h5",
            random_tracks(40, 2, 3),
            node_names=NODES,
            track_names=["only_one"],
        )
        with pytest.raises(Track2DataError) as caught:
            read(f)
        assert caught.value.code == "SLEAP_LAYOUT_AMBIGUOUS" and "track_names" in str(caught.value)

    def test_a_second_axis_that_is_not_x_and_y_is_refused(self, tmp_path: Path) -> None:
        tracks = np.zeros((2, 3, 3, 40))  # 3 coordinates: not a 2-D SLEAP export
        f = write_sleap_analysis(
            tmp_path / "a.analysis.h5", tracks, node_names=NODES, track_names=["a", "b"]
        )
        with pytest.raises(Track2DataError) as caught:
            read(f)
        assert caught.value.code == "SLEAP_LAYOUT_AMBIGUOUS" and "not 2" in str(caught.value)

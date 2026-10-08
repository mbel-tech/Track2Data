"""The DeepLabCut CSV reader (also Lightning Pose and EKS tables).

Built from tables written in the real layouts (tests/support/dlc.py); the real files they imitate
are exercised by the opt-in suite in tests/real_samples. What is pinned here: what counts as a
DeepLabCut file, what the scan offers the user, which keypoint becomes the animal, and that a
frame rate or frame size is never invented.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import numpy as np
import pytest

from tests.support.dlc import random_pose, write_dlc_csv
from track2data import readers
from track2data.core.errors import Track2DataError
from track2data.readers.deeplabcut import DeepLabCutReader
from track2data.readers.detection import Confidence
from track2data.readers.scan import scan

BPS = ["snout", "tail", "ear"]
VIDEO = {"fps": 25.0, "width_px": 640, "height_px": 480}


def single(path: Path, n: int = 50, **kw) -> Path:
    xy = random_pose(n, 1, 3)
    return write_dlc_csv(path, xy, kw.pop("likelihood", None), bodyparts=BPS, **kw)


def multi(path: Path, n: int = 50, animals=("mouse1", "mouse2"), **kw) -> Path:
    xy = random_pose(n, len(animals), 3)
    return write_dlc_csv(
        path, xy, kw.pop("likelihood", None), bodyparts=BPS, individuals=list(animals), **kw
    )


def read(path: Path, **options):
    return readers.read_session(path, reader="deeplabcut", options={**VIDEO, **options})


def tree_hash(folder: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(Path(folder).rglob("*")):
        if p.is_file():
            h.update(p.name.encode() + p.read_bytes())
    return h.hexdigest()


def detection_for(root: Path):
    (group,) = scan([root]).groups
    return group.best


class TestWhatIsADeepLabCutFile:
    def test_a_single_animal_table_is_recognised_with_high_confidence(self, tmp_path: Path) -> None:
        single(tmp_path / "trial1DLC_resnet50.csv")
        d = detection_for(tmp_path)
        assert d.reader == "deeplabcut" and d.confidence is Confidence.HIGH
        assert [s.session_id for s in d.sessions] == ["trial1DLC_resnet50"]

    def test_a_multi_animal_table_is_recognised(self, tmp_path: Path) -> None:
        multi(tmp_path / "m.csv")
        d = detection_for(tmp_path)
        assert d.confidence is Confidence.HIGH and "individuals" in " ".join(d.evidence)

    def test_every_file_in_a_folder_is_its_own_session(self, tmp_path: Path) -> None:
        for name in ("a", "b", "c"):
            single(tmp_path / f"{name}.csv")
        d = detection_for(tmp_path)
        assert [s.session_id for s in d.sessions] == ["a", "b", "c"]
        assert all(s.source.suffix == ".csv" for s in d.sessions)

    def test_a_folder_of_folders_is_walked(self, tmp_path: Path) -> None:
        single(tmp_path / "day1" / "a.csv")
        single(tmp_path / "day2" / "b.csv")
        assert len(detection_for(tmp_path).sessions) == 2

    def test_the_keypoints_are_offered_as_the_choices_for_the_animal_position(
        self, tmp_path: Path
    ) -> None:
        single(tmp_path / "a.csv")
        params = {p.name: p for p in detection_for(tmp_path).parameters}
        assert params["keypoint"].kind == "choice" and params["keypoint"].choices == tuple(BPS)
        assert not params["keypoint"].required
        for needed in ("fps", "width_px", "height_px"):
            assert params[needed].required

    def test_the_individuals_are_offered_for_a_multi_animal_file(self, tmp_path: Path) -> None:
        multi(tmp_path / "m.csv")
        params = {p.name: p for p in detection_for(tmp_path).parameters}
        assert params["individuals"].choices == ("mouse1", "mouse2")

    def test_a_table_with_no_likelihood_is_not_a_prediction_file(self, tmp_path: Path) -> None:
        # DeepLabCut's own CollectedData annotation files and 3-D tables have no likelihood.
        xy = random_pose(10, 1, 3)
        write_dlc_csv(tmp_path / "labels.csv", xy, bodyparts=BPS, coords=("x", "y"))
        assert scan([tmp_path]).groups == ()

    def test_an_ordinary_csv_is_not_taken_for_one(self, tmp_path: Path) -> None:
        (tmp_path / "data.csv").write_text("frame,x,y\n0,1,2\n1,2,3\n")
        (tmp_path / "scorer_notes.csv").write_text("scorer,x\nbob,1\n")
        assert scan([tmp_path]).groups == ()

    def test_a_bom_and_windows_line_endings_do_not_matter(self, tmp_path: Path) -> None:
        f = single(tmp_path / "a.csv")
        f.write_bytes(
            b"\xef\xbb\xbf" + f.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        )
        assert detection_for(tmp_path).confidence is Confidence.HIGH
        assert read(f).n_frames == 50

    def test_empty_and_one_line_files_are_not_claimed_and_never_raise(self, tmp_path: Path) -> None:
        (tmp_path / "empty.csv").write_bytes(b"")
        (tmp_path / "one.csv").write_text("scorer\n")
        assert scan([tmp_path]).groups == ()

    def test_detect_accepts_a_file_or_a_folder_holding_one(self, tmp_path: Path) -> None:
        f = single(tmp_path / "a.csv")
        assert DeepLabCutReader.detect(f) and DeepLabCutReader.detect(tmp_path)
        assert not DeepLabCutReader.detect(tmp_path / "nothing")

    def test_a_lightning_pose_table_proposes_no_likelihood_cutoff(self, tmp_path: Path) -> None:
        single(tmp_path / "eks.csv", extra_coords=True, scorer="ensemble-kalman_tracker")
        d = detection_for(tmp_path)
        assert d.proposed["likelihood_cutoff"].value == 0.0
        assert d.proposed["likelihood_cutoff"].source == "tool-default"

    def test_a_plain_deeplabcut_table_proposes_nothing_about_the_cutoff(
        self, tmp_path: Path
    ) -> None:
        single(tmp_path / "a.csv")
        assert "likelihood_cutoff" not in detection_for(tmp_path).proposed

    def test_positional_individual_names_are_flagged(self, tmp_path: Path) -> None:
        multi(tmp_path / "m.csv", animals=("ind1", "ind2"))
        (session,) = detection_for(tmp_path).sessions
        assert any("ind1" in w and "not identities" in w for w in session.warnings)

    def test_it_is_tested_against_real_output(self) -> None:
        assert DeepLabCutReader.verification == "real_sample"


class TestReading:
    def test_a_single_animal_file_becomes_one_animal(self, tmp_path: Path) -> None:
        f = single(tmp_path / "trial1.csv", n=40)
        s = read(f, keypoint="snout")
        assert (s.n_frames, s.n_animals) == (40, 1) and s.raw_xy.shape == (40, 1, 2)
        assert s.reader == "deeplabcut" and s.session_id == "trial1" and s.folder == f
        assert (s.video.fps, s.video.width_px, s.video.height_px) == (25.0, 640, 480)
        assert s.has_stable_identities and s.trajectory_variant == "with_gaps"
        assert s.trajectory_source == f

    def test_the_position_is_the_named_keypoint(self, tmp_path: Path) -> None:
        xy = random_pose(30, 1, 3)
        f = write_dlc_csv(tmp_path / "a.csv", xy, bodyparts=BPS)
        s = read(f, keypoint="tail")
        assert np.allclose(s.raw_xy[:, 0, :], xy[:, 0, 1, :])
        assert s.keypoints is not None and s.keypoints.selection.keypoint == "tail"
        assert s.keypoints.selection.chosen_by == "user"

    def test_a_folder_holding_the_file_reads_the_same_as_the_file(self, tmp_path: Path) -> None:
        f = single(tmp_path / "a.csv")
        assert np.array_equal(read(f).raw_xy, read(tmp_path).raw_xy, equal_nan=True)

    def test_the_whole_skeleton_is_kept_beside_it(self, tmp_path: Path) -> None:
        xy = random_pose(30, 1, 3)
        s = read(write_dlc_csv(tmp_path / "a.csv", xy, bodyparts=BPS), keypoint="snout")
        kp = s.keypoints
        assert kp is not None and kp.names == BPS and kp.xy.shape == (30, 1, 3, 2)
        assert kp.confidence is not None and kp.confidence.shape == (30, 1, 3)
        assert np.allclose(kp.xy[:, 0, 2, :], xy[:, 0, 2, :], atol=1e-3)

    def test_the_skeleton_can_be_declined(self, tmp_path: Path) -> None:
        f = single(tmp_path / "a.csv")
        assert read(f, keep_skeleton=False).keypoints is None

    def test_without_a_named_keypoint_the_best_covered_one_is_used(self, tmp_path: Path) -> None:
        xy = random_pose(40, 1, 3)
        xy[:20, 0, 0, :] = np.nan  # snout missing half the time
        f = write_dlc_csv(tmp_path / "a.csv", xy, bodyparts=BPS)
        s = read(f)
        assert s.keypoints.selection.keypoint == "tail"
        assert s.keypoints.selection.chosen_by == "coverage"

    def test_a_multi_animal_file_keeps_the_individuals_in_order_with_their_names(
        self, tmp_path: Path
    ) -> None:
        f = multi(tmp_path / "m.csv", animals=("mouseA", "mouseB"))
        s = read(f, keypoint="snout")
        assert s.n_animals == 2 and s.identities_labels == ["mouseA", "mouseB"]
        assert s.has_stable_identities and s.keypoints.xy.shape == (50, 2, 3, 2)

    def test_the_catch_all_single_individual_is_left_out_unless_asked_for(
        self, tmp_path: Path
    ) -> None:
        f = multi(tmp_path / "m.csv", animals=("mouse1", "mouse2", "single"))
        assert read(f).identities_labels == ["mouse1", "mouse2"]
        assert read(f, individuals=["mouse1", "single"]).identities_labels == ["mouse1", "single"]

    def test_positions_below_the_default_cutoff_are_missing(self, tmp_path: Path) -> None:
        xy = random_pose(30, 1, 3)
        lik = np.ones((30, 1, 3))
        lik[5:8, 0, :] = 0.01  # a human-filled gap carries a likelihood of 0.01
        s = read(write_dlc_csv(tmp_path / "a.csv", xy, lik, bodyparts=BPS), keypoint="snout")
        assert np.isnan(s.raw_xy[5:8]).all() and np.isfinite(s.raw_xy[:5]).all()
        assert s.keypoints.selection.cutoff == 0.6

    def test_a_cutoff_of_zero_keeps_everything(self, tmp_path: Path) -> None:
        lik = np.full((30, 1, 3), 0.01)
        f = write_dlc_csv(tmp_path / "a.csv", random_pose(30, 1, 3), lik, bodyparts=BPS)
        s = read(f, keypoint="snout", likelihood_cutoff=0.0)
        assert np.isfinite(s.raw_xy).all() and s.keypoints.selection.cutoff is None

    def test_empty_cells_are_missing_not_zero(self, tmp_path: Path) -> None:
        xy = random_pose(20, 1, 3)
        xy[4, 0, 0, :] = np.nan
        s = read(write_dlc_csv(tmp_path / "a.csv", xy, bodyparts=BPS), keypoint="snout")
        assert np.isnan(s.raw_xy[4]).all() and np.isfinite(s.raw_xy[3]).all()

    def test_extra_columns_from_lightning_pose_are_ignored_by_name(self, tmp_path: Path) -> None:
        xy = random_pose(25, 1, 3)
        plain = write_dlc_csv(tmp_path / "plain" / "a.csv", xy, bodyparts=BPS)
        extra = write_dlc_csv(tmp_path / "extra" / "a.csv", xy, bodyparts=BPS, extra_coords=True)
        a, b = read(plain, keypoint="snout"), read(extra, keypoint="snout")
        assert np.array_equal(a.raw_xy, b.raw_xy, equal_nan=True)
        assert b.keypoints.xy.shape == (25, 1, 3, 2)

    def test_frames_are_placed_by_their_index(self, tmp_path: Path) -> None:
        xy = random_pose(3, 1, 3)
        f = write_dlc_csv(tmp_path / "a.csv", xy, bodyparts=BPS, frames=[0, 1, 4])
        s = read(f, keypoint="snout")
        assert s.n_frames == 5 and np.isnan(s.raw_xy[2:4]).all()
        assert np.allclose(s.raw_xy[4, 0], xy[2, 0, 0], atol=1e-6)

    def test_positional_individuals_are_not_claimed_to_be_identities(self, tmp_path: Path) -> None:
        f = multi(tmp_path / "m.csv", animals=("ind1", "ind2"))
        assert read(f, keypoint="snout").has_stable_identities is False

    def test_a_single_animal_is_stable_by_construction(self, tmp_path: Path) -> None:
        assert read(single(tmp_path / "a.csv")).has_stable_identities is True

    def test_reading_never_modifies_the_input(self, tmp_path: Path) -> None:
        single(tmp_path / "s" / "a.csv")
        before = tree_hash(tmp_path / "s")
        read(tmp_path / "s")
        assert tree_hash(tmp_path / "s") == before


class TestWhatIsNeverInvented:
    @pytest.mark.parametrize("missing", ["fps", "width_px", "height_px"])
    def test_a_video_fact_the_file_does_not_record_must_be_given(
        self, tmp_path: Path, missing: str
    ) -> None:
        f = single(tmp_path / "a.csv")
        options = {k: v for k, v in VIDEO.items() if k != missing}
        with pytest.raises(Track2DataError) as caught:
            readers.read_session(f, reader="deeplabcut", options=options)
        assert caught.value.code == "READER_OPTION_MISSING" and caught.value.subject == missing

    def test_an_impossible_value_is_refused(self, tmp_path: Path) -> None:
        f = single(tmp_path / "a.csv")
        with pytest.raises(Track2DataError) as caught:
            read(f, fps=0.0)
        assert caught.value.code == "READER_OPTION_INVALID"

    def test_an_unknown_keypoint_lists_the_ones_there_are(self, tmp_path: Path) -> None:
        f = single(tmp_path / "a.csv")
        with pytest.raises(Track2DataError) as caught:
            read(f, keypoint="wing")
        assert caught.value.code == "READER_OPTION_INVALID"
        assert "snout" in caught.value.remediation

    def test_an_unknown_individual_lists_the_ones_there_are(self, tmp_path: Path) -> None:
        f = multi(tmp_path / "m.csv")
        with pytest.raises(Track2DataError) as caught:
            read(f, individuals=["mouse9"])
        assert caught.value.code == "READER_OPTION_INVALID" and "mouse1" in caught.value.remediation

    def test_individuals_on_a_single_animal_file_is_refused(self, tmp_path: Path) -> None:
        f = single(tmp_path / "a.csv")
        with pytest.raises(Track2DataError) as caught:
            read(f, individuals=["x"])
        assert caught.value.code == "READER_OPTION_INVALID"


class TestDamagedAndAmbiguousInput:
    def test_a_folder_with_two_files_asks_which(self, tmp_path: Path) -> None:
        single(tmp_path / "a.csv")
        single(tmp_path / "b.csv")
        with pytest.raises(Track2DataError) as caught:
            read(tmp_path)
        err = caught.value
        assert err.code == "SESSION_AMBIGUOUS" and "a.csv" in err.remediation
        assert "b.csv" in err.remediation

    def test_an_empty_file_is_a_coded_error(self, tmp_path: Path) -> None:
        f = tmp_path / "a.csv"
        f.write_bytes(b"")
        with pytest.raises(Track2DataError) as caught:
            DeepLabCutReader().read(f, options={**VIDEO, "keypoint": None})
        assert caught.value.code != "UNKNOWN" and caught.value.remediation

    def test_a_file_that_is_not_deeplabcut_is_a_coded_error(self, tmp_path: Path) -> None:
        f = tmp_path / "a.csv"
        f.write_text("frame,x,y\n0,1,2\n")
        with pytest.raises(Track2DataError) as caught:
            DeepLabCutReader().read(f, options={**VIDEO})
        assert caught.value.code == "DLC_NOT_A_PREDICTION_FILE" and caught.value.remediation

    def test_a_file_cut_off_mid_row_is_a_coded_error_not_a_crash(self, tmp_path: Path) -> None:
        f = single(tmp_path / "a.csv", n=30)
        data = f.read_bytes()
        f.write_bytes(data[: len(data) // 2])
        try:
            s = read(f)
        except Track2DataError as err:
            assert err.code != "UNKNOWN" and err.remediation
        else:  # a cut at a line end is a valid, shorter file
            assert s.n_frames < 30

    def test_non_numeric_cells_are_a_coded_error(self, tmp_path: Path) -> None:
        f = single(tmp_path / "a.csv", n=10)
        f.write_text(f.read_text().replace("\n3,", "\nthree,", 1))
        with pytest.raises(Track2DataError) as caught:
            read(f)
        assert caught.value.code == "DLC_BAD_FRAME_INDEX"

    def test_no_frames_is_a_coded_error(self, tmp_path: Path) -> None:
        f = single(tmp_path / "a.csv", n=5)
        header = "\n".join(f.read_text().splitlines()[:3]) + "\n"
        f.write_text(header)
        with pytest.raises(Track2DataError) as caught:
            read(f)
        assert caught.value.code == "READER_OUTPUT_INVALID"


class TestThroughTheRestOfTheApp:
    def test_it_is_registered_and_listed(self) -> None:
        assert "deeplabcut" in readers.reader_names()
        assert readers.find_reader("deeplabcut") is DeepLabCutReader

    def test_auto_detection_picks_it_for_a_folder_with_one_file(self, tmp_path: Path) -> None:
        single(tmp_path / "a.csv")
        assert readers.detect_reader(tmp_path) is DeepLabCutReader

    def test_idtracker_folders_are_not_claimed(self, tiny_real_session: Path) -> None:
        assert not DeepLabCutReader.detect(tiny_real_session)

    def test_a_dlc_file_does_not_make_idtracker_claim_the_folder(self, tmp_path: Path) -> None:
        single(tmp_path / "a.csv")
        names = [c.name for c in readers._REGISTRY if c.detect(tmp_path)]
        assert names == ["deeplabcut"]

    def test_probe_reads_it_too(self, tmp_path: Path) -> None:
        f = single(tmp_path / "a.csv")
        s = readers.probe_session(f, reader="deeplabcut", options=VIDEO)
        assert s.n_animals == 1

    def test_copying_the_file_elsewhere_reads_the_same(self, tmp_path: Path) -> None:
        f = single(tmp_path / "a.csv")
        g = tmp_path / "elsewhere" / "renamed.csv"
        g.parent.mkdir()
        shutil.copy(f, g)
        assert np.array_equal(read(f).raw_xy, read(g).raw_xy, equal_nan=True)
        assert read(g).session_id == "renamed"


class TestALikelihoodColumnThatSaysNothing:
    """EKS (ensemble Kalman) tables write a likelihood of exactly 0 for every frame: a
    placeholder. A cutoff applied to it would erase the whole recording."""

    def zero_likelihood_file(self, tmp_path: Path) -> Path:
        xy = random_pose(30, 1, 3)
        return write_dlc_csv(
            tmp_path / "eks.csv", xy, np.zeros((30, 1, 3)), bodyparts=BPS, extra_coords=True
        )

    def test_the_default_cutoff_does_not_erase_the_recording(self, tmp_path: Path) -> None:
        s = read(self.zero_likelihood_file(tmp_path), keypoint="snout")
        assert np.isfinite(s.raw_xy).all()

    def test_the_cutoff_that_was_not_applied_is_recorded_as_none(self, tmp_path: Path) -> None:
        s = read(self.zero_likelihood_file(tmp_path), keypoint="snout", likelihood_cutoff=0.9)
        assert s.keypoints.selection.cutoff is None and s.keypoints.confidence is None

    def test_the_session_says_why(self, tmp_path: Path) -> None:
        s = read(self.zero_likelihood_file(tmp_path))
        assert s.raw_attrs and "likelihood" in s.raw_attrs["likelihood_ignored"]

    def test_a_real_file_with_some_zero_likelihoods_is_not_affected(self, tmp_path: Path) -> None:
        lik = np.ones((30, 1, 3))
        lik[3, 0, :] = 0.0
        f = write_dlc_csv(tmp_path / "a.csv", random_pose(30, 1, 3), lik, bodyparts=BPS)
        s = read(f, keypoint="snout")
        assert np.isnan(s.raw_xy[3]).all() and s.keypoints.confidence is not None
        assert not (s.raw_attrs or {}).get("likelihood_ignored")


class TestEdgesOfTheFormat:
    def test_a_header_that_does_not_start_with_scorer_is_not_deeplabcut(
        self, tmp_path: Path
    ) -> None:
        f = single(tmp_path / "a.csv")
        f.write_text(f.read_text().replace("scorer,", "tracker,", 1))
        assert scan([tmp_path]).groups == ()
        assert not DeepLabCutReader.detect(f)

    def test_a_repeated_frame_number_is_refused(self, tmp_path: Path) -> None:
        f = write_dlc_csv(tmp_path / "a.csv", random_pose(3, 1, 3), bodyparts=BPS, frames=[0, 1, 1])
        with pytest.raises(Track2DataError) as caught:
            read(f)
        assert caught.value.code == "DLC_BAD_FRAME_INDEX"

    def test_a_negative_frame_number_is_refused(self, tmp_path: Path) -> None:
        f = write_dlc_csv(
            tmp_path / "a.csv", random_pose(3, 1, 3), bodyparts=BPS, frames=[-1, 0, 1]
        )
        with pytest.raises(Track2DataError) as caught:
            read(f)
        assert caught.value.code == "DLC_BAD_FRAME_INDEX"

    def test_a_text_cell_among_the_numbers_is_refused_not_turned_into_missing(
        self, tmp_path: Path
    ) -> None:
        f = single(tmp_path / "a.csv", n=10)
        lines = f.read_text().splitlines()
        cells = lines[5].split(",")
        cells[2] = "oops"
        lines[5] = ",".join(cells)
        f.write_text("\n".join(lines) + "\n")
        with pytest.raises(Track2DataError) as caught:
            read(f)
        assert caught.value.code == "DLC_BAD_VALUE"

    def test_a_mixed_folder_proposes_no_cutoff_change(self, tmp_path: Path) -> None:
        single(tmp_path / "plain.csv")
        single(tmp_path / "eks.csv", extra_coords=True)
        assert "likelihood_cutoff" not in detection_for(tmp_path).proposed

    def test_one_animal_called_ind1_is_neither_flagged_nor_unstable(self, tmp_path: Path) -> None:
        f = multi(tmp_path / "m.csv", animals=("ind1",))
        (session,) = detection_for(tmp_path).sessions
        assert session.warnings == ()
        assert read(f, keypoint="snout").has_stable_identities is True

    def test_choosing_animals_in_a_single_animal_file_says_there_are_none_to_choose(
        self, tmp_path: Path
    ) -> None:
        f = single(tmp_path / "a.csv")
        with pytest.raises(Track2DataError) as caught:
            read(f, individuals=["x"])
        assert "no individuals row" in str(caught.value)

    def test_a_blank_keypoint_means_not_chosen(self, tmp_path: Path) -> None:
        f = single(tmp_path / "a.csv")
        s = read(f, keypoint="")
        assert s.keypoints.selection.chosen_by == "coverage"

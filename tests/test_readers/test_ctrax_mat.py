"""The Ctrax raw ``.mat`` reader.

Built from files written in the real layout (tests/support/ctrax.py); the real 12,033-frame file
they imitate is exercised by the opt-in suite in tests/real_samples. Pinned here: what counts as a
raw Ctrax file (and what must not: ``trx.mat`` is a different format), how a flat list of detections
becomes one slot per Ctrax track, that y is flipped back to image coordinates, and that the frame
rate comes from the file's timestamps while the frame size must be given.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest
import scipy.io as sio

from tests.support.ctrax import walkers, write_ctrax_mat
from track2data import readers
from track2data.core.errors import Track2DataError
from track2data.readers.ctrax_mat import CtraxMatReader
from track2data.readers.detection import Confidence
from track2data.readers.scan import scan

SIZE = {"width_px": 640, "height_px": 480}


def raw(path: Path, **kw) -> Path:
    frames = kw.pop("frames", None)
    return write_ctrax_mat(path, walkers(40, (0, 1)) if frames is None else frames, **kw)


def read(path: Path, **options):
    return readers.read_session(path, reader="ctrax_mat", options={**SIZE, **options})


def detection_for(root: Path):
    (group,) = scan([root]).groups
    return group.best


def tree_hash(folder: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(Path(folder).rglob("*")):
        if p.is_file():
            h.update(p.name.encode() + p.read_bytes())
    return h.hexdigest()


class TestWhatIsARawCtraxFile:
    def test_a_raw_file_is_recognised_with_high_confidence(self, tmp_path: Path) -> None:
        raw(tmp_path / "run1.mat")
        d = detection_for(tmp_path)
        assert d.reader == "ctrax_mat" and d.confidence is Confidence.HIGH
        assert [s.session_id for s in d.sessions] == ["run1"]

    def test_a_compressed_file_is_recognised_too(self, tmp_path: Path) -> None:
        raw(tmp_path / "run1.mat", compress=True)
        assert detection_for(tmp_path).confidence is Confidence.HIGH

    def test_every_file_in_a_folder_is_its_own_session(self, tmp_path: Path) -> None:
        raw(tmp_path / "a.mat")
        raw(tmp_path / "b.mat")
        assert [s.session_id for s in detection_for(tmp_path).sessions] == ["a", "b"]

    def test_the_scan_warns_that_identities_are_fragments(self, tmp_path: Path) -> None:
        raw(tmp_path / "a.mat")
        (session,) = detection_for(tmp_path).sessions
        assert any("fragment" in w for w in session.warnings)

    def test_the_frame_size_is_asked_for_and_the_frame_rate_is_not(self, tmp_path: Path) -> None:
        raw(tmp_path / "a.mat")
        params = {p.name: p for p in detection_for(tmp_path).parameters}
        assert params["width_px"].required and params["height_px"].required
        assert "fps" not in params  # the timestamps in the file give it
        assert not params["top_n"].required

    def test_a_trx_mat_is_a_different_format_and_is_not_claimed(self, tmp_path: Path) -> None:
        sio.savemat(tmp_path / "trx.mat", {"trx": np.zeros((1, 1))})
        assert scan([tmp_path]).groups == ()

    def test_a_file_that_has_a_trx_next_to_the_raw_variables_is_not_claimed(
        self, tmp_path: Path
    ) -> None:
        raw(tmp_path / "a.mat", extra={"trx": np.zeros((1, 1))})
        assert scan([tmp_path]).groups == ()

    @pytest.mark.parametrize("missing", ["ntargets", "x_pos", "y_pos", "identity", "timestamps"])
    def test_a_file_missing_a_marker_variable_is_not_claimed(
        self, tmp_path: Path, missing: str
    ) -> None:
        raw(tmp_path / "a.mat", drop=(missing,))
        assert scan([tmp_path]).groups == ()

    def test_an_ordinary_mat_file_is_not_claimed(self, tmp_path: Path) -> None:
        sio.savemat(tmp_path / "other.mat", {"data": np.zeros((4, 4))})
        assert scan([tmp_path]).groups == ()

    def test_a_v7_3_file_is_not_claimed_because_it_has_no_real_sample(self, tmp_path: Path) -> None:
        import h5py

        with h5py.File(tmp_path / "big.mat", "w") as f:
            f.create_dataset("ntargets", data=np.zeros(3))
        assert scan([tmp_path]).groups == ()

    def test_a_damaged_file_is_not_claimed_and_never_raises(self, tmp_path: Path) -> None:
        f = raw(tmp_path / "a.mat")
        data = f.read_bytes()
        f.write_bytes(data[: len(data) // 2])
        (tmp_path / "empty.mat").write_bytes(b"")
        scan([tmp_path])  # must not raise

    def test_detect_accepts_a_file_or_a_folder_holding_one(self, tmp_path: Path) -> None:
        f = raw(tmp_path / "a.mat")
        assert CtraxMatReader.detect(f) and CtraxMatReader.detect(tmp_path)
        assert not CtraxMatReader.detect(tmp_path / "nothing")

    def test_it_is_tested_against_real_output(self) -> None:
        assert CtraxMatReader.verification == "real_sample"


class TestReading:
    def test_each_ctrax_track_becomes_a_slot_with_positions_in_image_coordinates(
        self, tmp_path: Path
    ) -> None:
        frames = [
            [(7, 10.0, 20.0), (3, 100.0, 200.0)],
            [(7, 11.0, 21.0), (3, 101.0, 201.0)],
            [(7, 12.0, 22.0)],
        ]
        s = read(raw(tmp_path / "a.mat", frames=frames))
        assert (s.n_frames, s.n_animals) == (3, 2) and s.raw_xy.shape == (3, 2, 2)
        # slots are ordered by track id: 3 then 7
        assert s.raw_xy[0, 0].tolist() == [100.0, 200.0] and s.raw_xy[0, 1].tolist() == [10.0, 20.0]
        assert s.raw_xy[2, 1].tolist() == [12.0, 22.0] and np.isnan(s.raw_xy[2, 0]).all()
        assert s.identities_labels == ["3", "7"]

    def test_y_is_flipped_back_because_ctrax_measures_it_from_the_bottom(
        self, tmp_path: Path
    ) -> None:
        f = raw(tmp_path / "a.mat", frames=[[(0, 50.0, 10.0)], [(0, 51.0, 11.0)]])
        stored = sio.loadmat(f)["y_pos"].ravel()[0]
        assert stored == 470.0  # as Ctrax wrote it
        assert read(f).raw_xy[0, 0, 1] == 10.0  # as the image has it

    def test_the_flip_uses_the_height_that_was_given(self, tmp_path: Path) -> None:
        f = raw(tmp_path / "a.mat", frames=[[(0, 50.0, 10.0)], [(0, 51.0, 11.0)]])
        assert read(f, height_px=500).raw_xy[0, 0, 1] == 30.0

    def test_the_frame_rate_comes_from_the_timestamps(self, tmp_path: Path) -> None:
        s = read(raw(tmp_path / "a.mat", fps=30.0))
        assert s.video.fps == pytest.approx(30.0) and s.video.n_frames == 40
        assert (s.video.width_px, s.video.height_px) == (640, 480)

    def test_the_frame_rate_is_the_average_over_the_whole_span(self, tmp_path: Path) -> None:
        # Frame times jitter by a millisecond; only the whole span matters, never one step.
        ts = np.arange(40) / 25.0 + np.random.default_rng(0).normal(0, 0.001, 40)
        s = read(raw(tmp_path / "a.mat", timestamps=ts))
        assert s.video.fps == pytest.approx(39 / (ts[-1] - ts[0]))

    def test_fragments_are_not_identities(self, tmp_path: Path) -> None:
        s = read(raw(tmp_path / "a.mat"))
        assert s.has_stable_identities is False and s.track_wo_identities is True

    def test_there_is_no_skeleton(self, tmp_path: Path) -> None:
        assert read(raw(tmp_path / "a.mat")).keypoints is None

    def test_a_frame_with_no_detections_is_all_missing(self, tmp_path: Path) -> None:
        frames = [[(0, 5.0, 5.0)], [], [(0, 6.0, 6.0)]]
        s = read(raw(tmp_path / "a.mat", frames=frames))
        assert np.isnan(s.raw_xy[1]).all() and np.isfinite(s.raw_xy[2]).all()

    def test_a_tracking_run_that_started_late_keeps_its_true_frame_numbers(
        self, tmp_path: Path
    ) -> None:
        s = read(raw(tmp_path / "a.mat", startframe=100))
        assert s.tracking_intervals == [(100, 140)]
        assert read(raw(tmp_path / "b.mat")).tracking_intervals is None

    def test_a_folder_holding_the_file_reads_the_same_as_the_file(self, tmp_path: Path) -> None:
        f = raw(tmp_path / "a.mat")
        assert np.array_equal(read(f).raw_xy, read(tmp_path).raw_xy, equal_nan=True)

    def test_session_identity_comes_from_the_file(self, tmp_path: Path) -> None:
        f = raw(tmp_path / "trial 3.mat")
        s = read(f)
        assert s.session_id == "trial 3" and s.folder == f and s.trajectory_source == f
        assert s.reader == "ctrax_mat"

    def test_reading_never_modifies_the_input(self, tmp_path: Path) -> None:
        raw(tmp_path / "s" / "a.mat")
        before = tree_hash(tmp_path / "s")
        read(tmp_path / "s")
        assert tree_hash(tmp_path / "s") == before


class TestKeepingTheLongestTracks:
    def frames(self) -> list:
        # track 0 present in all 30 frames, track 5 in 20, track 9 in 10, track 2 in 3
        out = []
        for f in range(30):
            d = [(0, 10.0 + f, 10.0)]
            if f < 20:
                d.append((5, 50.0, 50.0 + f))
            if f < 10:
                d.append((9, 90.0, 90.0))
            if f < 3:
                d.append((2, 30.0, 30.0))
            out.append(d)
        return out

    def test_by_default_every_track_is_kept(self, tmp_path: Path) -> None:
        s = read(raw(tmp_path / "a.mat", frames=self.frames()))
        assert s.identities_labels == ["0", "2", "5", "9"]

    def test_top_n_keeps_the_longest_in_id_order(self, tmp_path: Path) -> None:
        s = read(raw(tmp_path / "a.mat", frames=self.frames()), top_n=2)
        assert s.identities_labels == ["0", "5"] and s.n_animals == 2

    def test_more_than_there_are_keeps_them_all(self, tmp_path: Path) -> None:
        s = read(raw(tmp_path / "a.mat", frames=self.frames()), top_n=50)
        assert s.n_animals == 4

    def test_the_kept_tracks_keep_their_positions(self, tmp_path: Path) -> None:
        s = read(raw(tmp_path / "a.mat", frames=self.frames()), top_n=1)
        assert s.raw_xy[5, 0].tolist() == [15.0, 10.0]

    def test_zero_is_refused(self, tmp_path: Path) -> None:
        f = raw(tmp_path / "a.mat")
        with pytest.raises(Track2DataError) as caught:
            read(f, top_n=0)
        assert caught.value.code == "READER_OPTION_INVALID"

    def test_equal_lengths_prefer_the_lower_id(self, tmp_path: Path) -> None:
        frames = [[(4, 1.0, 1.0), (1, 2.0, 2.0), (8, 3.0, 3.0)] for _ in range(5)]
        assert read(raw(tmp_path / "a.mat", frames=frames), top_n=2).identities_labels == ["1", "4"]


class TestWhatIsRefusedNotGuessed:
    @pytest.mark.parametrize("missing", ["width_px", "height_px"])
    def test_the_frame_size_must_be_given(self, tmp_path: Path, missing: str) -> None:
        f = raw(tmp_path / "a.mat")
        options = {k: v for k, v in SIZE.items() if k != missing}
        with pytest.raises(Track2DataError) as caught:
            readers.read_session(f, reader="ctrax_mat", options=options)
        assert caught.value.code == "READER_OPTION_MISSING" and caught.value.subject == missing

    def test_a_height_smaller_than_the_detections_is_refused(self, tmp_path: Path) -> None:
        f = raw(tmp_path / "a.mat", frames=[[(0, 5.0, 5.0)], [(0, 6.0, 6.0)]])
        with pytest.raises(Track2DataError) as caught:
            read(f, height_px=2)
        assert (
            caught.value.code == "CTRAX_FRAME_TOO_SHORT" and "480" not in caught.value.remediation
        )

    def test_timestamps_that_give_no_frame_rate_are_refused(self, tmp_path: Path) -> None:
        f = raw(tmp_path / "a.mat", timestamps=np.zeros(40))
        with pytest.raises(Track2DataError) as caught:
            read(f)
        assert caught.value.code == "CTRAX_BAD_TIMESTAMPS"

    def test_one_frame_cannot_give_a_frame_rate(self, tmp_path: Path) -> None:
        f = raw(tmp_path / "a.mat", frames=[[(0, 1.0, 1.0)]])
        with pytest.raises(Track2DataError) as caught:
            read(f)
        assert caught.value.code == "CTRAX_BAD_TIMESTAMPS"

    def test_irregular_timestamps_are_noted_not_hidden(self, tmp_path: Path) -> None:
        ts = np.arange(40) / 25.0
        ts[20:] += 0.5  # a dropped chunk of video: half a second gone
        s = read(raw(tmp_path / "a.mat", timestamps=ts))
        assert s.raw_attrs and "irregular" in s.raw_attrs["timestamps"]

    def test_regular_timestamps_leave_no_note(self, tmp_path: Path) -> None:
        assert read(raw(tmp_path / "a.mat")).raw_attrs is None

    def test_counts_that_disagree_with_the_detections_are_refused(self, tmp_path: Path) -> None:
        f = raw(tmp_path / "a.mat")
        m = sio.loadmat(f)
        m = {k: v for k, v in m.items() if not k.startswith("__")}
        m["ntargets"] = m["ntargets"] + 1.0
        sio.savemat(f, m)
        with pytest.raises(Track2DataError) as caught:
            read(f)
        assert caught.value.code == "CTRAX_INCONSISTENT"

    def test_two_detections_with_one_track_id_in_one_frame_are_refused(
        self, tmp_path: Path
    ) -> None:
        f = raw(tmp_path / "a.mat", frames=[[(0, 1.0, 1.0), (0, 2.0, 2.0)], [(0, 1.0, 1.0)]])
        with pytest.raises(Track2DataError) as caught:
            read(f)
        assert caught.value.code == "CTRAX_DUPLICATE_TRACK" and caught.value.remediation

    def test_too_many_fragments_for_the_memory_budget_asks_for_top_n(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import track2data.readers.ctrax_mat as module

        monkeypatch.setattr(module, "_MAX_BYTES", 1000)
        f = raw(tmp_path / "a.mat")
        with pytest.raises(Track2DataError) as caught:
            read(f)
        assert caught.value.code == "CTRAX_TOO_LARGE" and "top_n" in caught.value.remediation
        assert read(f, top_n=1).n_animals == 1  # and that is how to get past it

    def test_no_frames_is_a_coded_error(self, tmp_path: Path) -> None:
        f = raw(tmp_path / "a.mat", frames=[])
        with pytest.raises(Track2DataError) as caught:
            read(f)
        assert caught.value.code in {"READER_OUTPUT_INVALID", "CTRAX_BAD_TIMESTAMPS"}


class TestDamagedAndAmbiguousInput:
    def test_a_folder_with_two_files_asks_which(self, tmp_path: Path) -> None:
        raw(tmp_path / "a.mat")
        raw(tmp_path / "b.mat")
        with pytest.raises(Track2DataError) as caught:
            read(tmp_path)
        assert caught.value.code == "SESSION_AMBIGUOUS" and "a.mat" in caught.value.remediation

    def test_a_trx_mat_is_pointed_at_the_right_reader_not_misread(self, tmp_path: Path) -> None:
        sio.savemat(tmp_path / "trx.mat", {"trx": np.zeros((1, 1))})
        with pytest.raises(Track2DataError) as caught:
            CtraxMatReader().read(tmp_path / "trx.mat", options={**SIZE, "top_n": None})
        assert caught.value.code == "CTRAX_NOT_A_RAW_FILE" and "trx" in caught.value.remediation

    @pytest.mark.parametrize("how", ["empty", "truncated"])
    def test_a_damaged_file_is_a_coded_error(self, tmp_path: Path, how: str) -> None:
        f = raw(tmp_path / "a.mat")
        data = f.read_bytes()
        f.write_bytes(b"" if how == "empty" else data[: len(data) // 2])
        with pytest.raises(Track2DataError) as caught:
            CtraxMatReader().read(f, options={**SIZE, "top_n": None})
        assert caught.value.code != "UNKNOWN" and caught.value.remediation

    def test_no_such_path_is_a_coded_error(self, tmp_path: Path) -> None:
        with pytest.raises(Track2DataError) as caught:
            CtraxMatReader().read(tmp_path / "gone", options={**SIZE, "top_n": None})
        assert caught.value.code == "CTRAX_NO_FILE"


class TestThroughTheRestOfTheApp:
    def test_it_is_registered_and_listed(self) -> None:
        assert "ctrax_mat" in readers.reader_names()
        assert readers.find_reader("ctrax_mat") is CtraxMatReader

    def test_auto_detection_picks_it_for_a_folder_with_one_file(self, tmp_path: Path) -> None:
        raw(tmp_path / "a.mat")
        assert readers.detect_reader(tmp_path) is CtraxMatReader

    def test_idtracker_folders_are_not_claimed(self, tiny_real_session: Path) -> None:
        assert not CtraxMatReader.detect(tiny_real_session)

    def test_only_it_claims_a_ctrax_file(self, tmp_path: Path) -> None:
        raw(tmp_path / "a.mat")
        assert [c.name for c in readers._REGISTRY if c.detect(tmp_path)] == ["ctrax_mat"]

    def test_probe_reads_it_too(self, tmp_path: Path) -> None:
        s = readers.probe_session(raw(tmp_path / "a.mat"), reader="ctrax_mat", options=SIZE)
        assert s.n_animals == 2


def _rewritten(path: Path, **changes) -> Path:
    """The file with some variables replaced: a damaged or foreign file with plausible parts."""
    m = {k: v for k, v in sio.loadmat(path).items() if not k.startswith("__")}
    m.update(changes)
    sio.savemat(path, m)
    return path


class TestMoreWaysAFileCanDisagreeWithItself:
    def test_counts_that_are_not_whole_numbers_are_refused(self, tmp_path: Path) -> None:
        f = _rewritten(
            raw(tmp_path / "a.mat", frames=[[(0, 1.0, 1.0)], [(0, 2.0, 2.0)]]),
            ntargets=np.array([[1.5], [0.5]]),
        )
        with pytest.raises(Track2DataError) as caught:
            read(f)
        assert caught.value.code == "CTRAX_INCONSISTENT"

    def test_negative_counts_are_refused(self, tmp_path: Path) -> None:
        f = _rewritten(
            raw(tmp_path / "a.mat", frames=[[(0, 1.0, 1.0)], [(0, 2.0, 2.0)]]),
            ntargets=np.array([[-1.0], [3.0]]),  # the same total, which is all a sum would see
        )
        with pytest.raises(Track2DataError) as caught:
            read(f)
        assert caught.value.code == "CTRAX_INCONSISTENT"

    def test_timestamps_for_a_different_number_of_frames_are_refused(self, tmp_path: Path) -> None:
        f = raw(tmp_path / "a.mat", timestamps=np.arange(39) / 25.0)
        with pytest.raises(Track2DataError) as caught:
            read(f)
        assert caught.value.code == "CTRAX_INCONSISTENT"

    def test_per_detection_arrays_of_different_lengths_are_refused(self, tmp_path: Path) -> None:
        f = raw(tmp_path / "a.mat")
        y = sio.loadmat(f)["y_pos"][:-1]
        with pytest.raises(Track2DataError) as caught:
            read(_rewritten(f, y_pos=y))
        assert caught.value.code == "CTRAX_INCONSISTENT"

    def test_a_file_with_no_frames_says_so(self, tmp_path: Path) -> None:
        with pytest.raises(Track2DataError) as caught:
            read(raw(tmp_path / "a.mat", frames=[]))
        assert caught.value.code == "READER_OUTPUT_INVALID"

    def test_the_longest_tracks_are_kept_in_id_order_even_when_the_longest_has_the_highest_id(
        self, tmp_path: Path
    ) -> None:
        frames = [[(9, 1.0, 1.0), (1, 2.0, 2.0)] if f < 10 else [(9, 1.0, 1.0)] for f in range(20)]
        frames += [[(4, 5.0, 5.0)] for _ in range(3)]
        s = read(raw(tmp_path / "a.mat", frames=frames), top_n=2)
        assert s.identities_labels == ["1", "9"]  # lengths 9: 20, 1: 10, 4: 3
        assert s.raw_xy[0, 0].tolist() == [2.0, 2.0] and s.raw_xy[0, 1].tolist() == [1.0, 1.0]

"""The shared building blocks pose-style readers use: sentinels, one-keypoint reduction, validation.

DeepLabCut, SLEAP, Anipose and friends all give several keypoints per animal; Track2Data's metrics
use one position per animal. These tests pin how that one is chosen (never a centroid of whatever is
visible, which jitters), that the whole skeleton is kept beside it, and that a session built from
a reader's arrays is checked, because the Session model itself checks nothing.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from track2data.core.errors import DataValidationError
from track2data.core.models import KeypointData, KeypointSelection, Session
from track2data.readers.assemble import (
    SKELETON_MAX_BYTES,
    assemble_session,
    build_keypoints,
    reduce_keypoints,
    skeleton_fits,
    to_nan,
)

NAMES = ["snout", "ear", "tail"]


def pose(n_frames: int = 10, n_animals: int = 2) -> np.ndarray:
    """(F, A, K, 2): keypoint k of animal a sits at (10a + k, 100 + f) so each is identifiable."""
    xy = np.zeros((n_frames, n_animals, 3, 2))
    for a in range(n_animals):
        for k in range(3):
            xy[:, a, k, 0] = 10 * a + k
            xy[:, a, k, 1] = 100 + np.arange(n_frames)
    return xy


class TestSentinels:
    def test_infinity_becomes_missing_whatever_else_is_asked(self) -> None:
        out = to_nan(np.array([1.0, np.inf, -np.inf, 2.0]))
        assert np.isnan(out[1]) and np.isnan(out[2]) and out[0] == 1.0 and out[3] == 2.0

    def test_a_named_sentinel_becomes_missing_too(self) -> None:
        out = to_nan(np.array([0.0, 5.0, -1.0]), 0.0, -1.0)
        assert np.isnan(out[0]) and out[1] == 5.0 and np.isnan(out[2])

    def test_the_input_is_not_modified_and_the_result_is_float64(self) -> None:
        a = np.array([1, 2, 3], dtype=np.float32)
        out = to_nan(a, 2.0)
        assert a.tolist() == [1.0, 2.0, 3.0] and out.dtype == np.float64

    def test_an_integer_array_is_accepted(self) -> None:
        assert to_nan(np.array([1, 0, 3]), 0).tolist()[0] == 1.0


class TestReducingToOneKeypoint:
    def test_a_named_keypoint_is_used_as_is(self) -> None:
        r = reduce_keypoints(pose(), NAMES, keypoint="ear")
        assert r.selection.keypoint == "ear" and r.selection.chosen_by == "user"
        assert r.raw_xy.shape == (10, 2, 2)
        assert r.raw_xy[0, 0, 0] == 1.0 and r.raw_xy[0, 1, 0] == 11.0

    def test_with_no_choice_the_keypoint_seen_most_often_wins(self) -> None:
        xy = pose()
        xy[:6, :, 0, :] = np.nan  # snout visible in 4 of 10 frames
        xy[:2, :, 2, :] = np.nan  # tail in 8 of 10; ear in all 10
        r = reduce_keypoints(xy, NAMES)
        assert r.selection.keypoint == "ear" and r.selection.chosen_by == "coverage"
        assert r.selection.coverage == pytest.approx(1.0)

    def test_coverage_is_judged_after_the_likelihood_cutoff(self) -> None:
        xy = pose()
        conf = np.ones((10, 2, 3))
        conf[:5, :, 1] = 0.1  # ear is always *there* but unreliable half of the time
        r = reduce_keypoints(xy, NAMES, conf, cutoff=0.6)
        assert r.selection.keypoint != "ear"
        assert r.coverage["ear"] == pytest.approx(0.5)

    def test_a_tie_goes_to_the_more_confident_keypoint(self) -> None:
        conf = np.full((10, 2, 3), 0.7)
        conf[:, :, 2] = 0.95
        r = reduce_keypoints(pose(), NAMES, conf, cutoff=0.6)
        assert r.selection.keypoint == "tail"

    def test_a_full_tie_goes_to_the_first_keypoint(self) -> None:
        assert reduce_keypoints(pose(), NAMES).selection.keypoint == "snout"

    def test_positions_below_the_cutoff_are_missing_and_the_rest_are_kept(self) -> None:
        conf = np.ones((10, 2, 3))
        conf[3, 0, 0] = 0.2
        r = reduce_keypoints(pose(), NAMES, conf, keypoint="snout", cutoff=0.6)
        assert np.isnan(r.raw_xy[3, 0]).all()
        assert np.isfinite(r.raw_xy[3, 1]).all() and np.isfinite(r.raw_xy[4, 0]).all()
        assert r.selection.cutoff == 0.6

    def test_a_confidence_exactly_at_the_cutoff_is_kept(self) -> None:
        conf = np.full((10, 2, 3), 0.6)
        r = reduce_keypoints(pose(), NAMES, conf, keypoint="snout", cutoff=0.6)
        assert np.isfinite(r.raw_xy).all()

    def test_a_missing_confidence_counts_as_not_reliable(self) -> None:
        conf = np.ones((10, 2, 3))
        conf[2, 1, 0] = np.nan
        r = reduce_keypoints(pose(), NAMES, conf, keypoint="snout", cutoff=0.5)
        assert np.isnan(r.raw_xy[2, 1]).all()

    def test_no_cutoff_keeps_everything_that_has_a_position(self) -> None:
        conf = np.full((10, 2, 3), 0.01)
        r = reduce_keypoints(pose(), NAMES, conf, keypoint="snout", cutoff=None)
        assert np.isfinite(r.raw_xy).all() and r.selection.cutoff is None

    def test_a_cutoff_with_no_confidence_to_apply_it_to_is_recorded_as_none(self) -> None:
        r = reduce_keypoints(pose(), NAMES, None, keypoint="snout", cutoff=0.6)
        assert r.selection.cutoff is None and np.isfinite(r.raw_xy).all()

    def test_an_unknown_keypoint_is_refused_and_the_choices_are_listed(self) -> None:
        with pytest.raises(DataValidationError) as caught:
            reduce_keypoints(pose(), NAMES, keypoint="wing")
        err = caught.value
        assert err.code == "READER_OPTION_INVALID" and err.subject == "keypoint"
        assert "snout" in err.remediation and "tail" in err.remediation

    def test_nothing_survives_the_cutoff_is_a_clear_error(self) -> None:
        conf = np.full((10, 2, 3), 0.1)
        with pytest.raises(DataValidationError) as caught:
            reduce_keypoints(pose(), NAMES, conf, cutoff=0.6)
        assert caught.value.code == "POSE_NO_POSITIONS" and "cutoff" in caught.value.remediation

    def test_a_3d_array_uses_the_chosen_plane_and_keeps_z_out_of_the_result(self) -> None:
        xy = np.zeros((4, 1, 1, 3))
        xy[..., 0], xy[..., 1], xy[..., 2] = 1.0, 2.0, 3.0
        r = reduce_keypoints(xy, ["a"], plane=(0, 2))
        assert r.raw_xy[0, 0].tolist() == [1.0, 3.0]
        assert r.selection.plane == ("x", "z")
        assert reduce_keypoints(xy, ["a"]).selection.plane == ("x", "y")

    def test_the_result_is_float64_and_the_source_is_untouched(self) -> None:
        xy = pose().astype(np.float32)
        before = xy.copy()
        r = reduce_keypoints(xy, NAMES)
        assert r.raw_xy.dtype == np.float64 and np.array_equal(xy, before)

    def test_infinity_in_the_source_is_not_a_position(self) -> None:
        xy = pose()
        xy[0, 0, 0, :] = np.inf
        r = reduce_keypoints(xy, NAMES, keypoint="snout")
        assert np.isnan(r.raw_xy[0, 0]).all()

    def test_the_names_must_match_the_array(self) -> None:
        with pytest.raises(ValueError, match="names"):
            reduce_keypoints(pose(), ["only", "two"])


class TestKeepingTheSkeleton:
    def sel(self) -> KeypointSelection:
        return KeypointSelection(
            keypoint="snout", cutoff=None, chosen_by="user", coverage=1.0, plane=("x", "y")
        )

    def test_it_is_stored_as_float32_with_the_names_and_edges(self) -> None:
        conf = np.ones((10, 2, 3))
        kp = build_keypoints(pose(), NAMES, conf, [(0, 1), (1, 2)], self.sel())
        assert isinstance(kp, KeypointData)
        assert kp.xy.dtype == np.float32 and kp.xy.shape == (10, 2, 3, 2)
        assert kp.confidence is not None and kp.confidence.dtype == np.float32
        assert kp.names == NAMES and kp.edges == [(0, 1), (1, 2)]

    def test_infinity_is_not_stored(self) -> None:
        xy = pose()
        xy[0, 0, 0, 0] = np.inf
        kp = build_keypoints(xy, NAMES, None, [], self.sel())
        assert kp is not None and np.isnan(kp.xy[0, 0, 0, 0])

    def test_it_can_be_declined(self) -> None:
        assert build_keypoints(pose(), NAMES, None, [], self.sel(), keep=False) is None

    def test_an_edge_that_names_no_keypoint_is_refused(self) -> None:
        with pytest.raises(ValueError, match="edge"):
            build_keypoints(pose(), NAMES, None, [(0, 7)], self.sel())

    def test_a_confidence_of_the_wrong_shape_is_refused(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            build_keypoints(pose(), NAMES, np.ones((3, 3, 3)), [], self.sel())

    def test_a_huge_skeleton_is_not_silently_kept(self) -> None:
        assert skeleton_fits(pose())
        too_big = np.broadcast_to(np.float32(0), (SKELETON_MAX_BYTES // 4 + 1,))
        assert not skeleton_fits(too_big.reshape(1, 1, 1, -1))


class TestAssemblingASession:
    def build(self, **overrides) -> Session:
        xy = overrides.pop("raw_xy", pose()[:, :, 0, :])
        args = dict(
            session_id="s1",
            folder=Path("somewhere"),
            reader="toy",
            fps=30.0,
            width_px=640,
            height_px=480,
            raw_xy=xy,
            has_stable_identities=True,
        )
        args.update(overrides)
        return assemble_session(**args)

    def test_it_builds_a_consistent_session(self) -> None:
        s = self.build()
        assert s.n_frames == 10 and s.n_animals == 2 and s.video.n_frames == 10
        assert (s.video.fps, s.video.width_px, s.video.height_px) == (30.0, 640, 480)
        assert s.raw_xy.dtype == np.float64 and s.trajectory_variant == "with_gaps"
        assert s.keypoints is None and s.id_probabilities is None

    def test_infinity_in_the_positions_becomes_missing(self) -> None:
        xy = pose()[:, :, 0, :].copy()
        xy[0, 0, 0] = np.inf
        assert np.isnan(self.build(raw_xy=xy).raw_xy[0, 0, 0])

    def test_the_keypoints_ride_along(self) -> None:
        sel = KeypointSelection(
            keypoint="snout", cutoff=None, chosen_by="user", coverage=1.0, plane=("x", "y")
        )
        kp = build_keypoints(pose(), NAMES, None, [], sel)
        assert self.build(keypoints=kp).keypoints is kp

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("fps", 0.0),
            ("fps", -5.0),
            ("fps", float("nan")),
            ("fps", float("inf")),
            ("width_px", 0),
            ("height_px", -1),
        ],
    )
    def test_a_video_fact_that_cannot_be_true_is_refused_by_name(self, field, value) -> None:
        with pytest.raises(DataValidationError) as caught:
            self.build(**{field: value})
        err = caught.value
        assert err.code == "READER_OUTPUT_INVALID" and err.subject == field and err.remediation

    def test_no_frames_is_refused(self) -> None:
        with pytest.raises(DataValidationError) as caught:
            self.build(raw_xy=np.zeros((0, 2, 2)))
        assert caught.value.code == "READER_OUTPUT_INVALID" and caught.value.subject == "raw_xy"

    def test_the_wrong_shape_is_refused(self) -> None:
        with pytest.raises(DataValidationError):
            self.build(raw_xy=np.zeros((10, 2)))
        with pytest.raises(DataValidationError):
            self.build(raw_xy=np.zeros((10, 2, 3)))

    def test_keypoints_that_disagree_with_the_positions_are_refused(self) -> None:
        sel = KeypointSelection(
            keypoint="snout", cutoff=None, chosen_by="user", coverage=1.0, plane=("x", "y")
        )
        kp = build_keypoints(pose(n_frames=9), NAMES, None, [], sel)
        with pytest.raises(DataValidationError) as caught:
            self.build(keypoints=kp)
        assert caught.value.subject == "keypoints"

    def test_identity_labels_must_name_every_animal(self) -> None:
        with pytest.raises(DataValidationError) as caught:
            self.build(identities_labels=["only-one"])
        assert caught.value.subject == "identities_labels"
        assert self.build(identities_labels=["a", "b"]).identities_labels == ["a", "b"]

    def test_tracking_intervals_must_add_up_to_the_frames(self) -> None:
        with pytest.raises(DataValidationError) as caught:
            self.build(tracking_intervals=[(0, 3)])
        assert caught.value.subject == "tracking_intervals"
        ok = self.build(tracking_intervals=[(100, 105), (200, 205)])
        assert ok.tracking_intervals == [(100, 105), (200, 205)]

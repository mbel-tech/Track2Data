"""core.timeline: which video frame each stored trajectory row is."""

from __future__ import annotations

import numpy as np
import pytest

from track2data.core.timeline import map_array_index_to_true_frame, timeline_problem


def _frames(intervals, n):
    frames, valid = map_array_index_to_true_frame(intervals, n)
    return list(frames), valid


def test_no_intervals_means_row_position_and_an_unverified_timeline() -> None:
    frames, valid = _frames(None, 4)
    assert frames == [0, 1, 2, 3] and valid is False


def test_a_single_interval_keeps_its_nonzero_start() -> None:
    frames, valid = _frames([(1000, 1004)], 4)
    assert frames == [1000, 1001, 1002, 1003] and valid is True


def test_disjoint_intervals_keep_the_real_gap() -> None:
    frames, valid = _frames([(0, 3), (1000, 1002)], 5)
    assert frames == [0, 1, 2, 1000, 1001] and valid is True


def test_adjacent_intervals_add_no_artificial_break() -> None:
    frames, valid = _frames([(0, 3), (3, 6)], 6)
    assert frames == [0, 1, 2, 3, 4, 5] and valid is True


def test_an_array_that_already_holds_the_whole_timeline_is_not_expanded_twice() -> None:
    # 12 rows spanning frames 100..111 although the intervals only list two pieces of it
    frames, valid = _frames([(100, 104), (108, 112)], 12)
    assert frames == list(range(100, 112)) and valid is True


@pytest.mark.parametrize(
    "intervals",
    [
        [(10, 5)],  # end before start
        [(5, 5)],  # empty
        [(-1, 4)],  # negative start
        [(0, 5), (3, 8)],  # overlap
        [(10, 14), (0, 4)],  # out of order
    ],
)
def test_malformed_intervals_are_unverified_and_say_why(intervals) -> None:
    frames, valid = map_array_index_to_true_frame(intervals, 8)
    assert valid is False
    assert list(frames) == list(range(8))  # documented fallback: row position
    assert timeline_problem(intervals, 8)


def test_intervals_that_do_not_add_up_are_unverified() -> None:
    _frames_unused, valid = map_array_index_to_true_frame([(0, 5)], 8)
    assert valid is False and "8" in timeline_problem([(0, 5)], 8)


def test_a_consistent_timeline_has_no_problem() -> None:
    assert timeline_problem([(0, 3), (1000, 1002)], 5) is None
    assert timeline_problem(None, 5) is None  # no metadata is not a malformed one


def test_the_result_is_an_int_array_of_the_right_length() -> None:
    frames, _ = map_array_index_to_true_frame([(7, 10)], 3)
    assert isinstance(frames, np.ndarray) and len(frames) == 3

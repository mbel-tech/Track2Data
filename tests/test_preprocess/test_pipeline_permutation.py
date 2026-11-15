"""
Review finding C20 (12 Nov 2026): after identity-switch correction only xy and z
were relabelled. The per-animal arrays read next to them -- the jump-replaced
mask, the raw positions behind ``was_interpolated`` and the tracker's identity
probabilities -- stayed on the tracker's labels, so from the switch onward they
described the other animal.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import track2data.preprocess.pipeline as pipeline
from track2data.core.models import PPStepResult, PreprocessConfig, Session, VideoInfo

N = 20
SWAP_AT = 8


def _session() -> Session:
    xy = np.zeros((N, 2, 2))
    xy[:, 0, 0] = np.arange(N, dtype=float)
    xy[:, 1, 0] = 100.0 + np.arange(N, dtype=float)
    xy[12, 0, :] = np.nan  # a short gap the gap fill closes: animal 0's column at frame 12
    id_prob = np.column_stack([np.full(N, 0.9), np.full(N, 0.4)])
    return Session(
        session_id="s",
        folder=Path("/tmp/s"),
        reader="test",
        video=VideoInfo(fps=25.0, n_frames=N, width_px=640, height_px=480),
        n_animals=2,
        trajectory_variant="with_gaps",
        has_stable_identities=True,
        raw_xy=xy,
        id_probabilities=id_prob,
    )


@pytest.fixture()
def swapped(monkeypatch: pytest.MonkeyPatch):
    """Identity-switch correction that swaps the two columns from SWAP_AT onward."""

    def fake_correct(xy, cfg, swap_boundaries=None):
        columns = np.tile(np.arange(2), (N, 1))
        columns[SWAP_AT:] = [1, 0]
        out = np.take_along_axis(xy, columns[:, :, None], axis=1)
        return out, PPStepResult(
            step_name="identity_switch",
            affected_frames=N - SWAP_AT,
            affected_per_individual=[N - SWAP_AT] * 2,
            permutation=columns,
        )

    monkeypatch.setattr(pipeline, "correct_switches", fake_correct)
    return pipeline.run(_session(), PreprocessConfig())


def test_was_interpolated_follows_the_relabelled_animal(swapped) -> None:
    flags = swapped.was_interpolated
    # the gap was in tracker column 0 at frame 12, which after the swap is identity 1
    assert flags[12, 1] and not flags[12, 0]


def test_identity_probabilities_follow_the_relabelled_animal(swapped) -> None:
    prob = swapped.id_probabilities_aligned
    assert prob is not None
    assert prob[SWAP_AT - 1].tolist() == [0.9, 0.4]
    assert prob[SWAP_AT].tolist() == [0.4, 0.9]


def test_jump_replaced_follows_the_relabelled_animal(monkeypatch, swapped) -> None:
    # Re-run with a jump in tracker column 0 at frame 15 forced through detect_jumps.
    real_detect = pipeline.detect_jumps

    def fake_detect(xy, cfg, velocity_threshold_px_frame=None):
        out, step = real_detect(xy, cfg, velocity_threshold_px_frame=velocity_threshold_px_frame)
        out = out.copy()
        out[15, 0, :] = out[15, 0, :] + 1.0
        return out, step

    monkeypatch.setattr(pipeline, "detect_jumps", fake_detect)
    psess = pipeline.run(_session(), PreprocessConfig())
    assert psess.jump_replaced is not None
    assert psess.jump_replaced[15, 1] and not psess.jump_replaced[15, 0]


def test_no_switch_leaves_the_arrays_as_they_were() -> None:
    psess = pipeline.run(_session(), PreprocessConfig())
    assert psess.raw_xy_rows is None and psess.id_probabilities_rows is None
    assert psess.was_interpolated[12, 0]

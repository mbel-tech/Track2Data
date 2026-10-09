"""Quality-grid inputs: telling deliberate identity-free tracking from unreliable identification,
and measuring crossings as a share of unique frames.

The identity cases run the real idtracker.ai normaliser and the real D-5, not a fabricated status
string, because the bug was exactly that the two cases look the same once folded into one flag.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest

from tests.test_readers.idtrackerai.test_normaliser import _minimal_payload
from track2data.core.models import Session, VideoInfo
from track2data.metrics.diagnostic import CrossingRate, IdentityStability
from track2data.readers.idtrackerai.normaliser import Normaliser
from ui.store.quality_grid import assess_session


def _session(tmp_path: Path, *, fraction: float | None, declared: bool | None) -> Session:
    payload = _minimal_payload(tmp_path)
    if fraction is None:
        del payload["fraction_identified"]
    else:
        payload["fraction_identified"] = fraction
    meta = {} if declared is None else {"track_wo_identities": declared}
    return Normaliser(tmp_path).normalise(payload, session_meta=meta)


def _grid(session: Session, **cfg: Any):
    """What the Preview grid sees: real D-5 plus clean everything else."""
    d5 = IdentityStability().compute(session, cfg or None)
    diagnostics = {
        "D-1": pd.DataFrame({"coverage_fraction": [1.0, 1.0]}),
        "D-5": d5,
        "D-8": pd.DataFrame({"crossing_unique_frame_fraction": [0.0]}),
        "D-10": pd.DataFrame({"teleport_jump_count": [0, 0]}),
        "D-11": pd.DataFrame({"frac_interpolated": [0.0, 0.0]}),
    }
    return d5, assess_session(
        SimpleNamespace(session_id="s", diagnostics=diagnostics, error=None)
    )


class TestIdentityVerdict:
    def test_ten_percent_identification_is_not_an_unqualified_good(self, tmp_path: Path) -> None:
        session = _session(tmp_path, fraction=0.1, declared=False)
        d5, q = _grid(session)
        assert d5["identity_stability_status"].iloc[0] == "identity_free"  # contract unchanged
        assert d5["identity_free_reason"].iloc[0] == "low_identification"
        assert d5["identified_fraction"].iloc[0] == pytest.approx(0.1)
        assert q.verdict != "Good"
        assert q.identity.level in ("check", "review")
        assert any("10.0 %" in r and "identif" in r.lower() for r in q.reasons)

    def test_deliberate_identity_free_tracking_is_still_not_applicable(
        self, tmp_path: Path
    ) -> None:
        session = _session(tmp_path, fraction=0.1, declared=True)
        d5, q = _grid(session)
        assert d5["identity_free_reason"].iloc[0] == "declared"
        assert q.identity.level == "na"
        assert q.verdict == "Good" and q.reasons == []

    def test_stable_identification_stays_good(self, tmp_path: Path) -> None:
        d5, q = _grid(_session(tmp_path, fraction=0.85, declared=False))
        assert d5["identity_stability_status"].iloc[0] == "stable"
        assert q.identity.level == "good" and q.verdict == "Good"

    def test_low_identification_with_no_declaration_shows_uncertainty(
        self, tmp_path: Path
    ) -> None:
        """The file never said whether identities were switched off on purpose."""
        d5, q = _grid(_session(tmp_path, fraction=0.1, declared=None))
        assert d5["identity_free_reason"].iloc[0] == "unknown"
        assert q.identity.level == "check" and "Unknown" in q.identity.text
        assert q.verdict == "Check"

    def test_the_users_identity_free_override_counts_as_deliberate(self, tmp_path: Path) -> None:
        session = _session(tmp_path, fraction=0.1, declared=False)
        d5, q = _grid(session, identity_free_declared=True)
        assert d5["identity_free_reason"].iloc[0] == "declared"
        assert q.identity.level == "na"

    def test_the_override_cannot_launder_a_stable_session(self, tmp_path: Path) -> None:
        session = _session(tmp_path, fraction=0.85, declared=False)
        d5, _ = _grid(session, identity_free_declared=True)
        assert d5["identity_stability_status"].iloc[0] == "stable"
        assert d5["identity_free_reason"].iloc[0] == ""

    def test_a_reader_without_identification_quality_is_not_penalised(self) -> None:
        session = Session(
            session_id="dlc",
            folder=Path("/tmp/x"),
            reader="deeplabcut",
            video=VideoInfo(fps=25.0, n_frames=5, width_px=10, height_px=10),
            n_animals=2,
            trajectory_variant="with_gaps",
            has_stable_identities=False,
            raw_xy=np.zeros((5, 2, 2)),
        )
        d5, q = _grid(session)
        assert d5["identity_free_reason"].iloc[0] == "not_applicable"
        assert q.identity.level == "na" and q.verdict == "Good"

    def test_old_frames_without_the_new_columns_keep_the_old_reading(self) -> None:
        diagnostics = {"D-5": pd.DataFrame({"identity_stability_status": ["identity_free"]})}
        q = assess_session(SimpleNamespace(session_id="s", diagnostics=diagnostics, error=None))
        assert q.identity.level == "na"


def _fragment(start: int, end: int, individual: bool) -> dict[str, Any]:
    return {"start_frame": start, "end_frame": end, "is_an_individual": individual}


def _fragment_session(fragments: list[dict[str, Any]] | None, n_frames: int = 100) -> Session:
    return Session(
        session_id="f",
        folder=Path("/tmp/f"),
        reader="idtrackerai",
        video=VideoInfo(fps=25.0, n_frames=n_frames, width_px=10, height_px=10),
        n_animals=5,
        trajectory_variant="with_gaps",
        has_stable_identities=True,
        raw_xy=np.zeros((n_frames, 5, 2)),
        fragments=None if fragments is None else {"fragments": fragments},
    )


class TestCrossingShare:
    def test_the_bug_report_case_counts_ten_unique_frames(self) -> None:
        """One crossing over [0, 10) plus concurrent individuals: 10 of 100 frames, while the
        fragment-duration share is 10 / 490."""
        fragments = [_fragment(0, 10, False)]
        fragments += [_fragment(0, 10, True)] * 3
        fragments += [_fragment(10, 100, True)] * 5
        row = CrossingRate().compute(_fragment_session(fragments)).iloc[0]
        assert row["crossing_unique_frame_fraction"] == pytest.approx(0.10)
        assert row["crossing_frame_fraction"] == pytest.approx(10 / 490)  # D-8's contract

    def test_overlapping_crossings_count_once(self) -> None:
        fragments = [_fragment(0, 10, False), _fragment(5, 15, False), _fragment(5, 10, False)]
        row = CrossingRate().compute(_fragment_session(fragments)).iloc[0]
        assert row["crossing_unique_frame_fraction"] == pytest.approx(0.15)

    def test_no_crossings_is_a_measured_zero(self) -> None:
        row = CrossingRate().compute(_fragment_session([_fragment(0, 100, True)])).iloc[0]
        assert row["crossing_unique_frame_fraction"] == 0.0

    def test_unavailable_fragment_data_is_nan(self) -> None:
        row = CrossingRate().compute(_fragment_session(None)).iloc[0]
        assert np.isnan(row["crossing_unique_frame_fraction"])
        assert np.isnan(row["crossing_frame_fraction"])

    def test_a_zero_length_session_is_nan_not_a_division_error(self) -> None:
        row = CrossingRate().compute(_fragment_session([_fragment(0, 0, False)], n_frames=0))
        assert np.isnan(row["crossing_unique_frame_fraction"].iloc[0])

    def test_a_crossing_running_past_the_end_is_clipped_to_the_tracked_frames(self) -> None:
        row = CrossingRate().compute(_fragment_session([_fragment(90, 500, False)])).iloc[0]
        assert row["crossing_unique_frame_fraction"] == pytest.approx(0.10)


class TestTheGridUsesTheUniqueFrameShare:
    def _grid_for(self, share: float, fragment_share: float):
        diagnostics = {
            "D-8": pd.DataFrame(
                {
                    "crossing_unique_frame_fraction": [share],
                    "crossing_frame_fraction": [fragment_share],
                }
            ),
        }
        return assess_session(SimpleNamespace(session_id="s", diagnostics=diagnostics, error=None))

    def test_it_judges_and_words_the_unique_share(self) -> None:
        q = self._grid_for(share=0.10, fragment_share=0.0204)
        assert q.crossings.level == "review"  # 10 % of frames, whatever the group size
        assert q.crossings.text == "10.0 %"
        assert any("10.0 % of frames" in r for r in q.reasons)

    def test_it_falls_back_to_the_old_column_but_words_it_as_fragment_time(self) -> None:
        diagnostics = {"D-8": pd.DataFrame({"crossing_frame_fraction": [0.10]})}
        q = assess_session(SimpleNamespace(session_id="s", diagnostics=diagnostics, error=None))
        assert q.crossings.level == "review"
        assert any("fragment" in r and "of frames" not in r for r in q.reasons)

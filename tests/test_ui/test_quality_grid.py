"""Traffic-light verdicts for the Preview diagnostics grid (pure, no Qt)."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from ui.store.quality_grid import assess_session, count_verdicts


def _result(coverage=0.99, status="stable", crossing=0.0, jumps=0, interp=0.0, error=None):
    diagnostics = {
        "D-1": pd.DataFrame({"coverage_fraction": [coverage, 1.0]}),
        "D-5": pd.DataFrame({"identity_stability_status": [status]}),
        "D-8": pd.DataFrame({"crossing_frame_fraction": [crossing]}),
        "D-10": pd.DataFrame({"teleport_jump_count": [jumps, 0]}),
        "D-11": pd.DataFrame({"frac_interpolated": [interp, 0.0]}),
    }
    return SimpleNamespace(session_id="s1", diagnostics=diagnostics, error=error)


def test_clean_session_is_good_with_no_reasons() -> None:
    q = assess_session(_result())
    assert q.verdict == "Good"
    assert q.reasons == []
    assert q.coverage.text == "99.0 %"


def test_verdict_is_the_worst_cell() -> None:
    q = assess_session(_result(coverage=0.90, interp=0.19))
    assert q.coverage.level == "check"
    assert q.interpolated.level == "review"
    assert q.verdict == "Review"
    assert any("19.0 % of positions are interpolated" in r for r in q.reasons)


def test_weak_identities_ask_for_a_check() -> None:
    q = assess_session(_result(status="weak"))
    assert q.identity.level == "check"
    assert q.verdict == "Check"


def test_identity_free_session_is_not_penalised() -> None:
    q = assess_session(_result(status="identity_free"))
    assert q.identity.level == "na"
    assert q.verdict == "Good"


def test_jump_count_thresholds() -> None:
    assert assess_session(_result(jumps=2)).jumps.level == "good"
    assert assess_session(_result(jumps=7)).jumps.level == "check"
    assert assess_session(_result(jumps=11)).jumps.level == "review"


def test_missing_diagnostics_are_not_applicable_not_errors() -> None:
    q = assess_session(SimpleNamespace(session_id="s2", diagnostics={}, error=None))
    assert q.verdict == "Good"
    assert q.coverage.text == "—"


def test_failed_run_is_review_with_the_error() -> None:
    q = assess_session(_result(error="boom"))
    assert q.verdict == "Review"
    assert "boom" in q.reasons[0]


def test_count_verdicts_skips_excluded_sessions() -> None:
    good = assess_session(_result())
    bad = assess_session(_result(coverage=0.5))
    bad.session_id = "s2"
    assert count_verdicts([good, bad], set()) == {"Good": 1, "Check": 0, "Review": 1}
    assert count_verdicts([good, bad], {"s2"}) == {"Good": 1, "Check": 0, "Review": 0}

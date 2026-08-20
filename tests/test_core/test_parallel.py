"""Tests for the worker-count policy and map_sessions parallel-execution helper."""

from __future__ import annotations

import pytest

from track2data.core.parallel import map_sessions, worker_count


def _double(x: int) -> int:
    """Module-level (picklable) helper.

    ProcessPoolExecutor's Windows 'spawn' start method re-imports this module
    in each worker process and looks up the callable by qualified name, so it
    must be a real top-level function rather than a lambda or closure.
    """
    return x * 2


# ── worker_count ─────────────────────────────────────────────────────────────

class TestWorkerCount:
    def test_high_cpu_count_is_capped_at_eight(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("track2data.core.parallel.os.cpu_count", lambda: 16)
        assert worker_count() == 8

    def test_low_cpu_count_is_not_inflated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("track2data.core.parallel.os.cpu_count", lambda: 4)
        assert worker_count() == 3

    def test_user_setting_below_cap_is_honoured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("track2data.core.parallel.os.cpu_count", lambda: 16)
        assert worker_count(user_setting=3) == 3

    def test_user_setting_above_cap_is_still_capped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("track2data.core.parallel.os.cpu_count", lambda: 5)
        assert worker_count(user_setting=100) == 4

    def test_floor_of_one_holds_with_single_cpu(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("track2data.core.parallel.os.cpu_count", lambda: 1)
        assert worker_count() == 1

    def test_floor_of_one_holds_when_cpu_count_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("track2data.core.parallel.os.cpu_count", lambda: None)
        assert worker_count() == 1

    def test_floor_of_one_holds_with_low_user_setting(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("track2data.core.parallel.os.cpu_count", lambda: 16)
        assert worker_count(user_setting=0) == 1


# ── map_sessions ─────────────────────────────────────────────────────────────

class TestMapSessions:
    def test_default_n_workers_applies_sequentially_in_order(self) -> None:
        result = map_sessions(lambda x: x * 2, [1, 2, 3, 4, 5])
        assert result == [2, 4, 6, 8, 10]

    def test_explicit_n_workers_one_applies_sequentially_in_order(self) -> None:
        result = map_sessions(lambda x: x - 1, [10, 20, 30], n_workers=1)
        assert result == [9, 19, 29]

    def test_empty_items_returns_empty_list(self) -> None:
        assert map_sessions(lambda x: x * 2, []) == []

    def test_parallel_two_workers_returns_correct_values_in_order(self) -> None:
        result = map_sessions(_double, [1, 2, 3, 4], n_workers=2)
        assert result == [2, 4, 6, 8]

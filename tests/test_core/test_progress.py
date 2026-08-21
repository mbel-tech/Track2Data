"""Tests for track2data.core.progress -- the engine-side progress/cancellation
contract (issue #18). Must stay PySide6-free (D-001): the UI adapts
ProgressEvent/ProgressCallback to Qt signals on its own side, not the other
way around."""

from __future__ import annotations

import subprocess
import sys
import threading

import pytest

# ── ProgressEvent ────────────────────────────────────────────────────────────


def test_percent_normal_case() -> None:
    from track2data.core.progress import ProgressEvent

    event = ProgressEvent(stage="import", current=3, total=10)
    assert event.percent == 30


def test_percent_clamped_when_current_exceeds_total() -> None:
    from track2data.core.progress import ProgressEvent

    event = ProgressEvent(stage="import", current=15, total=10)
    assert event.percent == 100


def test_percent_clamped_when_current_negative() -> None:
    from track2data.core.progress import ProgressEvent

    event = ProgressEvent(stage="import", current=-5, total=10)
    assert event.percent == 0


def test_percent_zero_when_total_is_zero() -> None:
    """Must not raise ZeroDivisionError."""
    from track2data.core.progress import ProgressEvent

    event = ProgressEvent(stage="import", current=0, total=0)
    assert event.percent == 0


def test_percent_zero_when_total_is_negative() -> None:
    from track2data.core.progress import ProgressEvent

    event = ProgressEvent(stage="import", current=0, total=-1)
    assert event.percent == 0


def test_percent_100_when_current_equals_total() -> None:
    from track2data.core.progress import ProgressEvent

    event = ProgressEvent(stage="export", current=5, total=5)
    assert event.percent == 100


def test_default_session_id_and_message() -> None:
    from track2data.core.progress import ProgressEvent

    event = ProgressEvent(stage="run", current=0, total=1)
    assert event.session_id is None
    assert event.message == ""


def test_event_is_frozen() -> None:
    from track2data.core.progress import ProgressEvent

    event = ProgressEvent(stage="import", current=0, total=1)
    with pytest.raises(AttributeError):
        event.current = 5  # type: ignore[misc]


# ── CancellationToken ────────────────────────────────────────────────────────


def test_token_starts_not_cancelled() -> None:
    from track2data.core.progress import CancellationToken

    token = CancellationToken()
    assert token.is_cancelled is False


def test_token_cancel_sets_is_cancelled() -> None:
    from track2data.core.progress import CancellationToken

    token = CancellationToken()
    token.cancel()
    assert token.is_cancelled is True


def test_raise_if_cancelled_is_noop_when_not_cancelled() -> None:
    from track2data.core.progress import CancellationToken

    token = CancellationToken()
    token.raise_if_cancelled()  # must not raise


def test_raise_if_cancelled_raises_after_cancel() -> None:
    from track2data.core.progress import CancellationToken, OperationCancelled

    token = CancellationToken()
    token.cancel()
    with pytest.raises(OperationCancelled):
        token.raise_if_cancelled()


def test_token_wraps_a_real_threading_event() -> None:
    """Cancellation must be visible across threads -- confirm the underlying
    primitive is a real threading.Event, not a plain bool."""
    from track2data.core.progress import CancellationToken

    token = CancellationToken()
    result: dict[str, bool] = {}

    def worker() -> None:
        result["cancelled_before"] = token.is_cancelled
        token.cancel()

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert result["cancelled_before"] is False
    assert token.is_cancelled is True


# ── OperationCancelled ───────────────────────────────────────────────────────


def test_operation_cancelled_is_a_track2data_error() -> None:
    from track2data.core.errors import Track2DataError
    from track2data.core.progress import OperationCancelled

    exc = OperationCancelled()
    assert isinstance(exc, Track2DataError)
    assert exc.code == "CANCELLED"


# ── emit() ───────────────────────────────────────────────────────────────────


def test_emit_is_noop_with_none_callback() -> None:
    from track2data.core.progress import ProgressEvent, emit

    emit(None, ProgressEvent(stage="import", current=0, total=1))  # must not raise


def test_emit_calls_the_callback_with_the_event() -> None:
    from track2data.core.progress import ProgressEvent, emit

    received: list[object] = []
    event = ProgressEvent(stage="metrics", current=1, total=2, session_id="s1")
    emit(received.append, event)
    assert received == [event]


def test_emit_propagates_operation_cancelled() -> None:
    """emit() must never swallow a cancellation raised by the callback."""
    from track2data.core.progress import OperationCancelled, ProgressEvent, emit

    def cancelling_callback(_event: object) -> None:
        raise OperationCancelled()

    with pytest.raises(OperationCancelled):
        emit(cancelling_callback, ProgressEvent(stage="import", current=0, total=1))


def test_emit_propagates_other_callback_exceptions_too() -> None:
    from track2data.core.progress import ProgressEvent, emit

    def broken_callback(_event: object) -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        emit(broken_callback, ProgressEvent(stage="import", current=0, total=1))


# ── D-001 enforcement ────────────────────────────────────────────────────────


def test_importing_progress_module_does_not_pull_in_pyside6() -> None:
    """
    Must run in a fresh subprocess: within this pytest process, other test
    files (e.g. test_app_smoke.py's TestUILayer) may already have imported
    PySide6 into the shared sys.modules cache, which would make an in-process
    "PySide6 not in sys.modules" check order-dependent and unreliable rather
    than an actual guard on this module's own import behaviour.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import track2data.core.progress; "
            "assert 'PySide6' not in sys.modules, 'progress.py pulled in PySide6'",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr

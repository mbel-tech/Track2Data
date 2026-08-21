"""
Tests for ui/store/task_runner.py (issue #20) -- QThreadPool-based
background execution of Engine calls, off the GUI thread.

Uses pytest-qt's qtbot to pump the Qt event loop while waiting for
cross-thread signal emissions, since QThreadPool workers run
asynchronously and Qt's queued connections only deliver when the event
loop is actually running.

Every test uses the `runner` fixture below rather than constructing a
TaskRunner directly: its teardown calls shutdown(), which cancels and
waits for every in-flight task before the test function returns. Without
this, a background pool thread can still be mid-run when a test returns
and its local objects (the TaskRunner, its _WorkerSignals) start getting
garbage collected -- a real, reproduced-once Windows access-violation
crash (a pool thread emitting a Qt signal into an object mid-destruction).
"""

from __future__ import annotations

import time

import pytest

pytest.importorskip("PySide6")


@pytest.fixture
def runner(qtbot):
    from ui.store.task_runner import TaskRunner

    r = TaskRunner()
    yield r
    r.shutdown(3000)


# ── submit(): plain callables, no progress ──────────────────────────────────


def test_submit_happy_path_emits_started_then_finished(qtbot, runner) -> None:
    started_ids: list[str] = []
    runner.taskStarted.connect(started_ids.append)

    with qtbot.waitSignal(runner.taskFinished, timeout=2000) as blocker:
        task_id = runner.submit(lambda: 42)

    finished_id, result = blocker.args
    assert finished_id == task_id
    assert result == 42
    assert started_ids == [task_id]


def test_submit_runs_off_the_gui_thread(qtbot, runner) -> None:
    import threading

    seen_thread: list[int] = []

    def record_thread() -> str:
        seen_thread.append(threading.get_ident())
        return "done"

    with qtbot.waitSignal(runner.taskFinished, timeout=2000):
        runner.submit(record_thread)

    assert seen_thread[0] != threading.get_ident()


# ── submit_with_progress(): callables taking progress= ──────────────────────


def test_submit_with_progress_forwards_events(qtbot, runner) -> None:
    from track2data.core.progress import ProgressEvent

    events: list[ProgressEvent] = []
    percents: list[int] = []
    runner.taskEvent.connect(lambda _tid, event: events.append(event))
    runner.taskProgress.connect(lambda _tid, pct: percents.append(pct))

    def do_work(progress) -> str:
        progress(ProgressEvent(stage="run", current=0, total=2, message="start"))
        progress(ProgressEvent(stage="run", current=2, total=2, message="done"))
        return "ok"

    with qtbot.waitSignal(runner.taskFinished, timeout=2000):
        runner.submit_with_progress(do_work)

    assert [e.message for e in events] == ["start", "done"]
    assert percents == [0, 100]


def test_submit_without_progress_does_not_receive_progress_kwarg(qtbot, runner) -> None:
    """submit() (not submit_with_progress()) must call fn() with no
    arguments -- a callable that requires `progress` would TypeError,
    proving the two entry points genuinely differ rather than one
    silently detecting the other's shape."""

    def needs_progress(progress) -> str:
        return "unreachable"

    with qtbot.waitSignal(runner.taskFailed, timeout=2000) as blocker:
        runner.submit(needs_progress)

    _task_id, message, _tb = blocker.args
    assert "progress" in message


# ── failure handling ─────────────────────────────────────────────────────────


def test_failing_task_emits_failed_not_finished(qtbot, runner) -> None:
    finished_calls: list[object] = []
    runner.taskFinished.connect(lambda *a: finished_calls.append(a))

    def boom() -> None:
        raise RuntimeError("simulated failure")

    with qtbot.waitSignal(runner.taskFailed, timeout=2000) as blocker:
        task_id = runner.submit(boom)

    failed_id, message, tb = blocker.args
    assert failed_id == task_id
    assert "simulated failure" in message
    assert "RuntimeError" in tb
    assert "boom" in tb  # traceback.format_exc() -- the function name appears


def test_failing_track2data_error_message_carries_code_subject_remediation(
    qtbot, runner
) -> None:
    """
    _EngineTask.run() only ever emits str(exc) + a plain traceback -- the
    original exception object (and its code/subject/remediation
    attributes) never crosses the thread boundary as structured data.
    That turns out not to matter: Track2DataError.__str__() already
    formats all three into the string itself (see core/errors.py), so
    str(exc) alone -- no changes needed here -- carries everything a
    failure dialog (#22) needs to show, just as one pre-formatted string
    rather than separate fields.
    """
    from track2data.core.errors import Track2DataError

    def boom() -> None:
        raise Track2DataError(
            "Session folder missing",
            code="NO_READER",
            subject="session_042",
            remediation="Check the folder path and try again.",
        )

    with qtbot.waitSignal(runner.taskFailed, timeout=2000) as blocker:
        runner.submit(boom)

    _task_id, message, tb = blocker.args
    assert "NO_READER" in message
    assert "Session folder missing" in message
    assert "session_042" in message
    assert "Check the folder path and try again." in message
    assert "Track2DataError" in tb  # the real traceback is still present too


# ── cancellation ─────────────────────────────────────────────────────────────


def test_cancel_stops_a_running_task(qtbot, runner) -> None:
    from track2data.core.progress import ProgressEvent

    finished_calls: list[object] = []
    runner.taskFinished.connect(lambda *a: finished_calls.append(a))

    def slow_work(progress) -> str:
        for i in range(20):
            progress(ProgressEvent(stage="run", current=i, total=20))
            time.sleep(0.05)
        return "should not get here"

    with qtbot.waitSignal(runner.taskCancelled, timeout=3000) as blocker:
        task_id = runner.submit_with_progress(slow_work)
        qtbot.wait(120)  # let a couple of progress ticks happen first
        runner.cancel(task_id)

    assert blocker.args == [task_id]
    assert finished_calls == []


def test_cancel_all_cancels_every_in_flight_task(qtbot, runner) -> None:
    from track2data.core.progress import ProgressEvent

    # max_threads=1 on the private pool (serialised execution), so submit
    # two tasks and cancel_all() while the first is still running -- the
    # second is still queued and must also end up cancelled, not run to
    # completion once the first is torn down. Waits for BOTH tasks to
    # reach a terminal state (not just "at least one") before returning.
    cancelled_ids: list[str] = []
    runner.taskCancelled.connect(cancelled_ids.append)

    def slow_work(progress) -> str:
        for i in range(20):
            progress(ProgressEvent(stage="run", current=i, total=20))
            time.sleep(0.05)
        return "should not get here"

    id1 = runner.submit_with_progress(slow_work)
    id2 = runner.submit_with_progress(slow_work)
    qtbot.wait(120)
    runner.cancel_all()

    qtbot.waitUntil(lambda: len(cancelled_ids) >= 2, timeout=3000)
    assert id1 in cancelled_ids
    assert id2 in cancelled_ids


# ── serialisation (private, single-thread pool) ─────────────────────────────


def test_pool_runs_tasks_serially_not_concurrently(qtbot, runner) -> None:
    """The private QThreadPool has max_threads=1 specifically so two
    concurrent triggers can't race on the same output directory."""
    order: list[str] = []

    def make_task(label: str):
        def _run() -> str:
            order.append(f"{label}-start")
            time.sleep(0.05)
            order.append(f"{label}-end")
            return label
        return _run

    finished_ids: list[str] = []
    runner.taskFinished.connect(lambda tid, _result: finished_ids.append(tid))

    runner.submit(make_task("a"))
    runner.submit(make_task("b"))

    qtbot.waitUntil(lambda: len(finished_ids) == 2, timeout=3000)

    assert order == ["a-start", "a-end", "b-start", "b-end"]


# ── shutdown ─────────────────────────────────────────────────────────────────


def test_shutdown_waits_for_pool_to_drain(qtbot, runner) -> None:
    with qtbot.waitSignal(runner.taskFinished, timeout=2000):
        runner.submit(lambda: "quick")

    drained = runner.shutdown(2000)
    assert drained is True


def test_shutdown_cancels_in_flight_tasks_first(qtbot, runner) -> None:
    from track2data.core.progress import ProgressEvent

    def slow_work(progress) -> str:
        for i in range(40):
            progress(ProgressEvent(stage="run", current=i, total=40))
            time.sleep(0.05)
        return "should not get here"

    runner.submit_with_progress(slow_work)
    qtbot.wait(120)

    drained = runner.shutdown(3000)
    assert drained is True  # cancellation lets it exit well within the timeout

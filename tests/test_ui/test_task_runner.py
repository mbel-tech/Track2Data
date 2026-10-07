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


def test_cancel_check_reaches_the_callable_and_cancels(qtbot) -> None:
    """GUI-05: a callable that polls cancel_check (not progress) is stoppable."""
    import threading

    from ui.store.task_runner import TaskRunner

    runner = TaskRunner()
    started = threading.Event()

    def work(progress=None, cancel_check=None):
        started.set()
        for _ in range(200):
            cancel_check()
            threading.Event().wait(0.02)
        return "finished"

    with qtbot.waitSignal(runner.taskCancelled, timeout=5000):
        runner.submit_with_progress(work, cancel_check=True)
        assert started.wait(2)
        runner.cancel_all()


# ── lanes: probes get their own pool (PERF-03) ──────────────────────────────


def test_probe_lane_runs_while_the_run_lane_is_busy(qtbot, runner) -> None:
    import threading

    release = threading.Event()
    runner.submit(lambda: release.wait(5) or "run-done")  # occupies the run lane

    with qtbot.waitSignal(runner.probeFinished, timeout=2000) as blocker:
        probe_id = runner.submit(lambda: "probe-done", lane="probe")
    assert blocker.args == [probe_id, "probe-done"]
    assert not release.is_set()  # the run was still blocked when the probe finished
    release.set()


def test_run_lane_is_still_serial(qtbot, runner) -> None:
    import threading

    active, peak = [0], [0]
    lock = threading.Lock()

    def work() -> None:
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.05)
        with lock:
            active[0] -= 1

    ids = [runner.submit(work) for _ in range(3)]
    done: list[str] = []
    runner.taskFinished.connect(lambda tid, _r: done.append(tid))
    qtbot.waitUntil(lambda: len(done) == 3, timeout=3000)
    assert peak[0] == 1 and set(done) == set(ids)


def test_probe_lane_does_not_use_the_generic_task_signals(qtbot, runner) -> None:
    seen: list[str] = []
    for sig in (runner.taskStarted, runner.taskFinished, runner.taskFailed, runner.taskCancelled):
        sig.connect(lambda *a, _s=seen: _s.append("generic"))

    with qtbot.waitSignal(runner.probeFinished, timeout=2000):
        runner.submit(lambda: 1, lane="probe")
    with qtbot.waitSignal(runner.probeFailed, timeout=2000) as blocker:
        runner.submit(lambda: 1 / 0, lane="probe")
    assert "division by zero" in blocker.args[1]
    qtbot.wait(50)
    assert seen == []  # MainWindow listens to these; probes must not trigger it


def test_cancel_all_for_the_run_lane_leaves_probes_alone(qtbot, runner) -> None:
    import threading

    gate = threading.Event()
    probe_id = runner.submit(lambda: (gate.wait(5), "probe-ok")[1], lane="probe")
    run_id = runner.submit(lambda: "x")
    runner.cancel_all(lane="run")
    assert probe_id in runner._tokens and not runner._tokens[probe_id].is_cancelled
    assert run_id not in runner._tokens or runner._tokens[run_id].is_cancelled
    with qtbot.waitSignal(runner.probeFinished, timeout=3000) as blocker:
        gate.set()
    assert blocker.args == [probe_id, "probe-ok"]


def test_a_task_cancelled_before_it_starts_never_runs(qtbot, runner) -> None:
    import threading

    gate = threading.Event()
    ran: list[int] = []
    runner.submit(lambda: gate.wait(5), lane="probe")  # blocks the probe thread
    queued = runner.submit(lambda: ran.append(1), lane="probe")
    runner.cancel(queued)
    with qtbot.waitSignal(runner.probeCancelled, timeout=3000) as blocker:
        gate.set()
    assert blocker.args == [queued] and ran == []


def test_shutdown_uses_one_deadline_for_both_lanes(qtbot, runner) -> None:
    import threading

    gate = threading.Event()
    runner.submit(lambda: gate.wait(10), lane="probe")
    runner.submit(lambda: gate.wait(10))
    start = time.monotonic()
    assert runner.shutdown(300) is False  # neither task polls its token
    assert time.monotonic() - start < 0.9  # not 2 x the timeout
    gate.set()
    assert runner.shutdown(3000) is True


def test_unknown_lane_is_rejected(runner) -> None:
    with pytest.raises(ValueError):
        runner.submit(lambda: 1, lane="nope")

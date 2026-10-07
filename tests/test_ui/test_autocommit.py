from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


def test_trigger_commits_once_after_the_delay(qtbot) -> None:
    from ui.widgets.autocommit import AutoCommit

    calls: list[int] = []
    ac = AutoCommit(lambda: calls.append(1), delay_ms=20)
    ac.trigger()
    ac.trigger()
    assert calls == []
    qtbot.waitUntil(lambda: calls == [1], timeout=1000)
    qtbot.wait(60)
    assert calls == [1]


def test_flush_commits_pending_edit_immediately(qtbot) -> None:
    from ui.widgets.autocommit import AutoCommit

    calls: list[int] = []
    ac = AutoCommit(lambda: calls.append(1), delay_ms=5000)
    ac.trigger()
    assert ac.pending
    ac.flush()
    assert calls == [1]
    assert not ac.pending
    ac.flush()  # nothing pending -> no second commit
    assert calls == [1]


def test_suppressed_ignores_triggers(qtbot) -> None:
    from ui.widgets.autocommit import AutoCommit

    calls: list[int] = []
    ac = AutoCommit(lambda: calls.append(1), delay_ms=5000)
    with ac.suppressed():
        ac.trigger()
    assert not ac.pending
    ac.flush()
    assert calls == []

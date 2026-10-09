"""Command palette: pure filtering, then the dialog's keys."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from ui.dialogs.command_palette import Command, CommandPalette, filter_commands


def _commands(log: list[str]) -> list[Command]:
    return [
        Command("Go to", "Sessions", lambda: log.append("sessions")),
        Command("Go to", "Metrics", lambda: log.append("metrics")),
        Command("Run", "Run pipeline", lambda: log.append("run"), "Ctrl+R"),
        Command("Run", "Export…", lambda: log.append("export"), "Ctrl+E", enabled=False),
        Command("View", "Switch theme", lambda: log.append("theme")),
    ]


def test_empty_query_lists_every_enabled_command_in_order() -> None:
    labels = [c.label for c in filter_commands(_commands([]), "")]
    assert labels == ["Sessions", "Metrics", "Run pipeline", "Switch theme"]


def test_disabled_commands_never_appear() -> None:
    assert filter_commands(_commands([]), "export") == []


def test_every_word_must_match_kind_or_label() -> None:
    assert [c.label for c in filter_commands(_commands([]), "go met")] == ["Metrics"]
    assert [c.label for c in filter_commands(_commands([]), "pipeline run")] == ["Run pipeline"]


def test_a_label_that_starts_with_the_query_ranks_first() -> None:
    commands = [
        Command("View", "Show the run log", lambda: None),
        Command("Run", "Run pipeline", lambda: None),
    ]
    ranked = [c.label for c in filter_commands(commands, "run")]
    assert ranked == ["Run pipeline", "Show the run log"]


def test_enter_runs_the_highlighted_command_and_closes(qtbot) -> None:
    log: list[str] = []
    palette = CommandPalette(_commands(log))
    qtbot.addWidget(palette)
    palette.set_query("theme")
    assert palette.shown_labels() == ["Switch theme"]
    palette.run_current()
    assert log == ["theme"]
    assert palette.result() == palette.DialogCode.Accepted


def test_arrow_keys_move_the_highlight_and_wrap(qtbot) -> None:
    log: list[str] = []
    palette = CommandPalette(_commands(log))
    qtbot.addWidget(palette)
    palette.step(1)
    palette.run_current()
    assert log == ["metrics"]

    log.clear()
    again = CommandPalette(_commands(log))
    qtbot.addWidget(again)
    again.step(-1)  # wraps to the last entry
    again.run_current()
    assert log == ["theme"]


def test_main_window_palette_offers_every_stage_and_disables_run_without_a_project(qtbot) -> None:
    from app.main_window import MainWindow
    from app.navigation import STAGES

    win = MainWindow()
    qtbot.addWidget(win)
    commands = win.palette_commands()
    go_to = [c.label for c in commands if c.kind == "Go to"]
    assert go_to == [label for label, _ in STAGES]
    run = next(c for c in commands if c.label == "Run pipeline")
    assert run.enabled is False
    win.close()

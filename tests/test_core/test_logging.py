"""Tests for core logging utilities including RunLogWriter (TDD)."""

from __future__ import annotations

from track2data.core.logging import RunLogWriter, get_logger


class TestGetLogger:
    def test_returns_logger(self) -> None:
        import logging

        logger = get_logger("test.module")
        assert isinstance(logger, logging.Logger)

    def test_logger_name(self) -> None:
        logger = get_logger("my.logger")
        assert logger.name == "my.logger"


class TestRunLogWriter:
    def test_initial_render_empty(self) -> None:
        writer = RunLogWriter()
        assert writer.render() == ""

    def test_log_single_line(self) -> None:
        writer = RunLogWriter()
        writer.log("Hello world")
        assert writer.render() == "Hello world"

    def test_log_multiple_lines(self) -> None:
        writer = RunLogWriter()
        writer.log("line 1")
        writer.log("line 2")
        assert writer.render() == "line 1\nline 2"

    def test_header_adds_h2(self) -> None:
        writer = RunLogWriter()
        writer.header("My Title")
        assert writer.render() == "## My Title"

    def test_bullet_adds_dash(self) -> None:
        writer = RunLogWriter()
        writer.bullet("some item")
        assert writer.render() == "- some item"

    def test_mixed_content(self) -> None:
        writer = RunLogWriter()
        writer.header("Results")
        writer.bullet("item 1")
        writer.bullet("item 2")
        writer.log("done")
        rendered = writer.render()
        assert rendered == "## Results\n- item 1\n- item 2\ndone"

    def test_clear_empties_lines(self) -> None:
        writer = RunLogWriter()
        writer.log("something")
        writer.clear()
        assert writer.render() == ""

    def test_clear_then_log(self) -> None:
        writer = RunLogWriter()
        writer.log("old content")
        writer.clear()
        writer.log("new content")
        assert writer.render() == "new content"

    def test_log_accepts_markdown(self) -> None:
        writer = RunLogWriter()
        writer.log("**bold** and _italic_")
        assert "**bold**" in writer.render()

    def test_render_returns_string(self) -> None:
        writer = RunLogWriter()
        assert isinstance(writer.render(), str)

    def test_multiple_headers(self) -> None:
        writer = RunLogWriter()
        writer.header("Section 1")
        writer.header("Section 2")
        rendered = writer.render()
        assert "## Section 1" in rendered
        assert "## Section 2" in rendered

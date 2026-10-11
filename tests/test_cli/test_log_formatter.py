"""The CLI's log rewrite: a public Formatter subclass, also on handlers installed before it."""

from __future__ import annotations

import io
import logging

from click.testing import CliRunner

from track2data.cli import _ReasonFormatter, cli
from track2data.metrics.availability import NEEDS_WATER_COLUMN_REASON, reason_for_cli


def _record(message: str) -> logging.LogRecord:
    return logging.LogRecord("t", logging.WARNING, __file__, 1, message, None, None)


def test_cli_formatter_is_a_formatter_subclass_and_rewrites_the_reason() -> None:
    inner = logging.Formatter("%(levelname)s|%(message)s")
    wrapped = _ReasonFormatter(inner)
    assert isinstance(wrapped, logging.Formatter)
    out = wrapped.format(_record(f"Skipping IL-15: {NEEDS_WATER_COLUMN_REASON}"))
    assert out.startswith("WARNING|Skipping IL-15: ")  # the original format is preserved
    rewritten = reason_for_cli(NEEDS_WATER_COLUMN_REASON)
    assert out == inner.format(_record(f"Skipping IL-15: {rewritten}"))
    assert "Calibration page" not in out
    plain = wrapped.format(_record("nothing to rewrite"))
    assert plain == "WARNING|nothing to rewrite"


def test_cli_rewrites_on_preinstalled_handlers() -> None:
    import click

    @cli.command("probe-log-format")
    def probe() -> None:
        for h in logging.getLogger().handlers:
            if h is handler:
                click.echo(h.format(_record(NEEDS_WATER_COLUMN_REASON)))
                click.echo("wrapped" if isinstance(h.formatter, _ReasonFormatter) else "plain")
                inner = getattr(h.formatter, "_inner", None)
                click.echo("nested" if isinstance(inner, _ReasonFormatter) else "flat")

    root = logging.getLogger()
    handler = logging.StreamHandler(io.StringIO())
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    root.addHandler(handler)
    try:
        result = CliRunner().invoke(cli, ["probe-log-format"])
        assert result.exit_code == 0, result.output
        first = result.output.splitlines()[0]
        assert first.startswith("WARNING ") and "Calibration page" not in first
        assert "calibration.water_column" in first
        assert result.output.splitlines()[1:] == ["wrapped", "flat"]
    finally:
        root.removeHandler(handler)
        cli.commands.pop("probe-log-format", None)


def test_a_cli_call_leaves_the_root_formatters_as_they_were() -> None:
    root = logging.getLogger()
    handler = logging.StreamHandler(io.StringIO())
    original = logging.Formatter("%(message)s")
    handler.setFormatter(original)
    root.addHandler(handler)
    before = {h: h.formatter for h in root.handlers}
    try:
        assert CliRunner().invoke(cli, ["list-readers"]).exit_code == 0
        assert {h: h.formatter for h in root.handlers if h in before} == before
        assert handler.formatter is original
    finally:
        root.removeHandler(handler)


def test_a_later_test_still_sees_the_neutral_reason_in_caplog(caplog) -> None:
    logging.getLogger("t").warning(NEEDS_WATER_COLUMN_REASON)
    assert NEEDS_WATER_COLUMN_REASON in caplog.text

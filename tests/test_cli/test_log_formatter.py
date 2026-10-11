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
    root = logging.getLogger()
    handler = logging.StreamHandler(io.StringIO())
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    root.addHandler(handler)
    try:
        result = CliRunner().invoke(cli, ["list-readers"])
        assert result.exit_code == 0, result.output
        out = handler.format(_record(NEEDS_WATER_COLUMN_REASON))
        assert out.startswith("WARNING ") and "Calibration page" not in out
        assert "calibration.water_column" in out
        again = CliRunner().invoke(cli, ["list-readers"])  # idempotent: no double wrapping
        assert again.exit_code == 0
        assert isinstance(handler.formatter, _ReasonFormatter)
        assert not isinstance(handler.formatter._inner, _ReasonFormatter)
    finally:
        root.removeHandler(handler)

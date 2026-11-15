"""The ``--self-check`` used by the release smoke test exports for real."""

from __future__ import annotations

import io

import pytest

from app import selfcheck


def test_self_check_passes_from_source() -> None:
    buf = io.StringIO()
    assert selfcheck.run_self_check(buf) == 0
    assert "self-check OK" in buf.getvalue()


def test_self_check_fails_when_an_exporter_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import track2data.exporters as exporters

    real = exporters.get_exporter
    monkeypatch.setattr(
        exporters, "get_exporter", lambda n: None if n == "excel" else real(n)
    )
    buf = io.StringIO()
    assert selfcheck.run_self_check(buf) == 1
    assert "excel: not registered" in buf.getvalue()


def test_main_dispatches_self_check(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.main as main_mod

    monkeypatch.setattr(main_mod.sys, "argv", ["Track2Data", "--self-check"])
    monkeypatch.setattr(selfcheck, "run_self_check", lambda out=None: 7)
    with pytest.raises(SystemExit) as exc:
        main_mod.main()
    assert exc.value.code == 7

"""Verify track2data.readers entry points are registered and loadable."""

from __future__ import annotations

import importlib.metadata


def _reader_names() -> set[str]:
    return {ep.name for ep in importlib.metadata.entry_points(group="track2data.readers")}


def test_unified_reader_registered() -> None:
    assert "idtrackerai" in _reader_names(), (
        f"Unified 'idtrackerai' entry point missing; registered: {_reader_names()}"
    )


def test_legacy_readers_registered() -> None:
    names = _reader_names()
    assert "idtrackerai_v5" in names, f"idtrackerai_v5 missing; registered: {names}"


def test_v4_reader_not_advertised_as_entry_point() -> None:
    """
    idtrackerai_v4's detect() unconditionally returns False (see its module
    docstring: "not yet implemented" -- no v4 sample data exists to validate
    against), so it can never actually be selected as a reader. Advertising
    it as a live entry point would mislead anyone enumerating
    track2data.readers expecting a working reader. See DECISIONS.md D-012.
    It's still registered as a built-in directly in readers/__init__.py, just
    not as a discoverable entry point.
    """
    assert "idtrackerai_v4" not in _reader_names()


def test_unified_reader_loadable() -> None:
    eps = importlib.metadata.entry_points(group="track2data.readers")
    unified = next(ep for ep in eps if ep.name == "idtrackerai")
    cls = unified.load()
    assert hasattr(cls, "name"), "IDTrackerAiReader must have a 'name' class attribute"
    assert hasattr(cls, "priority"), "IDTrackerAiReader must have a 'priority' class attribute"
    assert cls.priority >= 20, f"Unified reader priority must be ≥ 20; got {cls.priority}"


def test_legacy_reader_loadable() -> None:
    eps = {ep.name: ep for ep in importlib.metadata.entry_points(group="track2data.readers")}
    cls = eps["idtrackerai_v5"].load()
    assert hasattr(cls, "priority"), "idtrackerai_v5 missing 'priority' attribute"

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


def test_v4_reader_is_gone_entirely() -> None:
    """
    IDTrackerAiV4Reader was a stub whose detect() always returned False and
    whose read() raised NotImplementedError, so it could never be selected
    and could only ever fail if it were. D-012 had already removed its entry
    point; the class stayed registered as a built-in, where it did nothing
    but violate the reader contract. A class that raises on use is worse
    than an absent one -- the decision record keeps the history.
    """
    assert "idtrackerai_v4" not in _reader_names()

    import track2data.readers as readers

    assert not hasattr(readers, "IDTrackerAiV4Reader")
    assert "idtrackerai_v4" not in {r.name for r in readers._REGISTRY}


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

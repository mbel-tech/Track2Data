"""Local-only: scanning the real 70-session idtracker.ai corpus finds exactly its sessions.

Like the other corpus tests this skips in CI and whenever the corpus is absent. It is the check
that folder-of-folders import works on real data and not just on the synthetic fixtures: the
corpus root holds 70 ``session_*`` folders, each with about 87 files, and one scan of it must
yield one high-confidence idtracker.ai group of 70 sessions, quickly.

Run it (set ``T2D_CORPUS_DIR`` when the corpus lives in another checkout)::

    pytest tests/test_corpus/test_real_scan.py -m corpus_local
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from track2data.readers.detection import Confidence
from track2data.readers.scan import scan

pytestmark = [pytest.mark.corpus_local]

CORPUS_DIR = Path(
    os.environ.get("T2D_CORPUS_DIR")
    or Path(__file__).parent.parent.parent / "Checked sessions GOT"
)


def _sessions() -> list[Path]:
    if not CORPUS_DIR.is_dir():
        return []
    return sorted(p for p in CORPUS_DIR.glob("session_*") if p.is_dir())


pytestmark.append(
    pytest.mark.skipif(not _sessions(), reason=f"Real corpus not present at {CORPUS_DIR}")
)


def test_the_corpus_root_is_one_high_confidence_group_of_every_session() -> None:
    expected = [p.name for p in _sessions()]
    started = time.monotonic()
    result = scan([CORPUS_DIR])
    elapsed = time.monotonic() - started

    assert len(result.groups) == 1, [g.best.reader for g in result.groups]
    best = result.groups[0].best
    assert best.reader == "idtrackerai"
    assert best.confidence is Confidence.HIGH
    assert [s.session_id for s in best.sessions] == expected
    assert not result.truncated
    assert elapsed < 2.0, f"scan took {elapsed:.2f}s for {result.entries} entries"


def test_a_single_real_session_is_found_when_picked_directly() -> None:
    folder = _sessions()[0]
    result = scan([folder])
    assert [s.source for s in result.groups[0].best.sessions] == [folder]

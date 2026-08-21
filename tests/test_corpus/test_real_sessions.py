"""Local-only regression tests against the real 70-session idtracker.ai corpus.

These tests are skipped automatically in CI and whenever the corpus
directory is absent (the data are the user's own tracked sessions and are
not stored in the repository).

The corpus is the authoritative check for this reader: fixtures can (and
did) drift into a fictional contract that the reader passed against while
failing on every real session -- see docs/IDTRACKERAI_FORMAT_ANALYSIS.md.
Whenever a fixture and the corpus disagree, the corpus wins.

To run locally once the corpus is present at the repo root:

    pytest tests/test_corpus/ -v -m corpus_local
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.corpus_local]

CORPUS_DIR = Path(__file__).parent.parent.parent / "Checked sessions GOT"


def _corpus_sessions() -> list[Path]:
    if not CORPUS_DIR.is_dir():
        return []
    return sorted(p for p in CORPUS_DIR.glob("session_*") if p.is_dir())


pytestmark.append(
    pytest.mark.skipif(
        not _corpus_sessions(),
        reason=f"Real corpus not present at {CORPUS_DIR}",
    )
)


class TestAllSessionsImport:
    """The non-negotiable criterion from the format-alignment plan:
    read_session() must succeed on every real session, not just fixtures."""

    def test_every_session_imports(self) -> None:
        from track2data.readers import read_session

        sessions = _corpus_sessions()
        assert sessions, "corpus fixture guard should have skipped otherwise"

        failures: list[tuple[str, Exception]] = []
        for folder in sessions:
            try:
                read_session(folder)
            except Exception as exc:  # noqa: BLE001 -- collecting all failures deliberately
                failures.append((folder.name, exc))

        if failures:
            detail = "\n".join(f"  {name}: {exc!r}" for name, exc in failures[:10])
            pytest.fail(
                f"{len(failures)}/{len(sessions)} real sessions failed to import:\n{detail}"
            )

    def test_no_session_gets_fabricated_25fps(self) -> None:
        """Real corpus fps values sit in [24.833, 24.880]; a 25.0 fallback
        firing anywhere means frames_per_second silently defaulted instead
        of being read from the trajectory dict or session.json."""
        from track2data.readers import read_session

        offenders = []
        for folder in _corpus_sessions():
            s = read_session(folder)
            if s.video.fps == 25.0:
                offenders.append(folder.name)

        assert not offenders, f"fps fabricated to 25.0 for: {offenders}"

    def test_trajectory_format_used_is_h5(self) -> None:
        """All 70 real sessions ship trajectories.h5 as their default,
        highest-priority format; the reader should actually use it now
        that the h5 loader exists, not silently fall back to npy."""
        from track2data.readers import read_session

        sessions = _corpus_sessions()
        formats_used = {read_session(f).trajectory_format for f in sessions}
        assert formats_used == {"h5"}

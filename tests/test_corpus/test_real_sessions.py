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
            except Exception as exc:
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


class TestLogDigestOnRealCorpus:
    """The old idtrackerai.log parser matched neither the real timestamp
    format nor the real terminal-status line, so every session -- healthy
    or crashed -- reported status "Unknown". session_trial15_Segment1 is a
    genuine crash in the corpus (OSError: Too many open files); this test
    pins that it is now distinguishable from a healthy run."""

    def test_no_session_reports_unknown_status(self) -> None:
        from track2data.readers.idtrackerai.log import load_log_digest

        offenders = []
        for folder in _corpus_sessions():
            digest = load_log_digest(folder)
            if digest is not None and digest["status"] == "Unknown":
                offenders.append(folder.name)
        assert not offenders, f"log status still 'Unknown' for: {offenders}"

    def test_known_crashed_session_reports_failed(self) -> None:
        from track2data.readers.idtrackerai.log import load_log_digest

        folder = CORPUS_DIR / "session_trial15_Segment1"
        if not folder.is_dir():
            pytest.skip("session_trial15_Segment1 not present in corpus")
        digest = load_log_digest(folder)
        assert digest["status"] == "Failed"
        assert "OSError" in digest["failure_summary"]


class TestPipelineDoesNotCorruptRealData:
    """Regression coverage for the pipeline-corruption bugs found on the
    real corpus: jump_detect erasing gap_fill's NaN policy, and
    identity_switch injecting large artificial displacements. Pinned to
    session_trial10_Segment1's exact measured numbers so a future change
    reintroducing either bug fails loudly instead of silently."""

    SESSION = "session_trial10_Segment1"

    def _raw_xy(self):
        import numpy as np

        from track2data.readers.idtrackerai.formats.npy import load_npy

        folder = CORPUS_DIR / self.SESSION
        if not folder.is_dir():
            pytest.skip(f"{self.SESSION} not present in corpus")
        payload = load_npy(folder / "trajectories" / "trajectories.npy")
        return np.asarray(payload["trajectories"], dtype=np.float64)

    def test_jump_detect_preserves_gap_fill_policy(self) -> None:
        import numpy as np

        from track2data.core.models import PreprocessConfig
        from track2data.preprocess.gap_fill import fill_gaps
        from track2data.preprocess.jump_detect import detect_jumps

        xy = self._raw_xy()
        cfg = PreprocessConfig()
        after_gap_fill, _ = fill_gaps(xy.copy(), cfg.gap_fill)
        n_nan_after_gap_fill = int(np.isnan(after_gap_fill[:, :, 0]).sum())

        after_jump_detect, _ = detect_jumps(after_gap_fill, cfg.jump)
        n_nan_after_jump_detect = int(np.isnan(after_jump_detect[:, :, 0]).sum())

        assert n_nan_after_gap_fill == 9767
        assert n_nan_after_jump_detect == n_nan_after_gap_fill, (
            "jump_detect changed the NaN count left by gap_fill -- it must "
            "only touch frames it flags as jumps, never pre-existing gaps"
        )

    def test_identity_switch_disabled_by_default_does_not_alter_pipeline_output(self) -> None:
        """With the fragment-unaware corrector default-disabled, running the
        full pipeline must not inject the ~640px teleports and +5234% path
        length inflation measured on this session when it ran unconditionally."""
        import numpy as np

        from track2data.core.models import PreprocessConfig, Session, VideoInfo
        from track2data.preprocess.pipeline import run

        xy = self._raw_xy()
        session = Session(
            session_id=self.SESSION,
            folder=CORPUS_DIR / self.SESSION,
            reader="idtrackerai",
            video=VideoInfo(fps=24.851666666666667, n_frames=xy.shape[0],
                             width_px=1920, height_px=1080),
            n_animals=xy.shape[1],
            trajectory_variant="with_gaps",
            has_stable_identities=True,
            raw_xy=xy,
        )
        cfg = PreprocessConfig()
        assert cfg.identity_switch.enabled is False, (
            "identity_switch must default to disabled until it is "
            "fragment-boundary-aware -- see plan Fase 1.5b / 6d"
        )
        psess = run(session, cfg)

        max_disp = np.nanmax(
            np.linalg.norm(np.diff(psess.xy, axis=0), axis=2), axis=0
        )
        # Pre-fix, animal 0/1 max displacement jumped to ~642/~628 px after
        # identity_switch ran unconditionally. With it disabled, the pipeline's
        # own jump_detect + smoothing bound displacement far below that.
        assert np.all(max_disp < 200.0), f"unexpectedly large displacement: {max_disp}"


class TestRoiListZonesOnRealCorpus:
    """roi_list used to be stored unparsed with zero consumers -- a user
    would redraw by hand an arena idtracker.ai already had. Verification
    criterion #5 from the format-alignment plan: the net area must be
    smaller than the sum of additive polygons, since ~85% of real
    roi_list entries are subtractive exclusion holes."""

    SESSION = "session_trial10_Segment1"

    def test_net_arena_area_smaller_than_additive_sum(self) -> None:
        from shapely.geometry import Polygon

        from track2data.readers import read_session
        from track2data.zones.io import zone_set_from_roi_list

        folder = CORPUS_DIR / self.SESSION
        if not folder.is_dir():
            pytest.skip(f"{self.SESSION} not present in corpus")

        s = read_session(folder)
        assert s.roi_list, "expected a non-empty roi_list on a real session"
        zs = zone_set_from_roi_list(
            s.roi_list, width_px=s.video.width_px, height_px=s.video.height_px
        )

        def _area(vertices):
            poly = Polygon(vertices)
            return poly.buffer(0).area if not poly.is_valid else poly.area

        additive = sum(_area(r.vertices) for r in zs.rois if r.sign == "+")
        subtractive = sum(_area(r.vertices) for r in zs.rois if r.sign == "-")
        assert subtractive > 0, "expected at least one subtractive ROI in this session"
        assert additive - subtractive < additive

    def test_all_sessions_roi_list_parses_and_seeds_a_zone_set(self) -> None:
        from track2data.readers import read_session
        from track2data.zones.io import zone_set_from_roi_list

        for folder in _corpus_sessions():
            s = read_session(folder)
            if not s.roi_list:
                continue
            zs = zone_set_from_roi_list(
                s.roi_list, width_px=s.video.width_px, height_px=s.video.height_px
            )
            assert len(zs.rois) > 0
            assert all(r.sign in ("+", "-") for r in zs.rois)


class TestFragmentsOnRealCorpus:
    """preprocessing/list_of_fragments.json had zero consumers -- the
    entire fragment layer (identity-swap boundaries, per-fragment
    certainty, crossing detection) was unused. Pinned to
    session_trial10_Segment1's exact measured numbers."""

    SESSION = "session_trial10_Segment1"

    def test_fragment_counts_match_measured_values(self) -> None:
        from track2data.readers import read_session
        from track2data.readers.idtrackerai.fragments import (
            fragment_swap_boundaries,
            individual_fragments,
        )

        folder = CORPUS_DIR / self.SESSION
        if not folder.is_dir():
            pytest.skip(f"{self.SESSION} not present in corpus")

        s = read_session(folder)
        assert s.fragments is not None
        assert len(s.fragments["fragments"]) == 1152
        assert len(individual_fragments(s.fragments)) == 761

        boundaries = fragment_swap_boundaries(s.fragments)
        # 4.1% of 14911 frames are where a swap is even possible; a huge
        # reduction from the 94.9% of frames the old geometric-only
        # identity_switch pass used to reason about.
        assert len(boundaries) < 0.05 * s.n_frames

    def test_all_sessions_fragments_parse_without_error(self) -> None:
        from track2data.readers import read_session
        from track2data.readers.idtrackerai.fragments import (
            fragment_swap_boundaries,
            individual_fragments,
        )

        for folder in _corpus_sessions():
            s = read_session(folder)
            assert s.fragments is not None, f"no fragments parsed for {folder.name}"
            individual_fragments(s.fragments)  # must not raise
            fragment_swap_boundaries(s.fragments)  # must not raise

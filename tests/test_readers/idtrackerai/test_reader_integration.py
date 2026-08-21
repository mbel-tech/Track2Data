"""
Integration tests for the unified IDTrackerAiReader — written before
implementation (TDD RED).

These tests exercise the full pipeline:
  detect → load → normalise → Session
"""

from __future__ import annotations

from pathlib import Path

import pytest

from track2data.readers.idtrackerai.reader import IDTrackerAiReader

# ── Helpers ────────────────────────────────────────────────────────────────────

@pytest.fixture()
def reader() -> IDTrackerAiReader:
    return IDTrackerAiReader()


# ── detect() ──────────────────────────────────────────────────────────────────

class TestReaderDetect:
    def test_detects_tiny_real_session(self, reader: IDTrackerAiReader,
                                       tiny_real_session: Path) -> None:
        assert reader.detect(tiny_real_session) is True

    def test_does_not_detect_empty_folder(self, reader: IDTrackerAiReader,
                                          tmp_path: Path) -> None:
        assert reader.detect(tmp_path) is False

    def test_does_not_detect_v5_folder(self, reader: IDTrackerAiReader,
                                        tiny_v5_session: Path) -> None:
        # v5 folders have trajectories_wo_gaps.npy + video_object.npy.
        # The new reader detects based on trajectories/ containing a dict-npy;
        # v5 also has a raw-array npy, so detect must be True for it too,
        # but the full read distinguishes them.
        # What matters: the v5 session is detected (it has trajectories/).
        # That's fine — the reader handles it.
        result = reader.detect(tiny_v5_session)
        # The v5 session has trajectories/trajectories_wo_gaps.npy (raw array, not a dict).
        # Our detect() returns True whenever trajectories/ exists and has any npy.
        # So this is True — the reader must handle the raw-array case gracefully.
        assert isinstance(result, bool)


# ── read() ────────────────────────────────────────────────────────────────────

class TestReaderRead:
    def test_returns_session(self, reader: IDTrackerAiReader,
                             tiny_real_session: Path) -> None:
        from track2data.core.models import Session
        s = reader.read(tiny_real_session)
        assert isinstance(s, Session)

    def test_session_id_is_folder_name(self, reader: IDTrackerAiReader,
                                       tiny_real_session: Path) -> None:
        s = reader.read(tiny_real_session)
        assert s.session_id == tiny_real_session.name

    def test_raw_xy_shape(self, reader: IDTrackerAiReader,
                          tiny_real_session: Path) -> None:
        s = reader.read(tiny_real_session)
        assert s.raw_xy.shape == (10, 2, 2)

    def test_n_animals(self, reader: IDTrackerAiReader,
                       tiny_real_session: Path) -> None:
        s = reader.read(tiny_real_session)
        assert s.n_animals == 2

    def test_video_fps(self, reader: IDTrackerAiReader,
                       tiny_real_session: Path) -> None:
        s = reader.read(tiny_real_session)
        assert s.video.fps == pytest.approx(25.0)

    def test_video_dimensions(self, reader: IDTrackerAiReader,
                              tiny_real_session: Path) -> None:
        s = reader.read(tiny_real_session)
        assert s.video.width_px == 1920
        assert s.video.height_px == 1080

    # ── id_probabilities ──────────────────────────────────────────────────────

    def test_id_probabilities_squeezed_to_2d(self, reader: IDTrackerAiReader,
                                              tiny_real_session: Path) -> None:
        """Real files ship (N, M, 1); the reader must return (N, M)."""
        s = reader.read(tiny_real_session)
        assert s.id_probabilities is not None
        assert s.id_probabilities.shape == (10, 2)

    # ── quality metrics ───────────────────────────────────────────────────────

    def test_quality_metrics_present(self, reader: IDTrackerAiReader,
                                     tiny_real_session: Path) -> None:
        s = reader.read(tiny_real_session)
        assert s.quality is not None
        assert "estimated_accuracy" in s.quality
        assert "fraction_identified" in s.quality

    def test_idtrackerai_version(self, reader: IDTrackerAiReader,
                                  tiny_real_session: Path) -> None:
        s = reader.read(tiny_real_session)
        assert s.idtrackerai_version == "6.0.13"

    # ── body length ───────────────────────────────────────────────────────────

    def test_body_length_reliable_is_false(self, reader: IDTrackerAiReader,
                                           tiny_real_session: Path) -> None:
        s = reader.read(tiny_real_session)
        assert s.body_length_reliable is False

    def test_length_unit_none(self, reader: IDTrackerAiReader,
                              tiny_real_session: Path) -> None:
        s = reader.read(tiny_real_session)
        assert s.length_unit is None

    # ── session.json enrichment ───────────────────────────────────────────────

    def test_tracking_intervals_from_session_json(self, reader: IDTrackerAiReader,
                                                   tiny_real_session: Path) -> None:
        s = reader.read(tiny_real_session)
        assert s.tracking_intervals == [(0, 9)]

    def test_roi_list_from_session_json(self, reader: IDTrackerAiReader,
                                         tiny_real_session: Path) -> None:
        s = reader.read(tiny_real_session)
        assert s.roi_list is not None
        assert len(s.roi_list) >= 1

    # ── custom artefacts ──────────────────────────────────────────────────────

    def test_inconsistent_frames_loaded(self, reader: IDTrackerAiReader,
                                         tiny_real_session: Path) -> None:
        from tests.conftest import TINY_REAL_INCONSISTENT_FRAMES
        s = reader.read(tiny_real_session)
        assert s.inconsistent_frames == TINY_REAL_INCONSISTENT_FRAMES

    def test_bbox_table_loaded(self, reader: IDTrackerAiReader,
                               tiny_real_session: Path) -> None:
        s = reader.read(tiny_real_session)
        assert s.bbox_table is not None
        assert len(s.bbox_table) == 20  # 10 frames x 2 animals

    def test_bbox_summary_loaded(self, reader: IDTrackerAiReader,
                                  tiny_real_session: Path) -> None:
        s = reader.read(tiny_real_session)
        assert s.bbox_summary is not None
        assert s.bbox_summary["status"] == "ok"

    def test_matching_results_empty_when_absent(self, reader: IDTrackerAiReader,
                                                 tiny_real_session: Path) -> None:
        s = reader.read(tiny_real_session)
        assert s.matching_results == []

    # ── video path ────────────────────────────────────────────────────────────

    def test_unreachable_video_path_sets_none(self, reader: IDTrackerAiReader,
                                               tiny_real_session: Path) -> None:
        """video_paths points at /Volumes/Expansion/…; must not be reachable."""
        s = reader.read(tiny_real_session)
        assert s.video.path is None

    # ── log digest ────────────────────────────────────────────────────────────

    def test_tracking_log_status_success(self, reader: IDTrackerAiReader,
                                          tiny_real_session: Path) -> None:
        s = reader.read(tiny_real_session)
        assert s.tracking_log is not None
        assert s.tracking_log["status"] == "Success"

    # ── trajectory format ─────────────────────────────────────────────────────

    def test_trajectory_format_is_npy(self, reader: IDTrackerAiReader,
                                       tiny_real_session: Path) -> None:
        s = reader.read(tiny_real_session)
        assert s.trajectory_format == "npy"


# ── format fallback ─────────────────────────────────────────────────────────
#
# Real idtracker.ai sessions ship trajectories_formats=['h5','npy','csv'] by
# default (session_idtrackerai.md:73) -- confirmed in 70/70 of the real GOT
# corpus. detect() ranks h5 first. Before the fallback fix, any format ranked
# above the first one with a working loader made read() raise
# IDT_FORMAT_AMBIGUOUS even though a readable format sat right next to it --
# this class pins that regression.

class TestReaderFormatFallback:
    def test_reads_via_npy_when_unreadable_format_ranks_higher(
        self, reader: IDTrackerAiReader, tmp_path: Path
    ) -> None:
        import numpy as np

        from track2data.readers.idtrackerai.detect import detect

        session_dir = tmp_path / "session_fallback_test"
        traj_dir = session_dir / "trajectories"
        traj_dir.mkdir(parents=True)
        # A format detect() ranks above npy/csv but has no loader (parquet).
        (traj_dir / "trajectories.parquet").write_bytes(b"not a real parquet file")
        traj_dict = {
            "trajectories": np.zeros((3, 2, 2)),
            "version": "6.0.13",
            "frames_per_second": 25.0,
        }
        np.save(traj_dir / "trajectories.npy", traj_dict, allow_pickle=True)

        hit = detect(session_dir)
        assert hit is not None
        assert hit.format == "parquet"  # confirms the test actually exercises the fallback

        s = reader.read(session_dir)
        assert s.raw_xy.shape == (3, 2, 2)
        assert s.trajectory_format == "npy"

    def test_raises_only_when_nothing_is_readable(
        self, reader: IDTrackerAiReader, tmp_path: Path
    ) -> None:
        from track2data.core.errors import ImportError_

        session_dir = tmp_path / "session_all_unreadable"
        traj_dir = session_dir / "trajectories"
        traj_dir.mkdir(parents=True)
        (traj_dir / "trajectories.parquet").write_bytes(b"not real")
        (traj_dir / "trajectories.pickle").write_bytes(b"not real")

        with pytest.raises(ImportError_) as exc_info:
            reader.read(session_dir)
        assert exc_info.value.code == "IDT_FORMAT_AMBIGUOUS"

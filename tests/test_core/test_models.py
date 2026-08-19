"""Tests for core data models — written before any implementation (TDD RED)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from track2data.core.models import (
    ROI,
    CalibrationConfig,
    MetricSelection,
    PreprocessConfig,
    ProjectManifest,
    Session,
    VideoInfo,
    ZoneSet,
)

# ── VideoInfo ──────────────────────────────────────────────────────────────────

class TestVideoInfo:
    def test_fields_stored(self) -> None:
        v = VideoInfo(fps=25.0, n_frames=100, width_px=1920, height_px=1080)
        assert v.fps == 25.0
        assert v.n_frames == 100
        assert v.width_px == 1920
        assert v.height_px == 1080

    def test_path_optional(self) -> None:
        v = VideoInfo(fps=25.0, n_frames=100, width_px=1920, height_px=1080)
        assert v.path is None

    def test_path_stored_as_path(self, tmp_path: Path) -> None:
        v = VideoInfo(fps=25.0, n_frames=100, width_px=1920, height_px=1080,
                      path=tmp_path / "video.mp4")
        assert isinstance(v.path, Path)


# ── Session ────────────────────────────────────────────────────────────────────

class TestSession:
    @pytest.fixture()
    def sample_xy(self) -> np.ndarray:
        return np.zeros((100, 4, 2), dtype=np.float64)

    @pytest.fixture()
    def sample_video(self) -> VideoInfo:
        return VideoInfo(fps=25.0, n_frames=100, width_px=1920, height_px=1080)

    @pytest.fixture()
    def sample_session(self, sample_xy: np.ndarray, sample_video: VideoInfo,
                       tmp_path: Path) -> Session:
        return Session(
            session_id="test_session",
            folder=tmp_path,
            reader="idtrackerai_v5",
            video=sample_video,
            n_animals=4,
            trajectory_variant="wo_gaps",
            has_stable_identities=True,
            raw_xy=sample_xy,
        )

    def test_n_frames_property(self, sample_session: Session) -> None:
        assert sample_session.n_frames == 100

    def test_raw_xy_shape(self, sample_session: Session, sample_xy: np.ndarray) -> None:
        assert sample_session.raw_xy.shape == (100, 4, 2)

    def test_body_length_px_default_none(self, sample_session: Session) -> None:
        assert sample_session.body_length_px is None

    def test_body_length_px_stored(self, sample_xy: np.ndarray, sample_video: VideoInfo,
                                    tmp_path: Path) -> None:
        lengths = np.array([8.5, 9.0, 8.2, 9.5])
        s = Session(
            session_id="x", folder=tmp_path, reader="idtrackerai_v5",
            video=sample_video, n_animals=4, trajectory_variant="wo_gaps",
            has_stable_identities=True, raw_xy=sample_xy, body_length_px=lengths,
        )
        np.testing.assert_array_equal(s.body_length_px, lengths)

    def test_coverage_no_nans(self, sample_session: Session) -> None:
        cov = sample_session.coverage()
        assert cov.shape == (4,)
        np.testing.assert_array_equal(cov, np.ones(4))

    def test_coverage_with_nans(self, sample_video: VideoInfo, tmp_path: Path) -> None:
        xy = np.zeros((100, 4, 2), dtype=np.float64)
        xy[20:25, 0, :] = np.nan  # 5/100 NaN for animal 0
        s = Session(
            session_id="x", folder=tmp_path, reader="idtrackerai_v5",
            video=sample_video, n_animals=4, trajectory_variant="with_gaps",
            has_stable_identities=True, raw_xy=xy,
        )
        cov = s.coverage()
        assert cov[0] == pytest.approx(0.95)
        assert cov[1] == pytest.approx(1.0)


# ── Config models ──────────────────────────────────────────────────────────────

class TestPreprocessConfig:
    def test_defaults(self) -> None:
        cfg = PreprocessConfig()
        assert cfg.gap_fill.enabled is True
        assert cfg.gap_fill.max_gap_frames == 30
        assert cfg.jump.method == "sd_multiple"
        assert cfg.jump.sd_mult == 10.0
        assert cfg.identity_switch.tier1_ratio == 1.5
        assert cfg.identity_switch.tier2_hungarian is True
        assert cfg.smoothing.method == "savgol"
        assert cfg.smoothing.window == 5
        assert cfg.coverage.max_pct_na_per_individual == pytest.approx(0.10)

    def test_round_trip_json(self) -> None:
        cfg = PreprocessConfig()
        dumped = cfg.model_dump_json()
        restored = PreprocessConfig.model_validate_json(dumped)
        assert restored == cfg


class TestCalibrationConfig:
    def test_default_mode(self) -> None:
        assert CalibrationConfig().mode == "bodylength"

    def test_scalar_mode(self) -> None:
        c = CalibrationConfig(mode="scalar", px_per_cm=12.5)
        assert c.px_per_cm == 12.5


class TestZoneSet:
    def test_empty_default(self) -> None:
        zs = ZoneSet()
        assert zs.rois == []
        assert zs.orientation_tag is None

    def test_roi_vertices_stored(self) -> None:
        roi = ROI(name="flow", level="main",
                  vertices=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)])
        zs = ZoneSet(rois=[roi])
        assert len(zs.rois) == 1
        assert zs.rois[0].name == "flow"


class TestMetricSelection:
    def test_empty_defaults(self) -> None:
        m = MetricSelection()
        assert m.individual == []
        assert m.group == []
        assert m.zone == []
        assert m.timepoint_minutes is None

    def test_diagnostic_defaults_empty(self) -> None:
        m = MetricSelection()
        assert m.diagnostic == []

    def test_quality_threshold_defaults_zero(self) -> None:
        m = MetricSelection()
        assert m.quality_threshold == 0.0

    def test_diagnostic_stored(self) -> None:
        m = MetricSelection(diagnostic=["D-1", "D-2"])
        assert m.diagnostic == ["D-1", "D-2"]

    def test_quality_threshold_stored(self) -> None:
        m = MetricSelection(quality_threshold=0.5)
        assert m.quality_threshold == pytest.approx(0.5)

    def test_round_trip_json_with_new_fields(self) -> None:
        m = MetricSelection(
            individual=["IL-1"],
            group=["GL-3"],
            zone=["Z-1"],
            diagnostic=["D-1"],
            timepoint_minutes=20,
            quality_threshold=0.5,
        )
        restored = MetricSelection.model_validate_json(m.model_dump_json())
        assert restored == m


# ── ProjectManifest ────────────────────────────────────────────────────────────

class TestProjectManifest:
    @pytest.fixture()
    def minimal_manifest(self) -> ProjectManifest:
        now = datetime.now(tz=UTC)
        return ProjectManifest(
            project_name="test_project",
            created_at=now,
            updated_at=now,
        )

    def test_schema_version_default(self, minimal_manifest: ProjectManifest) -> None:
        assert minimal_manifest.schema_version == 1

    def test_app_version_present(self, minimal_manifest: ProjectManifest) -> None:
        assert minimal_manifest.app_version != ""

    def test_sessions_default_empty(self, minimal_manifest: ProjectManifest) -> None:
        assert minimal_manifest.sessions == []

    def test_project_hash_is_hex_string(self, minimal_manifest: ProjectManifest) -> None:
        h = minimal_manifest.project_hash()
        assert isinstance(h, str)
        assert len(h) == 16
        int(h, 16)  # must be valid hex

    def test_project_hash_stable(self, minimal_manifest: ProjectManifest) -> None:
        assert minimal_manifest.project_hash() == minimal_manifest.project_hash()

    def test_project_hash_changes_with_project_name(self) -> None:
        now = datetime.now(tz=UTC)
        m1 = ProjectManifest(project_name="alpha", created_at=now, updated_at=now)
        m2 = ProjectManifest(project_name="beta", created_at=now, updated_at=now)
        assert m1.project_hash() != m2.project_hash()

    def test_round_trip_json(self, minimal_manifest: ProjectManifest) -> None:
        dumped = minimal_manifest.model_dump_json()
        restored = ProjectManifest.model_validate_json(dumped)
        assert restored.project_name == minimal_manifest.project_name
        assert restored.schema_version == minimal_manifest.schema_version

    def test_serialises_to_valid_json(self, minimal_manifest: ProjectManifest) -> None:
        dumped = minimal_manifest.model_dump_json()
        parsed = json.loads(dumped)
        assert parsed["project_name"] == "test_project"


# ── Session extended fields (idtracker.ai reader) ──────────────────────────────

class TestSessionExtendedFields:
    """Tests for the optional fields added to Session to support the real idtracker.ai format."""

    @pytest.fixture()
    def base_session(self, tmp_path: Path) -> Session:
        return Session(
            session_id="test",
            folder=tmp_path,
            reader="idtrackerai",
            video=VideoInfo(fps=25.0, n_frames=10, width_px=1920, height_px=1080),
            n_animals=2,
            trajectory_variant="with_gaps",
            has_stable_identities=True,
            raw_xy=np.zeros((10, 2, 2), dtype=np.float64),
        )

    def test_body_length_reliable_defaults_false(self, base_session: Session) -> None:
        assert base_session.body_length_reliable is False

    def test_id_probabilities_defaults_none(self, base_session: Session) -> None:
        assert base_session.id_probabilities is None

    def test_quality_defaults_none(self, base_session: Session) -> None:
        assert base_session.quality is None

    def test_length_unit_defaults_none(self, base_session: Session) -> None:
        assert base_session.length_unit is None

    def test_identities_labels_defaults_none(self, base_session: Session) -> None:
        assert base_session.identities_labels is None

    def test_identities_groups_defaults_none(self, base_session: Session) -> None:
        assert base_session.identities_groups is None

    def test_setup_points_defaults_none(self, base_session: Session) -> None:
        assert base_session.setup_points is None

    def test_tracking_intervals_defaults_none(self, base_session: Session) -> None:
        assert base_session.tracking_intervals is None

    def test_roi_list_defaults_none(self, base_session: Session) -> None:
        assert base_session.roi_list is None

    def test_tracking_log_defaults_none(self, base_session: Session) -> None:
        assert base_session.tracking_log is None

    def test_inconsistent_frames_defaults_none(self, base_session: Session) -> None:
        assert base_session.inconsistent_frames is None

    def test_bbox_table_defaults_none(self, base_session: Session) -> None:
        assert base_session.bbox_table is None

    def test_bbox_summary_defaults_none(self, base_session: Session) -> None:
        assert base_session.bbox_summary is None

    def test_matching_results_defaults_none(self, base_session: Session) -> None:
        assert base_session.matching_results is None

    def test_idtrackerai_version_defaults_none(self, base_session: Session) -> None:
        assert base_session.idtrackerai_version is None

    def test_trajectory_format_defaults_none(self, base_session: Session) -> None:
        assert base_session.trajectory_format is None

    def test_raw_attrs_defaults_none(self, base_session: Session) -> None:
        assert base_session.raw_attrs is None

    def test_id_probabilities_stored_squeezed(self, tmp_path: Path) -> None:
        """(N, M, 1) array is stored; callers must squeeze — model stores as-is."""
        probs = np.ones((10, 2), dtype=np.float64) * 0.9
        s = Session(
            session_id="x", folder=tmp_path, reader="idtrackerai",
            video=VideoInfo(fps=25.0, n_frames=10, width_px=640, height_px=480),
            n_animals=2, trajectory_variant="with_gaps",
            has_stable_identities=True,
            raw_xy=np.zeros((10, 2, 2), dtype=np.float64),
            id_probabilities=probs,
        )
        assert s.id_probabilities is not None
        assert s.id_probabilities.shape == (10, 2)

    def test_quality_dict_stored(self, base_session: Session, tmp_path: Path) -> None:
        q = {"estimated_accuracy": 0.95, "fraction_identified": 0.82}
        s = Session(
            session_id="x", folder=tmp_path, reader="idtrackerai",
            video=VideoInfo(fps=25.0, n_frames=10, width_px=640, height_px=480),
            n_animals=2, trajectory_variant="with_gaps",
            has_stable_identities=True,
            raw_xy=np.zeros((10, 2, 2), dtype=np.float64),
            quality=q,
        )
        assert s.quality is not None
        assert s.quality["fraction_identified"] == pytest.approx(0.82)

    def test_inconsistent_frames_as_set(self, tmp_path: Path) -> None:
        s = Session(
            session_id="x", folder=tmp_path, reader="idtrackerai",
            video=VideoInfo(fps=25.0, n_frames=10, width_px=640, height_px=480),
            n_animals=2, trajectory_variant="with_gaps",
            has_stable_identities=True,
            raw_xy=np.zeros((10, 2, 2), dtype=np.float64),
            inconsistent_frames={0, 5, 9},
        )
        assert s.inconsistent_frames == {0, 5, 9}
        assert isinstance(s.inconsistent_frames, set)

    def test_tracking_intervals_list_of_tuples(self, tmp_path: Path) -> None:
        s = Session(
            session_id="x", folder=tmp_path, reader="idtrackerai",
            video=VideoInfo(fps=25.0, n_frames=100, width_px=640, height_px=480),
            n_animals=2, trajectory_variant="with_gaps",
            has_stable_identities=True,
            raw_xy=np.zeros((100, 2, 2), dtype=np.float64),
            tracking_intervals=[(0, 49), (60, 99)],
        )
        assert s.tracking_intervals == [(0, 49), (60, 99)]

    def test_matching_results_list_of_strings(self, tmp_path: Path) -> None:
        s = Session(
            session_id="x", folder=tmp_path, reader="idtrackerai",
            video=VideoInfo(fps=25.0, n_frames=10, width_px=640, height_px=480),
            n_animals=2, trajectory_variant="with_gaps",
            has_stable_identities=True,
            raw_xy=np.zeros((10, 2, 2), dtype=np.float64),
            matching_results=["session_trial1_Segment1"],
        )
        assert "session_trial1_Segment1" in s.matching_results  # type: ignore[operator]

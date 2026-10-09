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
    PreprocessReport,
    ProjectManifest,
    Session,
    SessionRef,
    SessionRunResult,
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
        # Off by default: re-permutes 17.1% of a real recording and injects
        # ~640px single-frame teleports (measured on the real corpus, see
        # IdSwitchCfg's docstring) -- pending a fragment-boundary-aware
        # replacement. Unlike gap_fill/jump/smoothing above, this one is
        # NOT on by default, and the only other place that was asserted
        # (tests/test_corpus/test_real_sessions.py) is corpus_local-marked
        # and skips automatically in CI, so a regression here would
        # otherwise pass CI silently. code-reviewer finding on #51,
        # Important #1.
        assert cfg.identity_switch.enabled is False
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

    def test_length_unit_label_defaults_cm_unconfirmed(self) -> None:
        """idtracker.ai's length_unit is a ratio to a user-defined unit,
        not necessarily centimetres -- default to "cm" (today's
        unconfirmed assumption, made explicit) with confirmed=False."""
        c = CalibrationConfig()
        assert c.length_unit_label == "cm"
        assert c.length_unit_confirmed_by_user is False

    def test_length_unit_label_settable(self) -> None:
        c = CalibrationConfig(length_unit_label="mm", length_unit_confirmed_by_user=True)
        assert c.length_unit_label == "mm"
        assert c.length_unit_confirmed_by_user is True


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

    def test_config_defaults_empty(self) -> None:
        m = MetricSelection()
        assert m.config == {}

    def test_config_stores_per_metric_param_dicts(self) -> None:
        """Keyed metric_id -> {param_name: value} -- see
        track2data/metrics/base.py's MetricParameter and
        UI_DESIGN.md:763's proposed shape."""
        m = MetricSelection(
            config={
                "IL-4": {"threshold_px_s": 2.5},
                "IL-7": {"threshold_px_s": 2.5, "min_bout_frames": 10},
            }
        )
        assert m.config["IL-4"]["threshold_px_s"] == pytest.approx(2.5)
        assert m.config["IL-7"]["min_bout_frames"] == 10

    def test_config_round_trips_through_json(self) -> None:
        m = MetricSelection(config={"GL-6": {"cohesion_source": "iid"}})
        restored = MetricSelection.model_validate_json(m.model_dump_json())
        assert restored == m

    def test_config_is_part_of_project_hash(self, tmp_path) -> None:
        """MetricSelection.config joins the reproducibility hash for
        free -- ProjectManifest.project_hash() dumps the whole
        manifest (minus timestamps), so a config-only difference must
        still change the hash."""
        from datetime import UTC, datetime

        from track2data.core.models import ProjectManifest

        now = datetime.now(tz=UTC)
        base = ProjectManifest(project_name="p", created_at=now, updated_at=now)
        configured = base.model_copy(
            update={"metrics": MetricSelection(config={"IL-4": {"threshold_px_s": 2.5}})}
        )
        assert base.project_hash() != configured.project_hash()


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


# ── SessionRef ─────────────────────────────────────────────────────────────────

class TestSessionRef:
    def test_has_stable_identities_defaults_to_none(self, tmp_path: Path) -> None:
        ref = SessionRef(session_id="s1", folder=tmp_path, sha256="abc")
        assert ref.has_stable_identities is None

    def test_has_stable_identities_can_be_set_explicitly(self, tmp_path: Path) -> None:
        ref = SessionRef(
            session_id="s1", folder=tmp_path, sha256="abc", has_stable_identities=True
        )
        assert ref.has_stable_identities is True


# ── SessionRunResult ─────────────────────────────────────────────────────────


class TestSessionRunResult:
    def test_preprocess_report_defaults_to_none(self) -> None:
        result = SessionRunResult(session_id="s1")
        assert result.preprocess_report is None

    def test_preprocess_report_stored(self) -> None:
        report = PreprocessReport()
        result = SessionRunResult(session_id="s1", preprocess_report=report)
        assert result.preprocess_report is report


# ── SessionRef.is_identity_free ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("declared", "override", "expected"),
    [
        (None, None, False),   # unprobed -- absence of evidence, not evidence
        (False, None, False),
        (True, None, True),
        (None, True, True),    # user answers before the probe lands
        (False, True, True),   # user overrules "tracked with identities"
        (True, False, False),  # user vouches for a wo-identities session
        (False, False, False),
        (True, True, True),
    ],
)
def test_session_ref_is_identity_free_truth_table(declared, override, expected) -> None:
    from track2data.core.models import SessionRef

    ref = SessionRef(
        session_id="s",
        folder=Path("s"),
        sha256="",
        track_wo_identities=declared,
        identity_free_override=override,
    )
    assert ref.is_identity_free() is expected


def test_manifest_written_before_identity_fields_still_loads() -> None:
    """Both fields are optional with defaults, so schema_version stays 1 and
    an existing .t2d.json keeps opening."""
    import json

    from track2data.core.models import ProjectManifest

    legacy = {
        "schema_version": 1,
        "project_name": "p",
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
        "sessions": [
            {"session_id": "s1", "folder": "s1", "sha256": "",
             "has_stable_identities": True}
        ],
    }
    manifest = ProjectManifest.model_validate(json.loads(json.dumps(legacy)))

    ref = manifest.sessions[0]
    assert ref.track_wo_identities is None
    assert ref.identity_free_override is None
    assert ref.is_identity_free() is False


def test_manifest_written_before_reader_fields_still_loads() -> None:
    """The saved reader choice is additive: an old manifest has none, and the engine then
    auto-detects exactly as it always did."""
    import json

    from track2data.core.models import ProjectManifest

    legacy = {
        "schema_version": 1,
        "project_name": "p",
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
        "sessions": [{"session_id": "s1", "folder": "s1", "sha256": ""}],
    }
    ref = ProjectManifest.model_validate(json.loads(json.dumps(legacy))).sessions[0]
    assert ref.reader is None
    assert ref.reader_options == {}
    assert ref.reader_chosen_by is None
    assert ref.reader_confidence is None


def test_a_reader_choice_round_trips_through_json() -> None:
    from track2data.core.models import SessionRef

    ref = SessionRef(
        session_id="s",
        folder=Path("s"),
        sha256="",
        reader="deeplabcut",
        reader_options={"fps": 30.0, "keypoint": "snout"},
        reader_chosen_by="user",
        reader_confidence="HIGH",
    )
    again = SessionRef.model_validate_json(ref.model_dump_json())
    assert again == ref
    # pydantic drops unknown fields silently, so equality alone would hold with no fields at all.
    assert again.reader == "deeplabcut"
    assert again.reader_options == {"fps": 30.0, "keypoint": "snout"}
    assert again.reader_chosen_by == "user"
    assert again.reader_confidence == "HIGH"


def test_reader_chosen_by_accepts_only_the_two_known_values() -> None:
    import pytest
    from pydantic import ValidationError

    from track2data.core.models import SessionRef

    for value in ("detected", "user", None):
        SessionRef(session_id="s", folder=Path("s"), sha256="", reader_chosen_by=value)
    with pytest.raises(ValidationError):
        SessionRef(session_id="s", folder=Path("s"), sha256="", reader_chosen_by="guess")


def test_refs_do_not_share_one_options_dict() -> None:
    from track2data.core.models import SessionRef

    a = SessionRef(session_id="a", folder=Path("a"), sha256="")
    b = SessionRef(session_id="b", folder=Path("b"), sha256="")
    a.reader_options["fps"] = 30.0
    assert b.reader_options == {}


def test_the_project_hash_depends_on_which_reader_read_the_sessions() -> None:
    """A different reader (or different options) is a different analysis."""
    from datetime import datetime

    from track2data.core.models import ProjectManifest, SessionRef

    def manifest(**ref_fields: object) -> ProjectManifest:
        return ProjectManifest(
            project_name="p",
            created_at=datetime(2026, 1, 1),
            updated_at=datetime(2026, 1, 1),
            sessions=[SessionRef(session_id="s", folder=Path("s"), sha256="", **ref_fields)],
        )

    plain = manifest().project_hash()
    assert manifest(reader="deeplabcut").project_hash() != plain
    assert (
        manifest(reader="deeplabcut", reader_options={"fps": 30.0}).project_hash()
        != manifest(reader="deeplabcut", reader_options={"fps": 25.0}).project_hash()
    )


# ── SceneConfig: the camera view the recording was made from ────────────────


def test_manifest_written_before_scene_still_loads_as_unknown() -> None:
    """The camera view is additive: an old manifest has none and reads as 'unknown', which
    leaves every metric behaving exactly as before."""
    import json

    from track2data.core.models import ProjectManifest

    legacy = {
        "schema_version": 1,
        "project_name": "p",
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
    }
    manifest = ProjectManifest.model_validate(json.loads(json.dumps(legacy)))
    assert manifest.scene.camera_view == "unknown"


@pytest.mark.parametrize("view", ["unknown", "top", "side"])
def test_a_camera_view_round_trips_through_json(view: str) -> None:
    from track2data.core.models import ProjectManifest, SceneConfig

    now = datetime(2026, 1, 1)
    manifest = ProjectManifest(
        project_name="p",
        created_at=now,
        updated_at=now,
        scene=SceneConfig(camera_view=view),
    )
    again = ProjectManifest.model_validate_json(manifest.model_dump_json())
    assert again.scene.camera_view == view


def test_an_unknown_camera_view_value_is_rejected() -> None:
    from pydantic import ValidationError

    from track2data.core.models import SceneConfig

    with pytest.raises(ValidationError):
        SceneConfig(camera_view="underwater")


# ── ProjectMode ────────────────────────────────────────────────────────────────


def _mode_manifest(**kw: object) -> ProjectManifest:
    now = datetime(2026, 1, 1)
    return ProjectManifest(project_name="p", created_at=now, updated_at=now, **kw)


def test_mode_defaults_to_2d() -> None:
    from track2data.core.models import ProjectMode

    m = _mode_manifest()
    assert m.mode == ProjectMode()
    assert m.mode.dimension == "2d"
    assert m.mode.layout is None
    assert not hasattr(m.mode, "id_map")


def test_mode_3d_requires_layout() -> None:
    from pydantic import ValidationError

    from track2data.core.models import ProjectMode

    with pytest.raises(ValidationError):
        ProjectMode(dimension="3d")


def test_mode_2d_rejects_layout() -> None:
    from pydantic import ValidationError

    from track2data.core.models import ProjectMode

    with pytest.raises(ValidationError):
        ProjectMode(dimension="2d", layout="two_videos")


def test_mode_roundtrip_keeps_pairing() -> None:
    from track2data.core.models import PairingPatterns, ProjectMode

    pairing = PairingPatterns(top_regex="_top$", side_regex="_side$")
    m = _mode_manifest(mode=ProjectMode(dimension="3d", layout="two_videos", pairing=pairing))
    restored = ProjectManifest.model_validate(m.model_dump())
    assert restored == m
    assert restored.mode.pairing == pairing


def test_old_manifest_without_mode_loads() -> None:
    from track2data.core.models import ProjectMode

    data = _mode_manifest().model_dump(exclude={"mode"})
    assert ProjectManifest.model_validate(data).mode == ProjectMode()


def test_project_hash_depends_on_mode() -> None:
    from track2data.core.models import ProjectMode

    mode3d = ProjectMode(dimension="3d", layout="single_video_two_panels")
    assert _mode_manifest().project_hash() != _mode_manifest(mode=mode3d).project_hash()


# ── View roles, pairs and pairing patterns ────────────────────────────────────


def test_view_defaults() -> None:
    from track2data.core.models import (
        VIEWS_3D_ONLY,
        PairingPatterns,
        ProjectMode,
        SessionRef,
        ViewPair,
    )

    ref = SessionRef(session_id="a", folder=Path("/x"), sha256="0")
    assert ref.view_role is None
    pair = ViewPair(top_session_id="a", side_session_id="b")
    assert pair.same_ids is False
    assert pair.fish_map == {}
    assert pair.auto is False
    assert PairingPatterns() == PairingPatterns(top_regex="", side_regex="")
    assert ProjectMode().pairing == PairingPatterns()
    assert _mode_manifest().view_pairs == []
    assert VIEWS_3D_ONLY == "Views apply to 3-D projects only"


def test_view_pair_rejects_same_session() -> None:
    from pydantic import ValidationError

    from track2data.core.models import ViewPair

    with pytest.raises(ValidationError):
        ViewPair(top_session_id="a", side_session_id="a")


def test_old_manifest_with_id_map_loads() -> None:
    data = _mode_manifest().model_dump()
    data["mode"]["id_map"] = {"a": "b"}
    m = ProjectManifest.model_validate(data)
    assert not hasattr(m.mode, "id_map")


def test_manifest_without_view_fields_loads() -> None:
    data = _mode_manifest().model_dump(exclude={"view_pairs"})
    assert ProjectManifest.model_validate(data).view_pairs == []


def _views_manifest() -> ProjectManifest:
    from track2data.core.models import PairingPatterns, ProjectMode, SessionRef, ViewPair

    return _mode_manifest(
        sessions=[
            SessionRef(session_id="a", folder=Path("/x"), sha256="0", view_role="top"),
            SessionRef(session_id="b", folder=Path("/y"), sha256="1", view_role="side"),
        ],
        mode=ProjectMode(
            dimension="3d",
            layout="two_videos",
            pairing=PairingPatterns(top_regex="top", side_regex="side"),
        ),
        view_pairs=[ViewPair(top_session_id="a", side_session_id="b", fish_map={"0": "1"})],
    )


def test_views_roundtrip_json() -> None:
    m = _views_manifest()
    assert ProjectManifest.model_validate_json(m.model_dump_json()) == m


def test_project_hash_depends_on_pairs() -> None:
    m = _views_manifest()
    other = m.model_copy(update={"view_pairs": []})
    assert m.project_hash() != other.project_hash()


# ── Panel rectangle on a session ──────────────────────────────────────────────


def test_panel_defaults_to_none() -> None:
    from track2data.core.models import PANELS_ONLY_FOR_SINGLE_VIDEO, PanelRect, SessionRef

    assert SessionRef(session_id="a", folder=Path("/x"), sha256="0").panel is None
    rect = PanelRect(width=10, height=5)
    assert (rect.x, rect.y) == (0.0, 0.0)
    assert PANELS_ONLY_FOR_SINGLE_VIDEO == "Panels apply to the 'One video, two panels' layout only"


@pytest.mark.parametrize("width,height", [(0, 5), (5, 0), (-1, 5), (5, -1)])
def test_panel_rect_rejects_non_positive_size(width: float, height: float) -> None:
    from pydantic import ValidationError

    from track2data.core.models import PanelRect

    with pytest.raises(ValidationError):
        PanelRect(width=width, height=height)


@pytest.mark.parametrize("x,y", [(-1, 0), (0, -1)])
def test_panel_rect_rejects_negative_origin(x: float, y: float) -> None:
    from pydantic import ValidationError

    from track2data.core.models import PanelRect

    with pytest.raises(ValidationError):
        PanelRect(x=x, y=y, width=10, height=10)


def _panel_manifest(panel=None) -> ProjectManifest:
    from track2data.core.models import ProjectMode, SessionRef

    return _mode_manifest(
        sessions=[SessionRef(session_id="a", folder=Path("/x"), sha256="0", panel=panel)],
        mode=ProjectMode(dimension="3d", layout="single_video_two_panels"),
    )


def test_session_ref_with_panel_roundtrips_json() -> None:
    from track2data.core.models import PanelRect

    m = _panel_manifest(PanelRect(x=10, y=20, width=300, height=200))
    back = ProjectManifest.model_validate_json(m.model_dump_json())
    assert back == m
    assert back.sessions[0].panel == PanelRect(x=10, y=20, width=300, height=200)


def test_old_manifest_without_panel_loads() -> None:
    data = _panel_manifest().model_dump()
    for s in data["sessions"]:
        s.pop("panel")
    assert ProjectManifest.model_validate(data).sessions[0].panel is None


def test_project_hash_depends_on_panel() -> None:
    from track2data.core.models import PanelRect

    assert (
        _panel_manifest().project_hash()
        != _panel_manifest(PanelRect(width=10, height=10)).project_hash()
    )


# ── Fusion settings on a view pair ────────────────────────────────────────────

_FUSION = {"surface_row": 10.0, "floor_row": 110.0, "tank_height_cm": 20.0}


def test_fusion_settings_defaults() -> None:
    from track2data.core.models import FusionSettings

    f = FusionSettings(**_FUSION)
    assert f.frame_offset == 0
    assert f.horizontal_axis == "x"
    assert f.flip is False


@pytest.mark.parametrize("missing", list(_FUSION))
def test_fusion_settings_requires_the_three_fields(missing: str) -> None:
    from pydantic import ValidationError

    from track2data.core.models import FusionSettings

    kw = {k: v for k, v in _FUSION.items() if k != missing}
    with pytest.raises(ValidationError):
        FusionSettings(**kw)


@pytest.mark.parametrize(
    "override",
    [
        {"surface_row": 110.0},
        {"surface_row": 120.0},
        {"surface_row": -1.0},
        {"tank_height_cm": 0.0},
        {"tank_height_cm": -5.0},
        {"surface_row": float("inf")},
        {"floor_row": float("inf")},
        {"tank_height_cm": float("nan")},
        {"surface_row": float("nan")},
        {"frame_offset": 1.5},
        {"horizontal_axis": "z"},
    ],
)
def test_fusion_settings_rejects_invalid(override: dict) -> None:
    from pydantic import ValidationError

    from track2data.core.models import FusionSettings

    with pytest.raises(ValidationError):
        FusionSettings(**{**_FUSION, **override})


def test_fusion_settings_message_for_inverted_rows() -> None:
    from pydantic import ValidationError

    from track2data.core.models import FusionSettings

    with pytest.raises(ValidationError, match="surface_row must be above floor_row"):
        FusionSettings(**{**_FUSION, "surface_row": 110.0})


def _fusion_manifest(fusion=None) -> ProjectManifest:
    m = _views_manifest()
    pair = m.view_pairs[0].model_copy(update={"fusion": fusion})
    return m.model_copy(update={"view_pairs": [pair]})


def test_view_pair_fusion_defaults_to_none() -> None:
    from track2data.core.models import ViewPair

    assert ViewPair(top_session_id="a", side_session_id="b").fusion is None


def test_view_pair_with_fusion_roundtrips_json() -> None:
    from track2data.core.models import FusionSettings

    m = _fusion_manifest(FusionSettings(frame_offset=-3, flip=True, **_FUSION))
    back = ProjectManifest.model_validate_json(m.model_dump_json())
    assert back == m
    assert back.view_pairs[0].fusion.frame_offset == -3


def test_old_manifest_without_fusion_loads() -> None:
    data = _fusion_manifest().model_dump()
    for p in data["view_pairs"]:
        p.pop("fusion")
    assert ProjectManifest.model_validate(data).view_pairs[0].fusion is None


def test_project_hash_depends_on_fusion() -> None:
    from track2data.core.models import FusionSettings

    none = _fusion_manifest().project_hash()
    zero = _fusion_manifest(FusionSettings(**_FUSION)).project_hash()
    shifted = _fusion_manifest(FusionSettings(frame_offset=2, **_FUSION)).project_hash()
    assert len({none, zero, shifted}) == 3


def test_preprocessed_session_depth_defaults_to_none() -> None:
    from track2data.core.models import PreprocessedSession

    psess = PreprocessedSession(session=None, xy=np.zeros((2, 1, 2)), kinematics=None)
    assert psess.depth is None

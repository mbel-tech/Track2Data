"""Coverage for the fixture-fidelity, provenance and diagnostic-code work.

Groups: tiny_real fixture variants (h5, calibrated, dict identities_groups),
the batch-comparability check, calibration spread / README provenance, the
reader's IDT_* log codes, the video-path rebase, the opt-in blob body-length
source, and manifest hashing.
"""

from __future__ import annotations

import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from tests.conftest import TINY_REAL_CALIBRATED_LENGTH_UNIT, _build_tiny_real_session
from track2data.api import Engine
from track2data.calibration.session_unit import (
    apply_session_calibration,
    length_calibration_spread,
)
from track2data.core.models import (
    CalibrationConfig,
    PreprocessedSession,
    PreprocessReport,
    ProjectManifest,
    SecurityConfig,
    SessionRef,
)
from track2data.core.session_consistency import SessionSummary, heterogeneity_warnings
from track2data.readers import read_session


def _manifest(**kw) -> ProjectManifest:
    now = datetime.now(tz=UTC)
    return ProjectManifest(project_name="p", created_at=now, updated_at=now, **kw)


# ── #78 fixtures ─────────────────────────────────────────────────────────────


def test_tiny_real_identities_groups_is_a_dict(tiny_real_session: Path) -> None:
    assert read_session(tiny_real_session, allow_pickle=True).identities_groups == {}


def test_tiny_real_h5_is_read_through_the_h5_path(tiny_real_h5: Path) -> None:
    assert not (tiny_real_h5 / "trajectories" / "trajectories.npy").exists()
    # No pickle consent needed: h5 is inert.
    s = read_session(tiny_real_h5, allow_pickle=False)
    assert s.trajectory_format == "h5"
    assert s.trajectory_source is not None and s.trajectory_source.suffix == ".h5"
    assert s.raw_xy.shape == (10, 2, 2)
    assert s.length_unit is None
    assert s.identities_groups == {}


def test_tiny_real_calibrated_has_positive_length_unit(
    tiny_real_calibrated: Path,
) -> None:
    s = read_session(tiny_real_calibrated, allow_pickle=True)
    assert s.length_unit == pytest.approx(TINY_REAL_CALIBRATED_LENGTH_UNIT)


def test_session_calibration_mode_end_to_end(tiny_real_calibrated: Path) -> None:
    session = read_session(tiny_real_calibrated, allow_pickle=True)
    psess = PreprocessedSession(
        session=session, xy=session.raw_xy,
        kinematics=None, report=PreprocessReport(),  # type: ignore[arg-type]
    )
    out = apply_session_calibration(psess, CalibrationConfig(mode="session"))
    assert out.px_per_cm == pytest.approx(TINY_REAL_CALIBRATED_LENGTH_UNIT)


# ── #76 batch comparability + provenance ─────────────────────────────────────


def _summary(sid: str, **kw) -> SessionSummary:
    base = dict(
        session_id=sid, reader="r", fps=30.0, n_frames=100, n_animals=2,
        width_px=100, height_px=100, length_unit=None, calibration_mode="bodylength",
        px_per_cm=None,
    )
    return SessionSummary(**{**base, **kw})


def test_mixed_segmentation_params_warn() -> None:
    w = heterogeneity_warnings([
        _summary("a", segmentation_params={"intensity_ths": [10, 128]}),
        _summary("b", segmentation_params={"intensity_ths": [10, 200]}),
    ])
    assert any("segmented with different" in x for x in w)


def test_mixed_identification_settings_warn() -> None:
    w = heterogeneity_warnings([
        _summary("a", resolution_reduction=0.75, id_image_size=(80, 80, 1)),
        _summary("b", resolution_reduction=1.0, id_image_size=(80, 80, 1)),
    ])
    assert any("identification-image" in x for x in w)


def test_matching_params_do_not_warn() -> None:
    kw = dict(segmentation_params={"a": 1}, resolution_reduction=1.0,
              id_image_size=(80, 80, 1))
    assert heterogeneity_warnings([_summary("a", **kw), _summary("b", **kw)]) == []


def test_from_session_carries_the_comparability_fields(tiny_real_session: Path) -> None:
    s = read_session(tiny_real_session, allow_pickle=True)
    summ = SessionSummary.from_session(s, calibration_mode="scalar")
    assert summ.segmentation_params and summ.resolution_reduction == 0.75
    assert summ.id_image_size == (80, 80, 1)


def test_length_calibration_spread() -> None:
    clicks = [
        {"point_A": [0, 0], "point_B": [10, 0], "distance": 1.0},
        {"point_A": [0, 0], "point_B": [0, 12], "distance": 1.0},
        {"point_A": "bad"},
    ]
    n, rel = length_calibration_spread(clicks)
    assert n == 2 and rel == pytest.approx(0.1286, abs=1e-3)
    assert length_calibration_spread(clicks[:1]) == (1, None)
    assert length_calibration_spread(None) == (0, None)


# ── #77 IDT_* codes, video rebase ────────────────────────────────────────────


def test_unreachable_video_and_resource_forks_are_logged(
    tiny_real_session: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        s = read_session(tiny_real_session, allow_pickle=True)
    assert s.video.path is None
    assert "IDT_VIDEO_PATH_UNREACHABLE" in caplog.text
    assert "IDT_RESOURCE_FORK_IGNORED" in caplog.text
    assert "IDT_BODY_LENGTH_UNRELIABLE" in caplog.text
    assert "IDT_VERSION_UNKNOWN" not in caplog.text  # 6.0.13 is known


def test_unknown_version_and_failed_run_are_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    folder = tmp_path / "s"
    _build_tiny_real_session(folder)
    sj = folder / "session.json"
    sj.write_text(sj.read_text().replace('"version": "6.0.13"', '"version": "9.9"', 1))
    (folder / "idtrackerai.log").write_text(
        "10:00:00 starting  run.py:1\nTraceback (most recent call last):\n"
        "ValueError: boom\n"
    )
    import numpy as np

    d = np.load(folder / "trajectories" / "trajectories.npy", allow_pickle=True).item()
    d["version"] = "9.9"
    np.save(folder / "trajectories" / "trajectories.npy", d, allow_pickle=True)
    with caplog.at_level(logging.INFO):
        read_session(folder, allow_pickle=True)
    assert "IDT_VERSION_UNKNOWN" in caplog.text
    assert "IDT_PARTIAL_SESSION" in caplog.text


def test_set_video_path_is_applied_on_import(
    tiny_real_session: Path, tmp_path: Path
) -> None:
    video = tmp_path / "real.mp4"
    video.write_bytes(b"x")
    ref = SessionRef(session_id=tiny_real_session.name, folder=tiny_real_session, sha256="")
    engine = Engine(_manifest(
        sessions=[ref], security=SecurityConfig(allow_pickle_trajectories=True),
    ))
    assert engine.import_session(tiny_real_session).video.path is None
    engine.set_video_path(tiny_real_session.name, video)
    assert engine.import_session(tiny_real_session).video.path == video
    with pytest.raises(FileNotFoundError):
        engine.set_video_path(tiny_real_session.name, tmp_path / "missing.mp4")
    with pytest.raises(KeyError):
        engine.set_video_path("nope", video)


# ── #72 opt-in blob body length ──────────────────────────────────────────────


def test_blobs_source_without_pickle_consent_keeps_session_value(
    tiny_real_h5: Path, caplog: pytest.LogCaptureFixture
) -> None:
    engine = Engine(_manifest(calibration=CalibrationConfig(body_length_source="blobs")))
    with caplog.at_level(logging.WARNING):
        s = engine.import_session(tiny_real_h5)
    assert s.blob_body_length_source_file is None
    assert "allow_pickle_trajectories" in caplog.text


def test_default_body_length_source_is_session() -> None:
    assert CalibrationConfig().body_length_source == "session"


# ── #73 hashing ──────────────────────────────────────────────────────────────


def test_project_hash_changes_when_input_data_changes(tmp_path: Path) -> None:
    def m(sha: str) -> ProjectManifest:
        return _manifest(sessions=[SessionRef(session_id="s", folder=tmp_path, sha256=sha)])

    assert m("a" * 64).project_hash() != m("b" * 64).project_hash()
    assert m("a" * 64).project_hash() == m("a" * 64).project_hash()




# ── #75 D-12 ─────────────────────────────────────────────────────────────────


def test_d12_reads_fragment_scores_from_quality(tiny_real_session: Path) -> None:
    from track2data.metrics.diagnostic import FragmentQualityScores

    s = read_session(tiny_real_session, allow_pickle=True)
    row = FragmentQualityScores().compute(s).iloc[0]
    assert row["fragment_connectivity"] == pytest.approx(1.34)
    assert row["silhouette_score"] == pytest.approx(0.781)


def test_d12_is_nan_without_quality(tiny_real_session: Path) -> None:
    from track2data.metrics.diagnostic import FragmentQualityScores

    s = read_session(tiny_real_session, allow_pickle=True).model_copy(update={"quality": None})
    row = FragmentQualityScores().compute(s).iloc[0]
    assert np.isnan(row["fragment_connectivity"]) and row["note"]


# ── #75 D-13..D-16 ───────────────────────────────────────────────────────────


def _frag(start, end, **kw):
    return {"identifier": start, "start_frame": start, "end_frame": end,
            "is_an_individual": True, **kw}


def _with_fragments(session, frags):
    return session.model_copy(update={"fragments": {"n_animals": 2, "fragments": frags}})


def test_d13_frame_weighted_certainty_per_identity(tiny_real_session: Path) -> None:
    from track2data.metrics.diagnostic import FragmentIdentityCertainty

    s = _with_fragments(read_session(tiny_real_session, allow_pickle=True), [
        _frag(0, 2, identity=1, certainty=0.2),
        _frag(2, 10, identity=1, certainty=1.0),
        _frag(0, 10, identity=2, certainty=-0.0069),
        _frag(0, 10),                              # no identity: skipped
        _frag(0, 5, identity=3, certainty=1.0),    # out of range: skipped
    ])
    df = FragmentIdentityCertainty().compute(s)
    a, b = df.iloc[0], df.iloc[1]
    assert a["individual_id"] == 0 and a["n_fragments"] == 2
    assert a["certainty_mean"] == pytest.approx((2 * 0.2 + 8 * 1.0) / 10)
    assert a["certainty_min"] == pytest.approx(0.2)
    assert b["certainty_mean"] == pytest.approx(-0.0069)


def test_d13_nan_without_fragments(tiny_real_session: Path) -> None:
    from track2data.metrics.diagnostic import FragmentIdentityCertainty

    df = FragmentIdentityCertainty().compute(read_session(tiny_real_session, allow_pickle=True))
    assert df["certainty_mean"].isna().all() and (df["n_fragments"] == 0).all()


def test_d14_fractions(tiny_real_session: Path) -> None:
    from track2data.metrics.diagnostic import CertainFragmentFrameFraction

    s = _with_fragments(read_session(tiny_real_session, allow_pickle=True), [
        _frag(0, 10, identity=1, certainty=0.9, identity_is_fixed=True),   # 10 frames
        _frag(0, 5, identity=2, certainty=0.1),                            # 5 frames
        {**_frag(0, 10), "is_an_individual": False},                       # crossing
    ])
    row = CertainFragmentFrameFraction().compute(s).iloc[0]
    assert row["frac_frames_certain"] == pytest.approx(10 / 20)
    assert row["frac_frames_identity_fixed"] == pytest.approx(10 / 20)
    assert row["frac_frames_individual"] == pytest.approx(15 / 20)


def test_d15_nan_until_blob_layer_is_read(tiny_real_session: Path) -> None:
    from track2data.metrics.diagnostic import TrackerCorrectionCensus

    s = read_session(tiny_real_session, allow_pickle=True)
    assert np.isnan(TrackerCorrectionCensus().compute(s).iloc[0]["n_corrected_frames"])
    row = TrackerCorrectionCensus().compute(
        s.model_copy(update={"tracker_corrected_frames": {1, 4}})
    ).iloc[0]
    assert row["n_corrected_frames"] == 2 and row["frac_corrected_frames"] == pytest.approx(0.2)


def test_find_identity_corrected_frames_distinguishes_unsupported_from_zero() -> None:
    from track2data.readers.idtrackerai.blobs import find_identity_corrected_frames

    class B:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    assert find_identity_corrected_frames([[B()], [B()]]) is None
    assert find_identity_corrected_frames(
        [[B(identity_corrected_solving_jumps=None)], [B(identity_corrected_solving_jumps=None)]]
    ) == set()
    assert find_identity_corrected_frames(
        [[B(identity_corrected_solving_jumps=None)], [B(identity_corrected_solving_jumps=2)]]
    ) == {1}


def test_blob_diagnostics_wires_corrections_into_import(
    tiny_real_session: Path, tmp_path: Path
) -> None:
    import pickle
    import sys
    import types

    folder = tmp_path / "s"
    shutil.copytree(tiny_real_session, folder)
    mod = types.ModuleType("idtrackerai.blob")
    pkg = types.ModuleType("idtrackerai")
    pkg.__path__ = []  # type: ignore[attr-defined]
    lob_mod = types.ModuleType("idtrackerai.list_of_blobs")
    blob_cls = type("Blob", (), {"__module__": "idtrackerai.blob"})
    lob_cls = type("ListOfBlobs", (), {"__module__": "idtrackerai.list_of_blobs"})
    mod.Blob, lob_mod.ListOfBlobs = blob_cls, lob_cls  # type: ignore[attr-defined]
    names = ("idtrackerai", "idtrackerai.blob", "idtrackerai.list_of_blobs")
    saved = {k: sys.modules.get(k) for k in names}
    sys.modules.update({"idtrackerai": pkg, "idtrackerai.blob": mod,
                        "idtrackerai.list_of_blobs": lob_mod})
    try:
        blobs = []
        for corrected in (None, 1, None):
            b = blob_cls()
            b.__dict__["identity_corrected_solving_jumps"] = corrected
            blobs.append([b])
        lob = lob_cls()
        lob.__dict__["blobs_in_video"] = blobs
        (folder / "preprocessing" / "list_of_blobs.pickle").write_bytes(pickle.dumps(lob))
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

    sec = SecurityConfig(allow_pickle_trajectories=True)
    off = Engine(_manifest(security=sec)).import_session(folder)
    on = Engine(_manifest(security=sec, blob_diagnostics=True)).import_session(folder)
    assert off.tracker_corrected_frames is None
    assert on.tracker_corrected_frames == {1}


def test_d16_distortion(tiny_real_session: Path) -> None:
    from track2data.metrics.diagnostic import PreprocessingDistortion

    s = read_session(tiny_real_session, allow_pickle=True)
    psess = PreprocessedSession(
        session=s, xy=s.raw_xy.copy(), kinematics=None,  # type: ignore[arg-type]
        report=PreprocessReport(),
    )
    clean = PreprocessingDistortion().compute(psess)
    assert (clean["rms_displacement_px"] == 0).all()
    assert (clean["frac_frames_altered"] == 0).all()
    assert clean["path_length_ratio"].tolist() == pytest.approx([1.0, 1.0])

    moved = s.raw_xy.copy()
    moved[5, 0, 1] += 100.0                       # a one-frame teleport
    out = PreprocessingDistortion().compute(
        PreprocessedSession(session=s, xy=moved, kinematics=None,  # type: ignore[arg-type]
                            report=PreprocessReport())
    )
    r0 = out.iloc[0]
    assert r0["frac_frames_altered"] == pytest.approx(1 / 10)
    assert r0["path_length_ratio"] > 1.5 and r0["distortion_index"] > 1
    assert out.iloc[1]["path_length_ratio"] == pytest.approx(1.0)

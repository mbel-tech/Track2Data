from datetime import UTC, datetime

import numpy as np
import pytest

from track2data.api import Engine
from track2data.core.errors import ImportError_
from track2data.core.models import (
    MODE_3D_BLOCK_REASON,
    ProjectManifest,
    ProjectMode,
    SessionRef,
    ViewPair,
)
from track2data.fusion.fuse import FusionError

from .builders import make_pair, settings


def _engine(monkeypatch, pairs, psesses, layout="two_videos", ids=("t", "s")):
    now = datetime.now(tz=UTC)
    manifest = ProjectManifest(
        project_name="p",
        created_at=now,
        updated_at=now,
        sessions=[SessionRef(session_id=i, folder=f"/tmp/{i}", sha256="") for i in ids],
        mode=ProjectMode(dimension="3d", layout=layout),
        view_pairs=pairs,
    )
    engine = Engine(manifest)
    monkeypatch.setattr(engine, "preprocess_ref", lambda ref: psesses[ref.session_id])
    return engine


def test_fuse_pair_returns_fused_session(monkeypatch):
    top, side, pair = make_pair()
    engine = _engine(monkeypatch, [pair], {"t": top, "s": side})
    fused = engine.fuse_pair(pair)
    assert fused.session_id == "t+s"
    assert fused.report.suggested_offset is None
    np.testing.assert_allclose(fused.psess.depth[:, 0], 0.25)


def test_same_video_ignores_offset_and_two_videos_uses_it(monkeypatch):
    top, side, pair = make_pair(fusion=settings(frame_offset=5))
    one = _engine(monkeypatch, [pair], {"t": top, "s": side}, layout="single_video_two_panels")
    assert one.fuse_pair(pair).report.overlap_frames == 100
    two = _engine(monkeypatch, [pair], {"t": top, "s": side}, layout="two_videos")
    assert two.fuse_pair(pair).report.overlap_frames == 95


def test_missing_session_raises(monkeypatch):
    top, _side, pair = make_pair(side_id="gone")
    engine = _engine(monkeypatch, [pair], {"t": top})
    with pytest.raises(FusionError, match="session not in the project: gone"):
        engine.fuse_pair(pair)


def test_fuse_all_collects_results_errors_and_skips(monkeypatch):
    top, side, pair = make_pair()
    no_settings = ViewPair(top_session_id="t", side_session_id="s2")
    bad = pair.model_copy(update={"fusion": settings(frame_offset=1000), "side_session_id": "s3"})
    psesses = {"t": top, "s": side, "s3": side}
    engine = _engine(monkeypatch, [pair, no_settings, bad], psesses, ids=("t", "s", "s2", "s3"))
    results, errors = engine.fuse_all()
    assert set(results) == {("t", "s")}
    assert set(errors) == {("t", "s3")}
    assert "no shared frames" in errors[("t", "s3")]


def test_offset_change_recomputes(monkeypatch):
    top, side, pair = make_pair()
    engine = _engine(monkeypatch, [pair], {"t": top, "s": side})
    a = engine.fuse_pair(pair).report.overlap_frames
    moved = pair.model_copy(update={"fusion": settings(frame_offset=10)})
    assert engine.fuse_pair(moved).report.overlap_frames == a - 10


def test_suggest_offset(monkeypatch):
    top, side, pair = make_pair()
    walk = np.cumsum(np.random.default_rng(1).normal(size=300))
    for k in range(3):
        top.xy[:, k, 0] = walk[:100] + 10 * k
    side.xy[:, :, 0] = top.xy[:, :, 0] * 5  # side scale is 10 px/cm, top is 2
    side.xy[:-7] = side.xy[7:].copy()  # the side view is 7 frames behind: side[i] = top[i+7]
    engine = _engine(monkeypatch, [pair], {"t": top, "s": side})
    assert engine.suggest_offset(pair) == -7
    gone = pair.model_copy(update={"side_session_id": "gone"})
    assert engine.suggest_offset(gone) is None


def test_require_computable_still_blocks_3d(monkeypatch):
    top, side, pair = make_pair()
    engine = _engine(monkeypatch, [pair], {"t": top, "s": side})
    with pytest.raises(ValueError, match=MODE_3D_BLOCK_REASON[:20]):
        engine.require_computable()


def _unreadable(engine, bad_id):
    real = engine.preprocess_ref

    def ref_or_raise(ref):
        if ref.session_id == bad_id:
            raise ImportError_("folder moved")
        return real(ref)

    engine.preprocess_ref = ref_or_raise


def test_unreadable_session_is_a_fusion_error(monkeypatch):
    top, side, pair = make_pair()
    engine = _engine(monkeypatch, [pair], {"t": top, "s": side})
    _unreadable(engine, "s")
    with pytest.raises(FusionError, match=r"session s could not be read: .*folder moved"):
        engine.fuse_pair(pair)
    assert engine.suggest_offset(pair) is None


def test_fuse_all_survives_an_unreadable_session(monkeypatch):
    top, side, pair = make_pair()
    other = pair.model_copy(update={"side_session_id": "s2"})
    psesses = {"t": top, "s": side, "s2": side}
    engine = _engine(monkeypatch, [pair, other], psesses, ids=("t", "s", "s2"))
    _unreadable(engine, "s2")
    results, errors = engine.fuse_all()
    assert set(results) == {("t", "s")}
    assert "session s2 could not be read" in errors[("t", "s2")]


def test_suggest_offset_none_for_single_video(monkeypatch):
    top, side, pair = make_pair()
    walk = np.cumsum(np.random.default_rng(1).normal(size=100))
    for k in range(3):
        top.xy[:, k, 0] = walk + 10 * k
    side.xy[:, :, 0] = top.xy[:, :, 0] * 5
    side.xy[:-7] = side.xy[7:].copy()
    engine = _engine(monkeypatch, [pair], {"t": top, "s": side})
    assert engine.suggest_offset(pair) == -7
    one = _engine(monkeypatch, [pair], {"t": top, "s": side}, layout="single_video_two_panels")
    assert one.suggest_offset(pair) is None

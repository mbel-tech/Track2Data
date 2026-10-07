"""SCI-02: zone metrics on identity-free sessions.

Occupancy metrics (Z-1, Z-2, Z-8) stay meaningful when pooled over all
detection slots and are emitted without ``individual_id``. Metrics that
follow a slot across frames (visits, transitions, events, latency, dwell)
require identity and are skipped.
"""

from __future__ import annotations

import numpy as np
import pytest

from tests.test_api import _identity_free_ref, _make_manifest, _make_psess, _make_session
from track2data.api import Engine
from track2data.core.models import MetricSelection

POOLED = {"Z-1", "Z-2", "Z-8"}
SEQUENTIAL = {"Z-3", "Z-4", "Z-5", "Z-6", "Z-7", "Z-9"}


def _zone_psess(identity_free: bool):
    session = _make_session(n_frames=20, n_animals=2).model_copy(
        update={"track_wo_identities": identity_free}
    )
    psess = _make_psess(session)
    zone = np.full((20, 2), "", dtype=object)
    zone[:10, 0] = "A"  # slot 0 in A for half the session
    zone[:, 1] = "A"    # slot 1 in A throughout
    psess.main_zone = zone
    return psess


def _engine(identity_free: bool) -> Engine:
    manifest = _make_manifest(
        sessions=[_identity_free_ref(track_wo_identities=identity_free)],
        metrics=MetricSelection(zone=sorted(POOLED | SEQUENTIAL)),
    )
    return Engine(manifest)


def test_sequential_zone_metrics_require_identity() -> None:
    from track2data import metrics

    metrics._load_builtins()
    for mid in SEQUENTIAL:
        assert metrics._registry[mid].requires_identity is True, mid
    for mid in POOLED:
        assert metrics._registry[mid].requires_identity is False, mid


def test_identity_free_session_skips_sequential_zone_metrics() -> None:
    results = _engine(True).compute_metrics(_zone_psess(True))
    assert not (SEQUENTIAL & set(results))


def test_identity_free_time_in_zone_is_pooled_without_individual_id() -> None:
    results = _engine(True).compute_metrics(_zone_psess(True))
    df = results["Z-1"]
    assert "individual_id" not in df.columns
    row = df[df["zone_name"] == "A"].iloc[0]
    # 10 + 20 frames of 20 frames x 2 slots at default fps
    assert row["time_pct"] == pytest.approx(30 / 40)


def test_identity_free_pooled_rows_for_z2_and_z8() -> None:
    engine = _engine(True)
    psess = _zone_psess(True)
    cfg = {"roi_areas": {"A": 50.0}, "total_arena_area": 100.0}
    engine._effective_cfg = lambda cls, ps: cfg  # type: ignore[method-assign]
    results = engine.compute_metrics(psess)
    for mid in ("Z-2", "Z-8"):
        assert "individual_id" not in results[mid].columns, mid
        assert len(results[mid]) == 1, mid


def test_normal_session_keeps_per_individual_zone_rows() -> None:
    results = _engine(False).compute_metrics(_zone_psess(False))
    assert "individual_id" in results["Z-1"].columns
    assert len(results["Z-1"]) == 2
    assert SEQUENTIAL & set(results)

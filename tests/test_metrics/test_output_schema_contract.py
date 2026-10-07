"""Every metric returns exactly the columns it declares.

``Metric.output_columns`` is the declared contract: the UI reads it, the
exporters read it, the docs are generated from it, and a downstream script
joining on a column name is trusting it.

The per-metric ``test_output_columns_present`` tests could not enforce it.
They asserted a hardcoded list of names was *present* -- a subset check
against a literal, so they never read ``output_columns`` at all, and an
undeclared extra column passed silently. Five metrics were shipping columns
they did not declare (IL-1's ``path_length_cm``/``_bl``, IL-2's
``mean_speed_cm_s``/``_bl_s``, GL-1's ``mean_nnd_cm``/``_bl``, GL-5's and
GL-7's ``*_cm_s``).

This runs the whole registry and asserts set *equality*, against both a
calibrated and an uncalibrated session -- which also pins that the
calibration-dependent columns are unconditional, i.e. NaN rather than
absent, so the schema does not change shape with a project setting.

Metrics are run through ``Engine._effective_cfg`` rather than called bare,
because several declare *derived* parameters the engine computes per session
(IL-3's arena radius gates ``time_in_centre_pct``). Calling them with
``cfg=None`` would report a column as missing when a real run always emits it.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

import track2data.metrics as metrics_registry
from track2data.core.models import (
    ROI,
    CalibrationConfig,
    MetricSelection,
    ProjectManifest,
    SecurityConfig,
    SessionRef,
    ZoneSet,
)


def _manifest(folder: Path) -> ProjectManifest:
    now = datetime.now(tz=UTC)
    return ProjectManifest(
        project_name="schema_contract",
        created_at=now,
        updated_at=now,
        sessions=[
            SessionRef(
                session_id=folder.name,
                folder=folder,
                sha256=hashlib.sha256(str(folder).encode()).hexdigest(),
            )
        ],
        calibration=CalibrationConfig(mode="scalar", px_per_cm=10.0),
        # Two zones so the zone-level metrics have something to occupy, and
        # an "inner"/"outer" split of the kind Z-* metrics assume.
        zones=ZoneSet(
            rois=[
                ROI(
                    name="inner",
                    level="main",
                    vertices=[(400.0, 400.0), (600.0, 400.0), (600.0, 600.0), (400.0, 600.0)],
                ),
                ROI(
                    name="outer",
                    level="main",
                    vertices=[(0.0, 0.0), (1000.0, 0.0), (1000.0, 1000.0), (0.0, 1000.0)],
                ),
            ]
        ),
        metrics=MetricSelection(),
        security=SecurityConfig(allow_pickle_trajectories=True),
    )


@pytest.fixture(params=["calibrated", "uncalibrated"])
def engine_and_psess(request, tiny_real_session: Path):  # type: ignore[no-untyped-def]
    """An Engine plus a preprocessed session, with and without calibration.

    The uncalibrated case is the one that catches a column being *dropped*
    rather than NaN-filled -- which is how a schema silently changes shape
    between two projects.
    """
    from track2data.api import Engine

    manifest = _manifest(tiny_real_session)
    if request.param == "uncalibrated":
        manifest = manifest.model_copy(
            update={"calibration": CalibrationConfig(mode="scalar", px_per_cm=None)}
        )

    engine = Engine(manifest)
    session = engine.import_session(tiny_real_session)
    # A longer, more varied trajectory than the 10-frame fixture, so metrics
    # that need movement (speed, turning, bouts) have something to measure
    # and do not bail out before reaching their calibrated columns.
    rng = np.random.default_rng(0)
    n_frames, n_animals = 400, session.n_animals
    xy = np.cumsum(rng.normal(0, 4.0, (n_frames, n_animals, 2)), axis=0)
    xy += rng.uniform(300, 700, (1, n_animals, 2))
    session = session.model_copy(update={"raw_xy": xy})

    return engine, engine.preprocess(session), request.param


@pytest.mark.parametrize("metric_id", metrics_registry.all_ids())
def test_metric_returns_exactly_the_columns_it_declares(
    metric_id: str, engine_and_psess
) -> None:  # type: ignore[no-untyped-def]
    engine, psess, calibration = engine_and_psess
    metric_cls = metrics_registry.get(metric_id)
    assert metric_cls is not None

    cfg = engine._effective_cfg(metric_cls, psess)
    try:
        df = metric_cls().compute(psess, cfg)
    except AttributeError:
        # D-1..D-10 describe the tracker's own output and read the raw
        # Session; D-11 and every non-diagnostic metric read the
        # preprocessed one.
        df = metric_cls().compute(psess.session, cfg)

    declared = set(metric_cls.output_columns)
    actual = set(df.columns)

    assert actual == declared, (
        f"{metric_id} ({calibration}) does not return what it declares.\n"
        f"  undeclared extras: {sorted(actual - declared) or 'none'}\n"
        f"  declared but absent: {sorted(declared - actual) or 'none'}\n"
        "Metric.output_columns is what the UI, the exporters and the "
        "generated docs promise; it has to match."
    )


@pytest.mark.parametrize("metric_id", metrics_registry.all_ids())
def test_declared_columns_have_no_duplicates(metric_id: str) -> None:
    """A duplicated name in the declaration silently shrinks the contract."""
    metric_cls = metrics_registry.get(metric_id)
    assert metric_cls is not None
    declared = metric_cls.output_columns
    assert len(declared) == len(set(declared)), (
        f"{metric_id} declares a duplicate column: {declared}"
    )


@pytest.mark.parametrize("metric_id", metrics_registry.all_ids())
def test_every_metric_declares_its_identity_columns(metric_id: str) -> None:
    """Nothing can be joined to a row that does not say which session it is
    from, or -- for a per-individual metric -- which animal."""
    metric_cls = metrics_registry.get(metric_id)
    assert metric_cls is not None
    declared = set(metric_cls.output_columns)

    assert "session_id" in declared, f"{metric_id} declares no session_id"
    if metric_cls.level == "individual":
        assert "individual_id" in declared, (
            f"{metric_id} is per-individual but declares no individual_id"
        )

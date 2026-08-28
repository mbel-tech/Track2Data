"""
``Metric.requires_identity`` pins which metrics Track2Data refuses to
compute for an identity-free session (Engine.compute_metrics), so this
file holds the classification as data rather than leaving it spread
across four metric modules where a new metric can silently join the
wrong side.

The flag used to be a proxy for ``level == "individual"``: every IL-*
plus D-3 was True and nothing else was, even though GL-3, GL-8 and GL-11
read ``kinematics.heading_rad`` -- built from ``xy[t+1] - xy[t]`` at a
*fixed row index* (preprocess/kinematics.py), which is identity-dependent
by construction, and which docs/METRICS_SPEC.md section 4.5 had always
listed as not identity-free derivable. That mismatch meant a
"identity-free" session still got polarisation and rotational-order
numbers computed from headings between unrelated animals.

The criterion, applied to what ``compute()`` actually reads:

    Does it consume a value derived from more than one frame at a fixed
    row index? (kinematics.speed_px_s, kinematics.heading_rad, any
    xy[t] -> xy[t+1] pairing at matching indices.) If yes, it requires
    identity.

GL-7 NNMatchedSpeed is the counter-example that shows the criterion is
about *how*, not *what*: it reports a speed, but re-matches detections
between each frame pair by nearest neighbour instead of trusting the row
index, so it stays identity-free.

Known gap, deliberately not encoded here: every Z-* metric emits an
``individual_id`` column yet declares ``requires_identity = False``. See
the module docstring of track2data/metrics/zone.py for why they are left
ungated and what fixing them properly requires.
"""

from __future__ import annotations

import pytest

from track2data import metrics
from track2data.metrics import base

# Every metric that must not run on an identity-free session.
IDENTITY_REQUIRING = {
    # All twelve individual metrics: each is a per-animal time series.
    "IL-1", "IL-2", "IL-3", "IL-4", "IL-5", "IL-6",
    "IL-7", "IL-8", "IL-9", "IL-10", "IL-11", "IL-14",
    # Group metrics built on per-individual headings.
    "GL-3",   # polarisation: mean unit heading vector
    "GL-8",   # rotational order: heading relative to the group centroid
    "GL-11",  # order-state classification: thresholds GL-3 against GL-8
    # Diagnostic: reports idtracker.ai's per-identity id_probabilities.
    # Always computed regardless (diagnostics bypass the gate), but the
    # flag is what it claims to be.
    "D-3",
}


@pytest.fixture(scope="module")
def registry() -> dict:
    metrics._load_builtins()
    return dict(metrics._registry)


def test_requires_identity_matches_the_pinned_classification(registry) -> None:
    actual = {mid for mid, cls in registry.items() if cls.requires_identity}
    assert actual == IDENTITY_REQUIRING, (
        "requires_identity has drifted from the pinned set. If this is "
        "deliberate, update IDENTITY_REQUIRING and the section 4.5 table in "
        "docs/METRICS_SPEC.md together -- the flag decides what "
        "Engine.compute_metrics refuses to compute."
    )


def test_every_pinned_id_is_actually_registered(registry) -> None:
    """Guards the pin against rot: a renamed or removed metric id would
    otherwise sit in IDENTITY_REQUIRING forever, gating nothing."""
    missing = IDENTITY_REQUIRING - set(registry)
    assert not missing, f"pinned but not registered: {sorted(missing)}"


@pytest.mark.parametrize("metric_id", ["GL-3", "GL-8", "GL-11"])
def test_heading_consuming_group_metrics_require_identity(metric_id, registry) -> None:
    """These three were the concrete bug: declared identity-free while
    reading headings derived from same-row-index displacement."""
    cls = registry[metric_id]
    assert cls.requires_identity is True
    assert any(
        "heading_rad" in inp for inp in cls.documentation.inputs
    ), f"{metric_id} no longer reads heading_rad; re-check its classification"


def test_gl7_is_identity_free_despite_reporting_a_speed(registry) -> None:
    cls = registry["GL-7"]
    assert cls.requires_identity is False
    # It must not be reading the per-individual kinematics arrays, or the
    # nearest-neighbour re-matching that makes it identity-free is moot.
    assert not any("kinematics" in inp for inp in cls.documentation.inputs)


def test_every_metric_declares_the_flag(registry) -> None:
    for mid, cls in registry.items():
        assert isinstance(cls.requires_identity, bool), (
            f"{mid} does not declare requires_identity as a bool"
        )


def test_base_metric_leaves_the_flag_undeclared(registry) -> None:
    """An annotation with no default, so a new metric class cannot inherit
    an accidental False and quietly become computable on identity-free
    sessions."""
    assert "requires_identity" not in vars(base.Metric)
    assert "requires_identity" in base.Metric.__annotations__

"""Tests for track2data.zones.orientation."""

from __future__ import annotations

from track2data.core.models import ROI, ZoneSet
from track2data.zones.orientation import flip_orientation, pair_orientation_zones

# ── helpers ────────────────────────────────────────────────────────────────────


def make_roi(name: str, level: str = "main") -> ROI:
    return ROI(name=name, level=level, vertices=[(0, 0), (10, 0), (10, 10), (0, 10)])


# ── pair_orientation_zones ────────────────────────────────────────────────────


def test_pair_orientation_ft_with_flow_in_name() -> None:
    """Zone named 'flow' should be labelled 'flow' for FT paradigm."""
    zs = ZoneSet(
        rois=[make_roi("flow"), make_roi("target")],
        orientation_tag="FT",
    )
    mapping = pair_orientation_zones(zs, "FT")
    assert mapping.get("flow") == "flow"


def test_pair_orientation_ft_target_zone() -> None:
    """Zone named 'target' should be labelled 'target' for FT paradigm."""
    zs = ZoneSet(
        rois=[make_roi("flow"), make_roi("target")],
        orientation_tag="FT",
    )
    mapping = pair_orientation_zones(zs, "FT")
    assert mapping.get("target") == "target"


def test_pair_orientation_none_returns_empty() -> None:
    """No orientation_tag → empty mapping regardless of tag argument."""
    zs = ZoneSet(rois=[make_roi("zone_A")], orientation_tag=None)
    mapping = pair_orientation_zones(zs, "FT")
    assert mapping == {}


def test_pair_orientation_only_main_zones_labelled() -> None:
    """Secondary zones should not appear in the orientation mapping."""
    zs = ZoneSet(
        rois=[make_roi("flow", level="main"), make_roi("side", level="secondary")],
        orientation_tag="FT",
    )
    mapping = pair_orientation_zones(zs, "FT")
    assert "side" not in mapping


def test_pair_orientation_zone_with_f_prefix() -> None:
    """Zone name starting with 'F' (like 'F1') should be labelled 'flow'."""
    zs = ZoneSet(
        rois=[make_roi("F1"), make_roi("T1")],
        orientation_tag="FT",
    )
    mapping = pair_orientation_zones(zs, "FT")
    assert mapping.get("F1") == "flow"


def test_pair_orientation_empty_rois() -> None:
    zs = ZoneSet(rois=[], orientation_tag="FT")
    mapping = pair_orientation_zones(zs, "FT")
    assert isinstance(mapping, dict)


# ── flip_orientation ──────────────────────────────────────────────────────────


def test_flip_orientation_returns_new_object() -> None:
    """flip_orientation must not mutate the original ZoneSet."""
    zs = ZoneSet(rois=[make_roi("zone_A")], orientation_tag="FT")
    flipped = flip_orientation(zs)
    assert flipped is not zs


def test_flip_orientation_does_not_mutate_input() -> None:
    original_tag = "FT"
    zs = ZoneSet(rois=[make_roi("zone_A")], orientation_tag=original_tag)
    flip_orientation(zs)
    assert zs.orientation_tag == original_tag


def test_flip_orientation_ft_becomes_tf() -> None:
    zs = ZoneSet(rois=[make_roi("zone_A")], orientation_tag="FT")
    flipped = flip_orientation(zs)
    assert flipped.orientation_tag == "TF"


def test_flip_orientation_tf_becomes_ft() -> None:
    zs = ZoneSet(rois=[make_roi("zone_A")], orientation_tag="TF")
    flipped = flip_orientation(zs)
    assert flipped.orientation_tag == "FT"


def test_flip_orientation_reverses_vertices() -> None:
    """Flipping should reverse the vertex order for each ROI."""
    vertices = [(0, 0), (10, 0), (10, 10), (0, 10)]
    roi = ROI(name="Z", level="main", vertices=vertices)
    zs = ZoneSet(rois=[roi], orientation_tag="FT")
    flipped = flip_orientation(zs)
    assert list(flipped.rois[0].vertices) == list(reversed(vertices))


def test_flip_orientation_preserves_roi_names() -> None:
    zs = ZoneSet(rois=[make_roi("alpha"), make_roi("beta")], orientation_tag="FT")
    flipped = flip_orientation(zs)
    names = {r.name for r in flipped.rois}
    assert names == {"alpha", "beta"}


def test_flip_orientation_none_tag_preserved() -> None:
    """If orientation_tag is None, flip returns a copy with None tag."""
    zs = ZoneSet(rois=[make_roi("zone_A")], orientation_tag=None)
    flipped = flip_orientation(zs)
    assert flipped.orientation_tag is None


def test_flip_orientation_idempotent_double_flip() -> None:
    """Double flip should restore original state."""
    vertices = [(0, 0), (10, 0), (10, 10), (0, 10)]
    roi = ROI(name="Z", level="main", vertices=vertices)
    zs = ZoneSet(rois=[roi], orientation_tag="FT")
    double_flipped = flip_orientation(flip_orientation(zs))
    assert double_flipped.orientation_tag == "FT"
    assert list(double_flipped.rois[0].vertices) == vertices

"""Tests for track2data.zones.io."""

from __future__ import annotations

from pathlib import Path

import pytest

from track2data.core.models import ROI, ZoneSet
from track2data.zones.io import load_zones_csv, save_zones_csv, zone_set_from_dict

# ── CSV round-trip ────────────────────────────────────────────────────────────


def test_csv_roundtrip(tmp_path: Path) -> None:
    roi = ROI(name="A", level="main", vertices=[(0, 0), (10, 0), (10, 10), (0, 10)])
    zs = ZoneSet(rois=[roi])
    path = tmp_path / "zones.csv"
    save_zones_csv(zs, path)
    loaded = load_zones_csv(path)
    assert len(loaded.rois) == 1
    assert loaded.rois[0].name == "A"
    assert len(loaded.rois[0].vertices) == 4


def test_csv_roundtrip_multiple_rois(tmp_path: Path) -> None:
    rois = [
        ROI(name="main_zone", level="main", vertices=[(0, 0), (100, 0), (100, 100), (0, 100)]),
        ROI(
            name="sec_zone",
            level="secondary",
            vertices=[(10, 10), (50, 10), (50, 50), (10, 50)],
        ),
    ]
    zs = ZoneSet(rois=rois)
    path = tmp_path / "zones.csv"
    save_zones_csv(zs, path)
    loaded = load_zones_csv(path)
    assert len(loaded.rois) == 2
    names = {r.name for r in loaded.rois}
    assert names == {"main_zone", "sec_zone"}


def test_csv_roundtrip_levels_preserved(tmp_path: Path) -> None:
    roi_main = ROI(name="M", level="main", vertices=[(0, 0), (10, 0), (10, 10), (0, 10)])
    roi_sec = ROI(name="S", level="secondary", vertices=[(20, 20), (30, 20), (30, 30), (20, 30)])
    zs = ZoneSet(rois=[roi_main, roi_sec])
    path = tmp_path / "zones.csv"
    save_zones_csv(zs, path)
    loaded = load_zones_csv(path)
    levels = {r.name: r.level for r in loaded.rois}
    assert levels["M"] == "main"
    assert levels["S"] == "secondary"


def test_csv_roundtrip_vertices_accurate(tmp_path: Path) -> None:
    vertices = [(1.5, 2.5), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    roi = ROI(name="precise", level="main", vertices=vertices)
    zs = ZoneSet(rois=[roi])
    path = tmp_path / "zones.csv"
    save_zones_csv(zs, path)
    loaded = load_zones_csv(path)
    loaded_verts = loaded.rois[0].vertices
    assert len(loaded_verts) == 4
    for (ox, oy), (lx, ly) in zip(vertices, loaded_verts, strict=True):
        assert lx == pytest.approx(ox)
        assert ly == pytest.approx(oy)


def test_csv_file_has_header(tmp_path: Path) -> None:
    roi = ROI(name="Z", level="main", vertices=[(0, 0), (1, 0), (1, 1), (0, 1)])
    zs = ZoneSet(rois=[roi])
    path = tmp_path / "zones.csv"
    save_zones_csv(zs, path)
    text = path.read_text(encoding="utf-8")
    first_line = text.splitlines()[0].lower()
    assert "roi_name" in first_line or "name" in first_line


def test_load_csv_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_zones_csv(tmp_path / "nonexistent.csv")


def test_csv_empty_zone_set(tmp_path: Path) -> None:
    zs = ZoneSet(rois=[])
    path = tmp_path / "zones.csv"
    save_zones_csv(zs, path)
    loaded = load_zones_csv(path)
    assert len(loaded.rois) == 0


# ── zone_set_from_dict ────────────────────────────────────────────────────────


def test_zone_set_from_dict_basic() -> None:
    data = {
        "rois": [
            {
                "name": "A",
                "level": "main",
                "vertices": [[0, 0], [10, 0], [10, 10], [0, 10]],
            }
        ]
    }
    zs = zone_set_from_dict(data)
    assert isinstance(zs, ZoneSet)
    assert len(zs.rois) == 1
    assert zs.rois[0].name == "A"


def test_zone_set_from_dict_with_orientation_tag() -> None:
    data = {
        "rois": [],
        "orientation_tag": "FT",
    }
    zs = zone_set_from_dict(data)
    assert zs.orientation_tag == "FT"


def test_zone_set_from_dict_empty() -> None:
    zs = zone_set_from_dict({})
    assert isinstance(zs, ZoneSet)
    assert len(zs.rois) == 0


def test_zone_set_from_dict_tuple_vertices() -> None:
    """Vertices given as lists should be coerced to tuples by pydantic."""
    data = {
        "rois": [
            {
                "name": "B",
                "level": "secondary",
                "vertices": [[5.0, 6.0], [15.0, 6.0], [15.0, 16.0], [5.0, 16.0]],
            }
        ]
    }
    zs = zone_set_from_dict(data)
    assert zs.rois[0].vertices[0] == (5.0, 6.0)

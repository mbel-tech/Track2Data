"""A project without a water column or a native session serialises as it did before the feature.

The golden values were computed from a clean checkout of fc5b2fc (before native 3-D files) on the
manifest built here.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from tests.test_fusion.scene import build_scene
from track2data.api import Engine
from track2data.core.models import (
    CalibrationConfig,
    MetricSelection,
    ProjectManifest,
    ProjectMode,
    SessionRef,
    WaterColumn,
)

GOLDEN_HASH = "957743be77913e61"
GOLDEN_JSON_INDENT_SHA = "2e83fcdce8080d6471620aad69238ad9461e91cd2b2623ca84cdfa3c4e78e922"
GOLDEN_JSON_SHA = "8b06d0dd10f5ce93a06d31d8549a16e98bbd8b349c8342ce0737a7632fbd9950"


def _manifest(water_column: WaterColumn | None = None) -> ProjectManifest:
    t = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    return ProjectManifest(
        # pinned: the manifest stamps the app version, and the golden values were computed
        # with 0.2.1, so a release bump must not change them
        app_version="0.2.1",
        project_name="golden",
        created_at=t,
        updated_at=t,
        sessions=[
            SessionRef(
                session_id="s1", folder=Path("/data/s1"), sha256="ab" * 32, reader="idtrackerai"
            )
        ],
        calibration=CalibrationConfig(mode="scalar", px_per_cm=8.0, water_column=water_column),
        metrics=MetricSelection(individual=["IL-1", "IL-2"]),
    )


def test_a_pixel_manifest_hashes_and_serialises_as_before() -> None:
    manifest = _manifest()
    assert manifest.project_hash() == GOLDEN_HASH
    indented = manifest.model_dump_json(indent=2).encode()
    assert hashlib.sha256(indented).hexdigest() == GOLDEN_JSON_INDENT_SHA
    assert hashlib.sha256(manifest.model_dump_json().encode()).hexdigest() == GOLDEN_JSON_SHA
    assert "water_column" not in manifest.calibration.model_dump(mode="json")


def test_a_water_column_is_kept_hashed_and_round_trips() -> None:
    manifest = _manifest(WaterColumn(surface_z=0.0, floor_z=20.0))
    assert manifest.project_hash() != GOLDEN_HASH
    again = ProjectManifest.model_validate_json(manifest.model_dump_json())
    assert again.calibration.water_column == WaterColumn(surface_z=0.0, floor_z=20.0)
    assert again.project_hash() == manifest.project_hash()
    assert ProjectManifest.model_validate_json(_manifest().model_dump_json()).project_hash() == (
        GOLDEN_HASH
    )


def test_a_pixel_run_writes_no_native_keys(tmp_path: Path) -> None:
    manifest = build_scene(tmp_path / "data").model_copy(
        update={"mode": ProjectMode(), "view_pairs": []}
    )
    out = tmp_path / "out"
    Engine(manifest).run(out, exporters=["csv_long", "readme"])
    for path in out.rglob("manifest.json"):
        text = path.read_text(encoding="utf-8")
        assert "water_column" not in json.loads(text)["calibration"]
        for unit in json.loads(text).get("run_metadata", {}).get("session_provenance", {}).values():
            assert "native_3d" not in unit if isinstance(unit, dict) else True
        assert '"native_3d"' not in text

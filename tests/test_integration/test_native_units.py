"""A tracker with no pixel frame, through the real pipeline and out the other side.

The pipeline's arithmetic does not care what a length is measured in; what must not happen is a
distance in a tool's own units exported under a ``_px`` header, or a tool's unit label believed
without anyone confirming it. These tests drive a toy tracker that reports no pixel frame
(tests/support/toy_reader.py) through every exporter and read back what it wrote.
"""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from tests.support.toy_reader import NATIVE_OPTIONS, OPTIONS
from track2data.api import Engine
from track2data.core.models import (
    CalibrationConfig,
    MetricSelection,
    ProjectManifest,
    SessionRef,
)

PIXEL_COLUMNS = ("_px", "_px_s", "_px_s2", "_px2")
METRICS = MetricSelection(individual=["IL-1", "IL-2", "IL-4"], group=[], zone=[], diagnostic=[])


def _engine(folder: Path, *, native: bool, **calibration: Any) -> Engine:
    now = datetime.now(tz=UTC)
    return Engine(
        ProjectManifest(
            project_name="units",
            created_at=now,
            updated_at=now,
            sessions=[
                SessionRef(
                    session_id="trial1",
                    folder=folder,
                    sha256="",
                    reader="toy_native" if native else "toy_csv",
                    reader_options=dict(NATIVE_OPTIONS if native else OPTIONS),
                    reader_chosen_by="user",
                    reader_confidence="HIGH",
                )
            ],
            calibration=CalibrationConfig(**(calibration or {"mode": "bodylength"})),
            metrics=METRICS,
        )
    )


def _run(engine: Engine, tmp_path: Path) -> Path:
    result = engine.run(tmp_path / "out", exporters=["csv_long", "readme"])
    assert [r.error for r in result.sessions] == [None]
    return tmp_path / "out"


def _headers(path: Path) -> list[str]:
    with open(path, newline="", encoding="utf-8") as handle:
        return next(csv.reader(handle))


def _length_columns(out: Path) -> set[str]:
    columns: set[str] = set()
    for name in ("master_fish_by_frame.csv", "trial_activity_summary.csv"):
        columns |= set(_headers(out / "trial1" / name))
    return columns


class TestWithNoPixelFrame:
    def test_nothing_is_exported_under_a_pixel_name(
        self, toy_native_reader: None, toy_folder: Path, tmp_path: Path
    ) -> None:
        out = _run(_engine(toy_folder, native=True), tmp_path)
        columns = _length_columns(out)
        assert not [c for c in columns if c.endswith(PIXEL_COLUMNS)]
        assert {"x_tu", "y_tu", "speed_tu_s"} <= columns

    def test_the_long_table_and_the_codebook_use_the_same_names_and_say_tool_units(
        self, toy_native_reader: None, toy_folder: Path, tmp_path: Path
    ) -> None:
        out = _run(_engine(toy_folder, native=True), tmp_path)
        long = pd.read_csv(out / "trial1" / "metrics_long.csv")
        lengths = long[long["column"].str.contains(r"_tu(?:_s2?|2)?$", regex=True)]
        assert not lengths.empty and all("tool units" in u for u in lengths["unit"])
        assert not long["column"].str.endswith(PIXEL_COLUMNS).any()
        book = pd.read_csv(out / "codebook.csv")
        assert not book["column"].str.endswith(PIXEL_COLUMNS).any()
        assert set(lengths["column"]) <= set(book["column"])

    def test_no_calibrated_columns_appear_without_a_scale(
        self, toy_native_reader: None, toy_folder: Path, tmp_path: Path
    ) -> None:
        out = _run(_engine(toy_folder, native=True), tmp_path)
        summary = pd.read_csv(out / "trial1" / "trial_activity_summary.csv")
        frame = pd.read_csv(out / "trial1" / "master_fish_by_frame.csv")
        calibrated = [c for c in summary.columns if c.endswith(("_cm", "_cm_s"))]
        assert summary[calibrated].isna().all().all()  # columns exist, as for any uncalibrated run
        assert not [c for c in frame.columns if c.endswith(("_cm", "_cm_s"))]

    def test_the_readme_says_what_the_numbers_are_and_that_the_label_is_unconfirmed(
        self, toy_native_reader: None, toy_folder: Path, tmp_path: Path
    ) -> None:
        out = _run(_engine(toy_folder, native=True), tmp_path)
        text = (out / "trial1" / "README.md").read_text("utf-8")
        row = next(line for line in text.splitlines() if line.startswith("| Coordinate unit"))
        assert "tool units" in row and "'mm'" in row and "not confirmed" in row

    def test_the_manifest_json_records_it(
        self, toy_native_reader: None, toy_folder: Path, tmp_path: Path
    ) -> None:
        out = _run(_engine(toy_folder, native=True), tmp_path)
        prov = json.loads((out / "trial1" / "manifest.json").read_text("utf-8"))["run_metadata"][
            "session_provenance"
        ]
        assert prov["coordinate_unit"] == "tu" and prov["coordinate_unit_reported"] == "mm"
        assert prov["coordinate_unit_confirmed"] is False

    def test_the_values_are_exactly_what_a_pixel_project_computes_from_the_same_numbers(
        self, toy_native_reader: None, toy_reader: None, toy_folder: Path, tmp_path: Path
    ) -> None:
        native = _run(_engine(toy_folder, native=True), tmp_path / "native")
        pixel = _run(_engine(toy_folder, native=False), tmp_path / "pixel")
        a = pd.read_csv(native / "trial1" / "master_fish_by_frame.csv")
        b = pd.read_csv(pixel / "trial1" / "master_fish_by_frame.csv")
        assert list(a.columns) == [c.replace("_px", "_tu") for c in b.columns]
        a.columns = list(b.columns)
        pd.testing.assert_frame_equal(a, b, check_dtype=False)


class TestOnceSomeoneConfirmsTheUnit:
    def confirmed(self, toy_folder: Path, label: str = "mm", **extra: Any) -> Engine:
        return _engine(
            toy_folder,
            native=True,
            mode="bodylength",
            length_unit_label=label,
            length_unit_confirmed_by_user=True,
            **extra,
        )

    def test_the_columns_take_the_confirmed_unit(
        self, toy_native_reader: None, toy_folder: Path, tmp_path: Path
    ) -> None:
        out = _run(self.confirmed(toy_folder), tmp_path)
        columns = _length_columns(out)
        assert {"x_mm", "y_mm", "speed_mm_s"} <= columns
        assert not [c for c in columns if c.endswith(PIXEL_COLUMNS) or "_tu" in c]

    def test_a_known_physical_unit_also_gets_centimetre_columns(
        self, toy_native_reader: None, toy_folder: Path, tmp_path: Path
    ) -> None:
        out = _run(self.confirmed(toy_folder), tmp_path)
        frame = pd.read_csv(out / "trial1" / "master_fish_by_frame.csv")
        assert np.allclose(frame["x_cm"], frame["x_mm"] / 10.0, equal_nan=True)
        assert np.allclose(frame["speed_cm_s"], frame["speed_mm_s"] / 10.0, equal_nan=True)
        assert frame["x_cm"].notna().any()

    def test_the_readme_says_it_was_confirmed(
        self, toy_native_reader: None, toy_folder: Path, tmp_path: Path
    ) -> None:
        out = _run(self.confirmed(toy_folder), tmp_path)
        text = (out / "trial1" / "README.md").read_text("utf-8")
        row = next(line for line in text.splitlines() if line.startswith("| Coordinate unit"))
        assert "mm" in row and "confirmed by user" in row and "not confirmed" not in row

    def test_a_unit_that_is_already_centimetres_adds_no_second_cm_family(
        self, toy_native_reader: None, toy_folder: Path, tmp_path: Path
    ) -> None:
        out = _run(self.confirmed(toy_folder, "cm"), tmp_path)
        columns = list(_headers(out / "trial1" / "master_fish_by_frame.csv"))
        assert "x_cm" in columns and len(columns) == len(set(columns))

    def test_a_label_that_collides_with_another_family_is_not_believed(
        self, toy_native_reader: None, toy_folder: Path, tmp_path: Path
    ) -> None:
        out = _run(self.confirmed(toy_folder, "bl"), tmp_path)
        assert {"x_tu", "speed_tu_s"} <= _length_columns(out)

    def test_an_unknown_but_safe_label_is_used_but_gets_no_centimetres(
        self, toy_native_reader: None, toy_folder: Path, tmp_path: Path
    ) -> None:
        out = _run(self.confirmed(toy_folder, "furlong"), tmp_path)
        columns = _length_columns(out)
        assert "x_furlong" in columns and "x_cm" not in columns


class TestAPixelProjectIsUntouched:
    def test_it_still_exports_pixel_names_and_says_pixels(
        self, toy_reader: None, toy_folder: Path, tmp_path: Path
    ) -> None:
        out = _run(_engine(toy_folder, native=False), tmp_path)
        columns = _length_columns(out)
        assert {"x_px", "y_px", "speed_px_s"} <= columns
        assert not [c for c in columns if c.endswith(("_tu", "_tu_s", "_mm"))]
        text = (out / "trial1" / "README.md").read_text("utf-8")
        row = next(line for line in text.splitlines() if line.startswith("| Coordinate unit"))
        assert "px" in row and "pixel" in row.lower()


def _project(
    folders: dict[str, tuple[Path, str]],
    *,
    metrics: MetricSelection | None = None,
    zones: Any = None,
    reported: dict[str, str] | None = None,
    **calibration: Any,
) -> Engine:
    """A project of several sessions: ``{session_id: (folder, "native" | "pixel")}``."""
    now = datetime.now(tz=UTC)
    refs = []
    for sid, (folder, kind) in folders.items():
        options = dict(NATIVE_OPTIONS if kind == "native" else OPTIONS)
        if kind == "native" and reported and sid in reported:
            options["reported_unit"] = reported[sid]
        refs.append(
            SessionRef(
                session_id=sid,
                folder=folder,
                sha256="",
                reader="toy_native" if kind == "native" else "toy_csv",
                reader_options=options,
                reader_chosen_by="user",
                reader_confidence="HIGH",
            )
        )
    fields: dict[str, Any] = {
        "project_name": "units",
        "created_at": now,
        "updated_at": now,
        "sessions": refs,
        "calibration": CalibrationConfig(**(calibration or {"mode": "bodylength"})),
        "metrics": metrics or METRICS,
    }
    if zones is not None:
        fields["zones"] = zones
    return Engine(ProjectManifest(**fields))


@pytest.fixture
def two_folders(tmp_path: Path) -> tuple[Path, Path]:
    from tests.support.toy_reader import write_toy_session

    return write_toy_session(tmp_path / "a", seed=1), write_toy_session(tmp_path / "b", seed=2)


class TestPreflight:
    def test_a_pixel_project_has_nothing_to_say_about_units(
        self, toy_reader: None, two_folders: tuple[Path, Path]
    ) -> None:
        a, b = two_folders
        assert _project({"a": (a, "pixel"), "b": (b, "pixel")}).validate() == []

    def test_a_project_of_native_sessions_alone_is_fine(
        self, toy_native_reader: None, two_folders: tuple[Path, Path]
    ) -> None:
        a, b = two_folders
        assert _project({"a": (a, "native"), "b": (b, "native")}).validate() == []

    def test_pixels_and_tool_units_cannot_share_a_project(
        self, toy_reader: None, toy_native_reader: None, two_folders: tuple[Path, Path]
    ) -> None:
        a, b = two_folders
        issues = _project({"a": (a, "pixel"), "b": (b, "native")}).validate()
        assert len(issues) == 1
        assert "different length units" in issues[0] and "a" in issues[0] and "b" in issues[0]
        assert "px" in issues[0] and "tool units" in issues[0]

    def test_tool_units_the_tools_name_differently_cannot_share_a_project(
        self, toy_native_reader: None, two_folders: tuple[Path, Path]
    ) -> None:
        a, b = two_folders
        issues = _project(
            {"a": (a, "native"), "b": (b, "native")}, reported={"a": "mm", "b": "um"}
        ).validate()
        assert len(issues) == 1 and "'mm'" in issues[0] and "'um'" in issues[0]

    def test_confirming_the_unit_makes_them_one_unit(
        self, toy_native_reader: None, two_folders: tuple[Path, Path]
    ) -> None:
        a, b = two_folders
        issues = _project(
            {"a": (a, "native"), "b": (b, "native")},
            reported={"a": "mm", "b": "um"},
            mode="bodylength",
            length_unit_label="mm",
            length_unit_confirmed_by_user=True,
        ).validate()
        assert issues == []

    def test_zones_cannot_apply_to_sessions_with_no_pixel_frame(
        self, toy_native_reader: None, two_folders: tuple[Path, Path]
    ) -> None:
        from track2data.core.models import ROI, ZoneSet

        a, _ = two_folders
        zones = ZoneSet(rois=[ROI(name="arena", vertices=[(0, 0), (10, 0), (10, 10)])])
        issues = _project({"a": (a, "native")}, zones=zones).validate()
        assert len(issues) == 1 and "zones" in issues[0].lower() and "a" in issues[0]

    def test_a_metric_whose_default_is_in_pixels_must_be_told_its_scale(
        self, toy_native_reader: None, two_folders: tuple[Path, Path]
    ) -> None:
        a, _ = two_folders
        sel = MetricSelection(individual=["IL-9", "IL-14"], group=["GL-13"], zone=[], diagnostic=[])
        issues = _project({"a": (a, "native")}, metrics=sel).validate()
        text = " ".join(issues)
        for needed in ("IL-9", "bin_size_px", "IL-14", "wall_contact_threshold_px", "GL-13"):
            assert needed in text

    def test_setting_the_value_explicitly_clears_it(
        self, toy_native_reader: None, two_folders: tuple[Path, Path]
    ) -> None:
        a, _ = two_folders
        sel = MetricSelection(
            individual=["IL-9"],
            group=[],
            zone=[],
            diagnostic=[],
            config={"IL-9": {"bin_size_px": 5.0}},
        )
        assert _project({"a": (a, "native")}, metrics=sel).validate() == []

    def test_a_metric_that_works_out_its_own_scale_is_not_in_the_way(
        self, toy_native_reader: None, two_folders: tuple[Path, Path]
    ) -> None:
        a, _ = two_folders
        sel = MetricSelection(
            individual=["IL-4"], group=["GL-3", "GL-8"], zone=[], diagnostic=[]
        )  # auto threshold; scale-free numerical-zero tolerances
        assert _project({"a": (a, "native")}, metrics=sel).validate() == []

    def test_the_same_metrics_are_fine_in_a_pixel_project(
        self, toy_reader: None, two_folders: tuple[Path, Path]
    ) -> None:
        a, _ = two_folders
        sel = MetricSelection(individual=["IL-9", "IL-14"], group=["GL-13"], zone=[], diagnostic=[])
        assert _project({"a": (a, "pixel")}, metrics=sel).validate() == []

    def test_a_scale_in_a_project_already_in_centimetres_is_refused(
        self, toy_native_reader: None, two_folders: tuple[Path, Path]
    ) -> None:
        a, _ = two_folders
        issues = _project(
            {"a": (a, "native")},
            mode="scalar",
            px_per_cm=1.0,
            length_unit_label="cm",
            length_unit_confirmed_by_user=True,
        ).validate()
        assert len(issues) == 1 and "centimetres" in issues[0]


class TestTheSensitivitySweep:
    """The sweep recomputes metrics outside the export, so it must name lengths the same way."""

    def test_a_native_session_is_swept_under_its_own_unit_names(
        self, toy_native_reader: None, toy_folder: Path
    ) -> None:
        from track2data.sensitivity import SensitivityGrid, run_sensitivity

        engine = _engine(toy_folder, native=True)
        session = engine.import_ref(engine.manifest.sessions[0])
        grid = SensitivityGrid(smoothing_windows=[0, 5], max_gap_frames=[0], metric_ids=["IL-1"])
        sweep = run_sensitivity(engine, session, grid)
        lengths = sweep[sweep["column"].astype(str).str.contains(r"_tu(?:_s2?|2)?$", regex=True)]
        assert not lengths.empty and set(lengths["unit"]) <= {"tool units", "tool units/s"}
        assert not sweep["column"].astype(str).str.endswith(PIXEL_COLUMNS).any()

    def test_a_pixel_session_is_swept_as_before(self, toy_reader: None, toy_folder: Path) -> None:
        from track2data.sensitivity import SensitivityGrid, run_sensitivity

        engine = _engine(toy_folder, native=False)
        session = engine.import_ref(engine.manifest.sessions[0])
        grid = SensitivityGrid(smoothing_windows=[0, 5], max_gap_frames=[0], metric_ids=["IL-1"])
        sweep = run_sensitivity(engine, session, grid)
        assert "px" in set(sweep["unit"].dropna())


class TestDefenceInDepth:
    """Things the pre-flight already prevents, which the pipeline must also be safe against."""

    def test_zones_are_not_assigned_to_positions_that_are_not_in_the_frame(
        self, toy_native_reader: None, two_folders: tuple[Path, Path]
    ) -> None:
        from track2data.core.models import ROI, ZoneSet

        a, _ = two_folders
        zones = ZoneSet(
            rois=[
                ROI(name="arena", level="main", vertices=[(0, 0), (500, 0), (500, 500), (0, 500)])
            ]
        )
        engine = _project({"a": (a, "native")}, zones=zones)
        psess = engine.preprocess_ref(engine.manifest.sessions[0])
        assert psess.main_zone is None  # even though the numbers fall inside the polygon

    def test_a_pixel_session_still_gets_its_zones(
        self, toy_reader: None, two_folders: tuple[Path, Path]
    ) -> None:
        from track2data.core.models import ROI, ZoneSet

        a, _ = two_folders
        zones = ZoneSet(
            rois=[
                ROI(name="arena", level="main", vertices=[(0, 0), (500, 0), (500, 500), (0, 500)])
            ]
        )
        engine = _project({"a": (a, "pixel")}, zones=zones)
        assert engine.preprocess_ref(engine.manifest.sessions[0]).main_zone is not None

    def test_a_derived_parameter_is_never_asked_for(
        self,
        toy_native_reader: None,
        two_folders: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import track2data.metrics as registry
        from track2data.metrics.base import MetricParameter

        a, _ = two_folders
        derived = MetricParameter(
            name="bin_size_px", label="x", kind="float", unit="px", default=20.0, derived=True
        )
        monkeypatch.setattr(registry.get("IL-9"), "parameters", [derived])
        sel = MetricSelection(individual=["IL-9"], group=[], zone=[], diagnostic=[])
        assert _project({"a": (a, "native")}, metrics=sel).validate() == []

    def test_a_pixel_project_does_not_open_a_single_session_to_check_its_units(
        self,
        toy_reader: None,
        two_folders: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        a, b = two_folders

        original = Engine.import_ref
        opened: list[str] = []

        def recording(self: Engine, ref: Any) -> Any:
            opened.append(ref.session_id)
            return original(self, ref)

        monkeypatch.setattr(Engine, "import_ref", recording)
        assert _project({"a": (a, "pixel"), "b": (b, "pixel")}).validate() == []
        assert opened == []  # a pixel reader is pixels by declaration: nothing to open


class TestThePreflightReportKnowsTheConfirmedUnit:
    def test_an_unconfirmed_unit_is_reported(
        self, toy_native_reader: None, two_folders: tuple[Path, Path]
    ) -> None:
        a, _ = two_folders
        warnings = _project({"a": (a, "native")}).consistency_warnings()
        assert any("the tool's own units" in w and "*_tu" in w for w in warnings)

    def test_a_confirmed_unit_is_not(
        self, toy_native_reader: None, two_folders: tuple[Path, Path]
    ) -> None:
        a, _ = two_folders
        engine = _project(
            {"a": (a, "native")},
            mode="bodylength",
            length_unit_label="mm",
            length_unit_confirmed_by_user=True,
        )
        assert not any("the tool's own units" in w for w in engine.consistency_warnings())

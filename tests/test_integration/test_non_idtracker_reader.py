"""A tracker other than idtracker.ai, through the real pipeline, from saved reader to README.

A toy reader stands in for the real ones that arrive in later tiers. What is checked here is
everything that is *not* specific to a tracker: the saved reader and options are replayed, the
manifest id is used, D-5 does not call a tracker without identification quality "weak", and the
export says which software and reader produced the numbers and whether that reader was verified.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import pandas as pd
import pytest

from track2data import readers
from track2data.api import Engine
from track2data.core.models import (
    CalibrationConfig,
    MetricSelection,
    ProjectManifest,
    Session,
    SessionRef,
    VideoInfo,
)
from track2data.readers.base import SessionReader
from track2data.readers.params import ReaderParameter

OPTIONS = {"fps": 25.0, "width_px": 100, "height_px": 80}


class ToyCsvReader(SessionReader):
    """Reads ``toy.csv`` (frame, id, x, y). Records nothing in the file about fps or frame size."""

    name = "toy_csv"
    display_name: ClassVar[str] = "Toy tracker"
    verification = "synthetic_only"
    parameters: ClassVar[tuple[ReaderParameter, ...]] = (
        ReaderParameter(name="fps", label="Frame rate", kind="float", required=True),
        ReaderParameter(name="width_px", label="Frame width", kind="int", required=True),
        ReaderParameter(name="height_px", label="Frame height", kind="int", required=True),
    )

    @classmethod
    def detect(cls, folder: Path) -> bool:
        return (folder / "toy.csv").exists()

    def read(self, folder: Path, *, allow_pickle: bool = False, options: Any = None) -> Session:
        table = pd.read_csv(folder / "toy.csv")
        ids = sorted(table["id"].unique())
        n_frames = int(table["frame"].max()) + 1
        xy = np.full((n_frames, len(ids), 2), np.nan)
        for column, animal in enumerate(ids):
            rows = table[table["id"] == animal]
            xy[rows["frame"].to_numpy(), column, 0] = rows["x"].to_numpy()
            xy[rows["frame"].to_numpy(), column, 1] = rows["y"].to_numpy()
        return Session(
            session_id="derived-by-the-reader",
            folder=folder,
            reader=self.name,
            video=VideoInfo(
                path=None,
                fps=options["fps"],
                n_frames=n_frames,
                width_px=options["width_px"],
                height_px=options["height_px"],
            ),
            n_animals=len(ids),
            trajectory_variant="with_gaps",
            has_stable_identities=True,
            raw_xy=xy,
            trajectory_source=folder / "toy.csv",
        )


@pytest.fixture
def toy_reader() -> Iterator[None]:
    readers.register(ToyCsvReader)
    yield
    readers._REGISTRY.remove(ToyCsvReader)


@pytest.fixture
def toy_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "trial1"
    folder.mkdir()
    rng = np.random.default_rng(0)
    rows = []
    for animal in (0, 1):
        position = rng.uniform(20, 60, size=2)
        for frame in range(60):
            position = position + rng.normal(0, 1.5, size=2)
            rows.append((frame, animal, *position))
    pd.DataFrame(rows, columns=["frame", "id", "x", "y"]).to_csv(folder / "toy.csv", index=False)
    return folder


def _engine(
    folder: Path, *, calibration: CalibrationConfig | None = None, **ref_fields: Any
) -> Engine:
    now = datetime.now(tz=UTC)
    fields: dict[str, Any] = {
        "reader": "toy_csv",
        "reader_options": OPTIONS,
        "reader_chosen_by": "user",
        "reader_confidence": "HIGH",
    }
    fields.update(ref_fields)
    return Engine(
        ProjectManifest(
            project_name="toy",
            created_at=now,
            updated_at=now,
            sessions=[SessionRef(session_id="trial1", folder=folder, sha256="", **fields)],
            calibration=calibration or CalibrationConfig(mode="scalar", px_per_cm=10.0),
            metrics=MetricSelection(individual=["IL-1"], group=[], zone=[], diagnostic=[]),
        )
    )


def _run(engine: Engine, out: Path) -> Path:
    result = engine.run(out, exporters=["csv_long", "readme"])
    assert [r.error for r in result.sessions] == [None]
    return out / "trial1"


def test_the_project_runs_end_to_end_with_the_saved_reader(
    toy_reader: None, toy_folder: Path, tmp_path: Path
) -> None:
    engine = _engine(toy_folder)
    assert engine.validate() == []
    out = _run(engine, tmp_path / "out")
    assert (out / "README.md").exists()
    assert any(out.glob("*.csv"))


def test_diagnostic_d5_is_not_assessed_for_a_tracker_without_identification_quality(
    toy_reader: None, toy_folder: Path, tmp_path: Path
) -> None:
    result = _engine(toy_folder).run(tmp_path / "out", exporters=["csv_long"])
    d5 = result.sessions[0].diagnostics["D-5"]
    assert d5["identity_stability_status"].iloc[0] == "not_assessed"


class TestTheReadmeNamesTheSourceSoftware:
    def test_it_says_which_software_and_reader_produced_the_numbers(
        self, toy_reader: None, toy_folder: Path, tmp_path: Path
    ) -> None:
        text = (_run(_engine(toy_folder), tmp_path / "out") / "README.md").read_text("utf-8")
        assert "## Source software provenance" in text
        assert "| Software | Toy tracker |" in text
        assert "| Reader | toy_csv |" in text

    def test_it_does_not_pretend_the_session_came_from_idtracker(
        self, toy_reader: None, toy_folder: Path, tmp_path: Path
    ) -> None:
        text = (_run(_engine(toy_folder), tmp_path / "out") / "README.md").read_text("utf-8")
        assert "## idtracker.ai provenance" not in text
        assert "idtracker.ai version" not in text
        assert "Body-length reliability" not in text

    def test_an_unverified_reader_says_so(
        self, toy_reader: None, toy_folder: Path, tmp_path: Path
    ) -> None:
        text = (_run(_engine(toy_folder), tmp_path / "out") / "README.md").read_text("utf-8")
        assert "**unverified**" in text

    def test_a_reader_tested_on_real_output_says_that_instead(
        self, toy_reader: None, toy_folder: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(ToyCsvReader, "verification", "real_sample")
        text = (_run(_engine(toy_folder), tmp_path / "out") / "README.md").read_text("utf-8")
        assert "tested against real tracker output" in text
        assert "**unverified**" not in text

    def test_it_lists_the_options_and_who_chose_the_reader(
        self, toy_reader: None, toy_folder: Path, tmp_path: Path
    ) -> None:
        text = (_run(_engine(toy_folder), tmp_path / "out") / "README.md").read_text("utf-8")
        assert "fps=25.0" in text
        assert "width_px=100" in text
        assert "chosen by the user" in text
        assert "confidence HIGH" in text

    def test_it_names_the_source_file(
        self, toy_reader: None, toy_folder: Path, tmp_path: Path
    ) -> None:
        text = (_run(_engine(toy_folder), tmp_path / "out") / "README.md").read_text("utf-8")
        assert "`toy.csv`" in text

    def test_the_calibration_rows_are_still_there(
        self, toy_reader: None, toy_folder: Path, tmp_path: Path
    ) -> None:
        text = (_run(_engine(toy_folder), tmp_path / "out") / "README.md").read_text("utf-8")
        assert "Length calibration factor" in text


def test_the_manifest_json_carries_the_same_facts(
    toy_reader: None, toy_folder: Path, tmp_path: Path
) -> None:
    out = _run(_engine(toy_folder), tmp_path / "out")
    prov = json.loads((out / "manifest.json").read_text("utf-8"))["run_metadata"][
        "session_provenance"
    ]
    assert prov["reader"] == "toy_csv"
    assert prov["source_software"] == "Toy tracker"
    assert prov["reader_verification"] == "synthetic_only"
    assert prov["reader_options"] == OPTIONS
    assert prov["reader_chosen_by"] == "user"
    assert prov["detection_confidence"] == "HIGH"
    assert prov["source_files"][0].endswith("toy.csv")


class TestAdvisories:
    def test_an_unverified_reader_is_reported_before_the_run_and_does_not_block_it(
        self, toy_reader: None, toy_folder: Path
    ) -> None:
        engine = _engine(toy_folder)
        warnings = engine.consistency_warnings()
        assert any("toy_csv" in w and "real tracker output" in w for w in warnings)
        assert engine.validate() == []

    def test_a_reader_tested_on_real_output_is_not_reported(
        self, toy_reader: None, toy_folder: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(ToyCsvReader, "verification", "real_sample")
        assert _engine(toy_folder).consistency_warnings() == []

    def test_body_length_calibration_is_flagged_for_a_tracker_that_reports_none(
        self, toy_reader: None, toy_folder: Path
    ) -> None:
        engine = _engine(toy_folder, calibration=CalibrationConfig(mode="bodylength"))
        warnings = [w for w in engine.consistency_warnings() if "body length" in w]
        assert len(warnings) == 1
        assert "trial1" in warnings[0]
        assert engine.validate() == []

    def test_the_run_still_finishes_in_pixels_when_body_length_is_missing(
        self, toy_reader: None, toy_folder: Path, tmp_path: Path
    ) -> None:
        engine = _engine(toy_folder, calibration=CalibrationConfig(mode="bodylength"))
        assert _run(engine, tmp_path / "out").is_dir()

    def test_the_project_summary_carries_the_notes_too(
        self, toy_reader: None, toy_folder: Path, tmp_path: Path
    ) -> None:
        _run(_engine(toy_folder), tmp_path / "out")
        text = (tmp_path / "out" / "PROJECT_SUMMARY.md").read_text("utf-8")
        assert "## Notes on the readers" in text
        assert "toy_csv" in text.split("## Notes on the readers")[1]

    def test_a_project_with_nothing_to_note_has_no_such_section(
        self, toy_reader: None, toy_folder: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(ToyCsvReader, "verification", "real_sample")
        _run(_engine(toy_folder), tmp_path / "out")
        text = (tmp_path / "out" / "PROJECT_SUMMARY.md").read_text("utf-8")
        assert "## Notes on the readers" not in text

    def test_the_notes_are_not_mistaken_for_a_reason_not_to_pool_sessions(
        self, toy_reader: None, toy_folder: Path, tmp_path: Path
    ) -> None:
        _run(_engine(toy_folder), tmp_path / "out")
        text = (tmp_path / "out" / "PROJECT_SUMMARY.md").read_text("utf-8")
        assert "## Read before pooling these sessions" not in text
        assert "## Session consistency" in text

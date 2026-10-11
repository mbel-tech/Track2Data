"""Tests for ReadmeExporter and ExcelExporter — TDD RED."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from track2data.core.models import PreprocessReport
from track2data.exporters.base import ExportPayload
from track2data.exporters.readme import ReadmeExporter

# ── shared fixture ─────────────────────────────────────────────────────────────


@pytest.fixture()
def minimal_payload() -> ExportPayload:
    fish_df = pd.DataFrame(
        {
            "session_id": ["s1", "s1"],
            "individual_id": [0, 1],
            "frame": [0, 0],
            "x": [1.0, 2.0],
            "y": [3.0, 4.0],
        }
    )
    return ExportPayload(
        session_id="s1",
        project_name="MyProject",
        project_hash="1234567890abcdef",
        app_version="0.1.0",
        fish_by_frame=fish_df,
        individual_metrics={
            "IL-1": pd.DataFrame({"session_id": ["s1"], "individual_id": [0], "val": [1.0]})
        },
        group_metrics={"GL-1": pd.DataFrame({"session_id": ["s1"], "metric": [2.0]})},
        zone_metrics={
            "Z-1": pd.DataFrame({"session_id": ["s1"], "zone_name": ["A"], "time_s": [1.0]})
        },
        diagnostic_metrics={},
        preprocess_report=PreprocessReport(),
        manifest_json=json.dumps({"schema_version": 1, "project_name": "MyProject"}),
    )


# ── ReadmeExporter ────────────────────────────────────────────────────────────


class TestReadmeExporter:
    def test_exporter_name(self) -> None:
        assert ReadmeExporter.name == "readme"

    def test_exporter_extension(self) -> None:
        assert ReadmeExporter.file_extension == ".md"

    def test_writes_readme_md(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        exporter = ReadmeExporter()
        paths = exporter.write(minimal_payload, tmp_path)
        assert any(p.name == "README.md" for p in paths)

    def test_readme_exists_on_disk(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        exporter = ReadmeExporter()
        exporter.write(minimal_payload, tmp_path)
        assert (tmp_path / "README.md").exists()

    def test_readme_contains_project_name(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        exporter = ReadmeExporter()
        exporter.write(minimal_payload, tmp_path)
        content = (tmp_path / "README.md").read_text(encoding="utf-8")
        assert "MyProject" in content

    def test_readme_contains_app_version(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        exporter = ReadmeExporter()
        exporter.write(minimal_payload, tmp_path)
        content = (tmp_path / "README.md").read_text(encoding="utf-8")
        assert "0.1.0" in content

    def test_readme_contains_project_hash(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        exporter = ReadmeExporter()
        exporter.write(minimal_payload, tmp_path)
        content = (tmp_path / "README.md").read_text(encoding="utf-8")
        assert "1234567890abcdef" in content

    def test_readme_contains_metric_ids(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        exporter = ReadmeExporter()
        exporter.write(minimal_payload, tmp_path)
        content = (tmp_path / "README.md").read_text(encoding="utf-8")
        assert "IL-1" in content
        assert "GL-1" in content

    def test_writes_manifest_json(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        exporter = ReadmeExporter()
        paths = exporter.write(minimal_payload, tmp_path)
        assert any(p.name == "manifest.json" for p in paths)

    def test_manifest_json_exists_on_disk(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        exporter = ReadmeExporter()
        exporter.write(minimal_payload, tmp_path)
        assert (tmp_path / "manifest.json").exists()

    def test_manifest_json_is_valid_json(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        exporter = ReadmeExporter()
        exporter.write(minimal_payload, tmp_path)
        text = (tmp_path / "manifest.json").read_text(encoding="utf-8")
        data = json.loads(text)
        assert isinstance(data, dict)

    def test_manifest_contains_project_name(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        exporter = ReadmeExporter()
        exporter.write(minimal_payload, tmp_path)
        data = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
        assert data.get("project_name") == "MyProject"

    def test_returns_two_paths(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        exporter = ReadmeExporter()
        paths = exporter.write(minimal_payload, tmp_path)
        assert len(paths) == 2

    def test_all_paths_exist(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        exporter = ReadmeExporter()
        paths = exporter.write(minimal_payload, tmp_path)
        for p in paths:
            assert p.exists(), f"{p} does not exist"


# ── SessionProvenance rendering ─────────────────────────────────────────────
#
# Regression coverage: ExportPayload carried no reference to Session at all,
# so no idtracker.ai value could reach the README even in principle -- it
# listed only metric *IDs* (e.g. "D-2"), never the estimated_accuracy value
# that metric actually reports.


@pytest.fixture()
def provenance_payload(minimal_payload: ExportPayload) -> ExportPayload:
    from dataclasses import replace

    from track2data.exporters.base import SessionProvenance

    prov = SessionProvenance(
        reader="idtrackerai",
        idtrackerai_version="6.0.13",
        trajectory_format="h5",
        trajectory_variant="with_gaps",
        n_frames=14911,
        n_animals=4,
        has_stable_identities=True,
        tracking_status="Success",
        tracking_warnings_count=13,
        estimated_accuracy=0.751957740605162,
        fraction_identified=0.822446515994903,
        silhouette_score=0.7805799245834351,
        fragment_connectivity=1.3401015228426396,
        length_unit=8.95425,
        body_length_reliable=False,
    )
    return replace(minimal_payload, provenance=prov)


class TestReadmeProvenanceSection:
    def test_idtrackerai_version_in_readme(
        self, tmp_path: Path, provenance_payload: ExportPayload
    ) -> None:
        ReadmeExporter().write(provenance_payload, tmp_path)
        content = (tmp_path / "README.md").read_text(encoding="utf-8")
        assert "6.0.13" in content

    def test_trajectory_format_in_readme(
        self, tmp_path: Path, provenance_payload: ExportPayload
    ) -> None:
        ReadmeExporter().write(provenance_payload, tmp_path)
        content = (tmp_path / "README.md").read_text(encoding="utf-8")
        assert "| Trajectory format read | h5 |" in content

    def test_quality_values_in_readme_not_just_metric_ids(
        self, tmp_path: Path, provenance_payload: ExportPayload
    ) -> None:
        """The whole point: actual values, not just the D-2/D-3 IDs."""
        ReadmeExporter().write(provenance_payload, tmp_path)
        content = (tmp_path / "README.md").read_text(encoding="utf-8")
        assert "0.7520" in content  # estimated_accuracy
        assert "0.8224" in content  # fraction_identified

    def test_calibration_unit_caveat_present_when_calibrated(
        self, tmp_path: Path, provenance_payload: ExportPayload
    ) -> None:
        ReadmeExporter().write(provenance_payload, tmp_path)
        content = (tmp_path / "README.md").read_text(encoding="utf-8")
        assert "8.95425" in content
        assert "not confirmed" in content

    def test_calibration_unit_confirmed_shows_no_caveat_warning(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        from dataclasses import replace

        from track2data.exporters.base import SessionProvenance

        prov = SessionProvenance(
            length_unit=10.0,
            length_unit_label="mm",
            length_unit_confirmed_by_user=True,
        )
        payload = replace(minimal_payload, provenance=prov)
        ReadmeExporter().write(payload, tmp_path)
        content = (tmp_path / "README.md").read_text(encoding="utf-8")
        assert "px per mm" in content
        assert "confirmed by user" in content
        assert "not confirmed" not in content

    def test_not_calibrated_shown_when_length_unit_none(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        ReadmeExporter().write(minimal_payload, tmp_path)
        content = (tmp_path / "README.md").read_text(encoding="utf-8")
        assert "*(not calibrated)*" in content

    def test_body_length_reliability_caveat_present(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        ReadmeExporter().write(minimal_payload, tmp_path)
        content = (tmp_path / "README.md").read_text(encoding="utf-8")
        assert "not** acknowledged reliable" in content

    def test_failed_tracking_status_shows_failure_summary(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        from dataclasses import replace

        from track2data.exporters.base import SessionProvenance

        prov = SessionProvenance(
            tracking_status="Failed",
            tracking_failure_summary="OSError: [Errno 24] Too many open files",
        )
        payload = replace(minimal_payload, provenance=prov)
        ReadmeExporter().write(payload, tmp_path)
        content = (tmp_path / "README.md").read_text(encoding="utf-8")
        assert "Tracking failure" in content
        assert "Too many open files" in content

    def test_missing_quality_values_render_as_not_reported(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        ReadmeExporter().write(minimal_payload, tmp_path)
        content = (tmp_path / "README.md").read_text(encoding="utf-8")
        assert "*(not reported)*" in content

    def test_session_provenance_in_manifest_json(
        self, tmp_path: Path, provenance_payload: ExportPayload
    ) -> None:
        ReadmeExporter().write(provenance_payload, tmp_path)
        manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
        prov = manifest["run_metadata"]["session_provenance"]
        assert prov["idtrackerai_version"] == "6.0.13"
        assert prov["estimated_accuracy"] == pytest.approx(0.751957740605162)


class TestReadmeValidatorProvenance:
    def test_last_validated_data_policy_and_calibration_spread(
        self, tmp_path: Path, provenance_payload: ExportPayload
    ) -> None:
        from dataclasses import replace

        prov = replace(
            provenance_payload.provenance,
            last_validated="2024-01-15T10:30:00",
            data_policy="trajectories",
            length_calibration_n=3,
            length_calibration_rel_sd=0.021,
        )
        ReadmeExporter().write(replace(provenance_payload, provenance=prov), tmp_path)
        content = (tmp_path / "README.md").read_text(encoding="utf-8")
        assert "| Last validated | 2024-01-15T10:30:00 |" in content
        assert "| idtracker.ai data policy | trajectories |" in content
        assert "| Length calibration clicks | 3 (relative SD 2.10%) |" in content

    def test_never_validated_is_stated(
        self, tmp_path: Path, provenance_payload: ExportPayload
    ) -> None:
        ReadmeExporter().write(provenance_payload, tmp_path)
        content = (tmp_path / "README.md").read_text(encoding="utf-8")
        assert "never opened in the Validator" in content

# ── Source-software provenance: any tracker, not only idtracker.ai ────────────
#
# SessionProvenance used to describe idtracker.ai and nothing else, so a session read from
# another tracker would have been reported as an idtracker.ai run with every field "unknown".


def _from(minimal_payload: ExportPayload, **fields: object) -> ExportPayload:
    from dataclasses import replace

    from track2data.exporters.base import SessionProvenance

    fields.setdefault("reader", "toy_csv")
    fields.setdefault("source_software", "Toy tracker")
    return replace(minimal_payload, provenance=SessionProvenance(**fields))  # type: ignore[arg-type]


def _readme(tmp_path: Path, payload: ExportPayload) -> str:
    ReadmeExporter().write(payload, tmp_path)
    return (tmp_path / "README.md").read_text(encoding="utf-8")


class TestWhichSectionTheReadmeWrites:
    def test_a_session_from_another_tracker_gets_the_generic_section_only(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        content = _readme(tmp_path, _from(minimal_payload))
        assert "## Source software provenance" in content
        assert "## idtracker.ai provenance" not in content

    @pytest.mark.parametrize("reader", ["idtrackerai", "idtrackerai_v5"])
    def test_an_idtracker_session_keeps_its_own_section_unchanged(
        self, tmp_path: Path, minimal_payload: ExportPayload, reader: str
    ) -> None:
        payload = _from(
            minimal_payload,
            reader=reader,
            source_software="idtracker.ai",
            reader_verification="real_sample",
        )
        content = _readme(tmp_path, payload)
        assert "## idtracker.ai provenance" in content
        assert "## Source software provenance" not in content

    def test_a_provenance_with_no_reader_is_still_read_as_idtracker(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        # What every payload built before readers were recorded looks like.
        content = _readme(tmp_path, minimal_payload)
        assert "## idtracker.ai provenance" in content
        assert "## Source software provenance" not in content


class TestTheSourceSoftwareSection:
    def test_the_software_falls_back_to_the_reader_name(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        content = _readme(tmp_path, _from(minimal_payload, source_software=None))
        assert "| Software | toy_csv |" in content

    def test_a_reader_whose_verification_is_unknown_says_so(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        content = _readme(tmp_path, _from(minimal_payload))
        assert "| Reader verification | *(not recorded)* |" in content

    def test_a_reader_with_nothing_recorded_about_how_it_was_chosen_says_so(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        content = _readme(tmp_path, _from(minimal_payload))
        assert "| Reader chosen | *(not recorded)* |" in content
        assert "| Reader options | *(none)* |" in content
        assert "| Source file(s) | *(not recorded)* |" in content

    def test_an_automatically_detected_reader_is_not_called_user_chosen(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        payload = _from(
            minimal_payload, reader_chosen_by="detected", detection_confidence="MEDIUM"
        )
        content = _readme(tmp_path, payload)
        assert "detected automatically (detection confidence MEDIUM)" in content
        assert "chosen by the user" not in content

    def test_option_values_cannot_break_the_table(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        payload = _from(minimal_payload, reader_options={"label": "a|b"})
        content = _readme(tmp_path, payload)
        assert "label=a\\|b" in content

    def test_only_the_file_names_are_shown_not_where_they_live(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        source = tmp_path / "private_dir" / "trial.csv"
        content = _readme(tmp_path / "out", _from(minimal_payload, source_files=(str(source),)))
        assert "`trial.csv`" in content
        assert "private_dir" not in content

    def test_a_long_list_of_files_is_cut_short_and_counted(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        files = tuple(str(tmp_path / f"f{i}.csv") for i in range(8))
        content = _readme(tmp_path / "out", _from(minimal_payload, source_files=files))
        assert "`f4.csv`" in content
        assert "`f5.csv`" not in content
        assert "+3 more" in content

    def test_the_manifest_json_gets_every_new_field(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        payload = _from(
            minimal_payload,
            reader_verification="synthetic_only",
            reader_options={"fps": 25.0},
            reader_chosen_by="user",
            detection_confidence="HIGH",
            source_files=("a.csv",),
        )
        ReadmeExporter().write(payload, tmp_path)
        prov = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))[
            "run_metadata"
        ]["session_provenance"]
        assert prov["source_software"] == "Toy tracker"
        assert prov["reader_verification"] == "synthetic_only"
        assert prov["reader_options"] == {"fps": 25.0}
        assert prov["reader_chosen_by"] == "user"
        assert prov["detection_confidence"] == "HIGH"
        assert prov["source_files"] == ["a.csv"]


class TestCalibrationInTheSourceSoftwareSection:
    def test_an_unconfirmed_factor_is_flagged_without_blaming_idtracker(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        content = _readme(tmp_path, _from(minimal_payload, length_unit=10.0))
        assert "| Length calibration factor | 10 px per cm (**not confirmed**" in content
        assert "idtracker.ai does not record" not in content

    def test_a_confirmed_factor_carries_no_warning(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        payload = _from(
            minimal_payload,
            length_unit=10.0,
            length_unit_label="mm",
            length_unit_confirmed_by_user=True,
        )
        content = _readme(tmp_path, payload)
        assert "10 px per mm (confirmed by user)" in content
        assert "not confirmed" not in content

    def test_no_factor_says_not_calibrated(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        content = _readme(tmp_path, _from(minimal_payload))
        assert "| Length calibration factor | *(not calibrated)* |" in content

    def test_the_idtracker_wording_is_unchanged(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        payload = _from(minimal_payload, reader="idtrackerai", length_unit=10.0)
        content = _readme(tmp_path, payload)
        assert "idtracker.ai does not record which physical unit" in content


class TestTheAnimalPositionRow:
    """Which keypoint stood for the animal is part of what a Methods section must say."""

    SELECTION = {
        "keypoint": "snout",
        "chosen_by": "coverage",
        "cutoff": 0.6,
        "coverage": 0.984,
        "plane": ["x", "y"],
        "n_keypoints": 12,
    }

    def test_it_names_the_keypoint_how_it_was_chosen_and_the_cutoff(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        content = _readme(tmp_path, _from(minimal_payload, keypoint_selection=self.SELECTION))
        row = next(line for line in content.splitlines() if line.startswith("| Animal position"))
        assert "`snout`" in row and "best coverage" in row
        assert "likelihood cutoff 0.6" in row and "98.4 %" in row
        assert "12 keypoints" in row and "x, y" in row

    def test_a_keypoint_the_user_named_says_so(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        chosen = {**self.SELECTION, "chosen_by": "user", "cutoff": None}
        content = _readme(tmp_path, _from(minimal_payload, keypoint_selection=chosen))
        row = next(line for line in content.splitlines() if line.startswith("| Animal position"))
        assert "chosen by the user" in row and "no likelihood cutoff" in row

    def test_a_tracker_with_one_point_per_animal_has_no_such_row(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        assert "Animal position" not in _readme(tmp_path, _from(minimal_payload))


# ── Camera view: written only when it says something ──────────────────────────


class TestCameraViewProvenance:
    def test_a_default_run_has_no_camera_view_section(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        """Existing READMEs must not change just because the setting now exists."""
        assert "Camera view" not in _readme(tmp_path, _from(minimal_payload))

    def test_a_declared_view_is_recorded(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        content = _readme(tmp_path, _from(minimal_payload, camera_view="side"))
        assert "## Camera view" in content
        assert "| Camera view | Side view |" in content

    def test_a_top_down_view_is_recorded_in_words(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        content = _readme(tmp_path, _from(minimal_payload, camera_view="top"))
        assert "| Camera view | Top-down |" in content

    def test_the_water_column_rows_and_source_are_recorded(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        column = {"top_px": 100.0, "bottom_px": 700.0, "source": "zone:tank"}
        content = _readme(
            tmp_path, _from(minimal_payload, camera_view="side", water_column=column)
        )
        assert "| Water column | rows 100 to 700 px (zone:tank) |" in content

    def test_a_missing_water_column_says_why(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        column = {"top_px": None, "bottom_px": None, "source": "none:no_main_zone"}
        content = _readme(
            tmp_path, _from(minimal_payload, camera_view="side", water_column=column)
        )
        assert "| Water column | none (none:no_main_zone) |" in content

    def test_the_manifest_json_carries_the_view(
        self, tmp_path: Path, minimal_payload: ExportPayload
    ) -> None:
        import json

        ReadmeExporter().write(_from(minimal_payload, camera_view="side"), tmp_path)
        data = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
        assert data["run_metadata"]["session_provenance"]["camera_view"] == "side"



# ── units, user-supplied options, empty identity slots ────────────────────────


def _render_readme(payload: ExportPayload, out: Path) -> str:
    ReadmeExporter().write(payload, out)
    return (out / "README.md").read_text(encoding="utf-8")


def _with_calibration(payload: ExportPayload, mode: str, px_per_cm: float | None = None) -> None:
    payload.manifest_json = json.dumps(
        {"calibration": {"mode": mode, "px_per_cm": px_per_cm}, "project_name": "MyProject"}
    )


class TestUnitsNote:
    def test_bodylength_mode_says_why_the_cm_columns_are_empty(
        self, minimal_payload: ExportPayload, tmp_path: Path
    ) -> None:
        _with_calibration(minimal_payload, "bodylength")
        text = _render_readme(minimal_payload, tmp_path)
        assert "## Units" in text
        assert "_cm" in text and "empty" in text and "scalar" in text

    def test_the_note_makes_no_idtrackerai_claim_for_another_reader(
        self, minimal_payload: ExportPayload, tmp_path: Path
    ) -> None:
        minimal_payload.provenance.reader = "sleap"
        _with_calibration(minimal_payload, "bodylength")
        text = _render_readme(minimal_payload, tmp_path)
        section = text.split("## Units")[1].split("\n## ")[0]
        assert "idtracker" not in section.lower() and "tracker records" not in section

    def test_scalar_mode_without_a_scale_explains_the_empty_cm_columns(
        self, minimal_payload: ExportPayload, tmp_path: Path
    ) -> None:
        _with_calibration(minimal_payload, "scalar", None)
        text = _render_readme(minimal_payload, tmp_path)
        assert "Calibration is 'scalar' but no pixels-per-cm value is set" in text

    def test_scalar_mode_with_a_scale_has_no_such_note(
        self, minimal_payload: ExportPayload, tmp_path: Path
    ) -> None:
        _with_calibration(minimal_payload, "scalar", 12.5)
        assert "## Units" not in _render_readme(minimal_payload, tmp_path)


class TestSuppliedReaderOptions:
    def test_idtrackerai_readme_lists_options_the_user_gave(
        self, minimal_payload: ExportPayload, tmp_path: Path
    ) -> None:
        minimal_payload.provenance.reader = "idtrackerai"
        minimal_payload.provenance.reader_options = {"width_px": 640, "fps": 25.0}
        text = _render_readme(minimal_payload, tmp_path)
        assert "fps=25.0" in text and "width_px=640" in text
        assert "not recorded in the files" in text

    def test_no_options_no_row(self, minimal_payload: ExportPayload, tmp_path: Path) -> None:
        minimal_payload.provenance.reader = "idtrackerai"
        assert "not recorded in the files" not in _render_readme(minimal_payload, tmp_path)


class TestEmptyIdentitySlots:
    def test_slots_that_are_almost_all_missing_are_listed(
        self, minimal_payload: ExportPayload, tmp_path: Path
    ) -> None:
        n = 20
        nan = float("nan")
        minimal_payload.fish_by_frame = pd.DataFrame(
            {
                "individual_id": [0] * n + [1] * n + [2] * n,
                "frame": list(range(n)) * 3,
                "x_px": [1.0] * n + [nan] * 19 + [1.0] + [nan] * n,
                "y_px": [1.0] * n + [nan] * 19 + [1.0] + [nan] * n,
            }
        )
        text = _render_readme(minimal_payload, tmp_path)
        assert "## Identity slots with little data" in text
        section = text.split("## Identity slots with little data")[1].split("\n## ")[0]
        assert "| 1 |" in section and "| 2 |" in section and "| 0 |" not in section

    def test_other_readers_get_no_idtrackerai_slot_section(
        self, minimal_payload: ExportPayload, tmp_path: Path
    ) -> None:
        minimal_payload.provenance.reader = "sleap"
        n = 20
        nan = float("nan")
        minimal_payload.fish_by_frame = pd.DataFrame(
            {
                "individual_id": [0] * n + [1] * n,
                "frame": list(range(n)) * 2,
                "x_px": [1.0] * n + [nan] * n,
                "y_px": [1.0] * n + [nan] * n,
            }
        )
        assert "Identity slots with little data" not in _render_readme(minimal_payload, tmp_path)

    def test_the_slot_table_is_capped_at_twenty_rows(
        self, minimal_payload: ExportPayload, tmp_path: Path
    ) -> None:
        minimal_payload.provenance.reader = "idtrackerai"
        n_slots = 27
        nan = float("nan")
        minimal_payload.fish_by_frame = pd.DataFrame(
            {
                "individual_id": [0] * 20 + [i for i in range(1, n_slots) for _ in range(20)],
                "frame": list(range(20)) * n_slots,
                "x_px": [1.0] * 20 + [nan] * (20 * (n_slots - 1)),
                "y_px": [1.0] * 20 + [nan] * (20 * (n_slots - 1)),
            }
        )
        text = _render_readme(minimal_payload, tmp_path)
        section = text.split("## Identity slots with little data")[1].split("\n## ")[0]
        rows =[ln for ln in section.splitlines() if ln.startswith("| ") and "%" in ln]
        assert len(rows) == 20
        assert "and 6 more" in section

    def test_a_well_covered_session_has_no_such_section(
        self, minimal_payload: ExportPayload, tmp_path: Path
    ) -> None:
        assert "Identity slots with little data" not in _render_readme(minimal_payload, tmp_path)


# ── columns that are entirely NaN ─────────────────────────────────────────────

_NAN = float("nan")


def _section(text: str) -> str:
    assert "## Columns with no values" in text
    return text.split("## Columns with no values")[1].split("\n## ")[0]


def _row(section: str, key: str) -> str:
    return next(line for line in section.splitlines() if key in line)


class TestColumnsWithNoValues:
    def test_each_empty_diagnostic_column_gets_the_reason_for_its_metric(
        self, minimal_payload: ExportPayload, tmp_path: Path
    ) -> None:
        minimal_payload.diagnostic_metrics = {
            "D-7": pd.DataFrame({"session_id": ["s1"], "fragment_length_median": [_NAN]}),
            "D-2": pd.DataFrame({"session_id": ["s1"], "estimated_accuracy": [_NAN]}),
            "D-3": pd.DataFrame({"session_id": ["s1"], "id_prob_median": [_NAN]}),
            "D-6": pd.DataFrame({"session_id": ["s1"], "number_of_error_frames": [_NAN]}),
            "D-12": pd.DataFrame({"session_id": ["s1"], "silhouette_score": [_NAN]}),
            "D-15": pd.DataFrame({"session_id": ["s1"], "n_corrected_frames": [_NAN]}),
        }
        section = _section(_render_readme(minimal_payload, tmp_path))
        assert "list_of_fragments.json" in _row(section, "fragment_length_median")
        assert "fraction_identified" in _row(section, "estimated_accuracy")
        assert "id_probabilities" in _row(section, "id_prob_median")
        assert "session.json" in _row(section, "number_of_error_frames")
        assert "silhouette" in _row(section, "silhouette_score")
        assert "list_of_blobs" in _row(section, "n_corrected_frames")

    def test_a_column_with_any_value_is_not_listed(
        self, minimal_payload: ExportPayload, tmp_path: Path
    ) -> None:
        minimal_payload.individual_metrics = {
            "IL-5": pd.DataFrame(
                {"individual_id": [0, 1], "partial": [_NAN, 2.0], "empty": [_NAN, _NAN]}
            )
        }
        section = _section(_render_readme(minimal_payload, tmp_path))
        assert "`empty`" in section and "partial" not in section

    def test_a_metric_without_a_known_reason_gets_the_generic_one(
        self, minimal_payload: ExportPayload, tmp_path: Path
    ) -> None:
        minimal_payload.group_metrics = {"GL-5": pd.DataFrame({"session_id": ["s1"], "m": [_NAN]})}
        section = _section(_render_readme(minimal_payload, tmp_path))
        assert "no valid values in this run" in section

    def test_cm_columns_point_to_the_units_section_under_bodylength(
        self, minimal_payload: ExportPayload, tmp_path: Path
    ) -> None:
        _with_calibration(minimal_payload, "bodylength")
        minimal_payload.individual_metrics = {
            "IL-1": pd.DataFrame(
                {"individual_id": [0], "path_length_cm": [_NAN], "mean_speed_cm_s": [_NAN]}
            )
        }
        text = _render_readme(minimal_payload, tmp_path)
        assert "## Units" in text
        assert "Units" in _row(_section(text), "path_length_cm")
        assert "Units" in _row(_section(text), "mean_speed_cm_s")

    def test_idtrackerai_reasons_are_not_given_to_other_readers(
        self, minimal_payload: ExportPayload, tmp_path: Path
    ) -> None:
        minimal_payload.provenance.reader = "trex"
        minimal_payload.diagnostic_metrics = {
            "D-7": pd.DataFrame({"session_id": ["s1"], "fragment_length_median": [_NAN]}),
            "D-6": pd.DataFrame({"session_id": ["s1"], "number_of_error_frames": [_NAN]}),
        }
        section = _section(_render_readme(minimal_payload, tmp_path))
        assert "list_of_fragments" not in section and "session.json" not in section
        assert "no valid values in this run" in _row(section, "fragment_length_median")

    def test_cm_columns_point_to_units_when_scalar_has_no_scale(
        self, minimal_payload: ExportPayload, tmp_path: Path
    ) -> None:
        _with_calibration(minimal_payload, "scalar", None)
        minimal_payload.individual_metrics = {
            "IL-1": pd.DataFrame({"individual_id": [0], "path_length_cm": [_NAN]})
        }
        text = _render_readme(minimal_payload, tmp_path)
        assert "Units" in _row(_section(text), "path_length_cm")

    def test_gl1_blames_the_skipped_frames_when_every_frame_was_skipped(
        self, minimal_payload: ExportPayload, tmp_path: Path
    ) -> None:
        minimal_payload.fish_by_frame = pd.DataFrame(
            {
                "individual_id": [0, 1] * 5,
                "frame": [f for f in range(5) for _ in range(2)],
                "x_px": [1.0] * 10,
                "y_px": [1.0] * 10,
            }
        )
        minimal_payload.group_metrics = {
            "GL-1": pd.DataFrame(
                {"session_id": ["s1"], "mean_nnd_px": [_NAN], "n_skipped_frames": [5]}
            )
        }
        section = _section(_render_readme(minimal_payload, tmp_path))
        assert "n_skipped_frames" in _row(section, "mean_nnd_px")
        assert "missing position" in _row(section, "mean_nnd_px")

    def test_gl1_stays_generic_when_not_every_frame_was_skipped(
        self, minimal_payload: ExportPayload, tmp_path: Path
    ) -> None:
        minimal_payload.fish_by_frame = pd.DataFrame(
            {
                "individual_id": [0, 1] * 5,
                "frame": [f for f in range(5) for _ in range(2)],
                "x_px": [1.0] * 10,
                "y_px": [1.0] * 10,
            }
        )
        minimal_payload.group_metrics = {
            "GL-1": pd.DataFrame(
                {"session_id": ["s1"], "mean_nnd_px": [_NAN], "n_skipped_frames": [2]}
            )
        }
        section = _section(_render_readme(minimal_payload, tmp_path))
        assert "no valid values in this run" in _row(section, "mean_nnd_px")

    def test_nothing_empty_nothing_written(
        self, minimal_payload: ExportPayload, tmp_path: Path
    ) -> None:
        assert "Columns with no values" not in _render_readme(minimal_payload, tmp_path)

    def test_a_table_with_no_rows_is_not_reported_as_empty(
        self, minimal_payload: ExportPayload, tmp_path: Path
    ) -> None:
        minimal_payload.individual_metrics = {"IL-2": pd.DataFrame({"individual_id": [], "v": []})}
        assert "Columns with no values" not in _render_readme(minimal_payload, tmp_path)

    def test_text_columns_are_not_mistaken_for_empty(
        self, minimal_payload: ExportPayload, tmp_path: Path
    ) -> None:
        minimal_payload.diagnostic_metrics = {
            "D-15": pd.DataFrame({"n_corrected_frames": [1.0], "note": [""]})
        }
        assert "Columns with no values" not in _render_readme(minimal_payload, tmp_path)

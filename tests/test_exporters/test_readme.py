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

"""Tests for metadata schema + loader + mapping + join."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

# ── schema ────────────────────────────────────────────────────────────────────


def test_canonical_list_not_empty() -> None:
    from track2data.metadata.schema import CANONICAL

    assert len(CANONICAL) >= 7
    assert "session_id" in CANONICAL
    assert "treatment" in CANONICAL


def test_resolve_known_alias() -> None:
    from track2data.metadata.schema import resolve_column

    assert resolve_column("condition") == "treatment"
    assert resolve_column("date") == "trial_date"


def test_resolve_already_canonical() -> None:
    from track2data.metadata.schema import resolve_column

    assert resolve_column("session_id") == "session_id"


def test_resolve_unknown_passes_through() -> None:
    from track2data.metadata.schema import resolve_column

    assert resolve_column("my_custom_col") == "my_custom_col"


def test_is_canonical() -> None:
    from track2data.metadata.schema import is_canonical

    assert is_canonical("session_id")
    assert not is_canonical("random_junk")


# ── loader ────────────────────────────────────────────────────────────────────


def test_load_csv(tmp_path: Path) -> None:
    from track2data.metadata.loader import load

    csv = tmp_path / "meta.csv"
    csv.write_text("session_id,treatment,trial_date\nS1,ctrl,2024-01-01\nS2,exp,2024-01-02\n")
    df = load(csv)
    assert list(df.columns) == ["session_id", "treatment", "trial_date"]
    assert df["session_id"].tolist() == ["S1", "S2"]


def test_load_csv_strips_whitespace(tmp_path: Path) -> None:
    from track2data.metadata.loader import load

    csv = tmp_path / "meta.csv"
    csv.write_text("session_id , treatment\n S1 , ctrl \n")
    df = load(csv)
    assert "session_id" in df.columns
    assert df["session_id"].iloc[0] == "S1"


def test_load_csv_date_coercion(tmp_path: Path) -> None:
    from track2data.metadata.loader import load

    csv = tmp_path / "meta.csv"
    csv.write_text("session_id,trial_date\nS1,2024-03-15\n")
    df = load(csv)
    assert pd.api.types.is_datetime64_any_dtype(df["trial_date"])


def test_load_missing_file_raises(tmp_path: Path) -> None:
    from track2data.metadata.loader import load

    with pytest.raises(FileNotFoundError):
        load(tmp_path / "does_not_exist.csv")


def test_load_bad_extension_raises(tmp_path: Path) -> None:
    from track2data.metadata.loader import load

    f = tmp_path / "meta.json"
    f.write_text("{}")
    with pytest.raises(ValueError, match="Unsupported"):
        load(f)


# ── mapping ───────────────────────────────────────────────────────────────────


def test_apply_mapping_renames_columns() -> None:
    from track2data.core.models import MappingRule
    from track2data.metadata.mapping import apply_mapping

    df = pd.DataFrame({"session_id": ["S1"], "condition": ["ctrl"]})
    rule = MappingRule(rules={"treatment": "condition"})
    out = apply_mapping(df, rule)
    assert "treatment" in out.columns
    assert "condition" not in out.columns


def test_apply_mapping_drops_non_canonical() -> None:
    from track2data.core.models import MappingRule
    from track2data.metadata.mapping import apply_mapping

    df = pd.DataFrame({"session_id": ["S1"], "some_junk": [42]})
    rule = MappingRule(rules={})
    out = apply_mapping(df, rule)
    assert "some_junk" not in out.columns
    assert "session_id" in out.columns


def test_auto_map_detects_canonical_columns() -> None:
    from track2data.metadata.mapping import auto_map

    df = pd.DataFrame({"session_id": ["S1"], "treatment": ["ctrl"], "trial_id": [1]})
    rule = auto_map(df)
    assert "session_id" in rule.rules or "session_id" in rule.rules.values()


def test_auto_map_applies_alias() -> None:
    from track2data.metadata.mapping import auto_map

    df = pd.DataFrame({"session_id": ["S1"], "condition": ["ctrl"]})
    rule = auto_map(df)
    assert "treatment" in rule.rules


# ── join ──────────────────────────────────────────────────────────────────────


def test_join_exact_match() -> None:
    from track2data.core.models import MappingRule
    from track2data.metadata.join import match

    df = pd.DataFrame({"session_id": ["S1", "S2"], "treatment": ["ctrl", "exp"]})
    rule = MappingRule(join_keys=["session_id"])
    result = match(["S1", "S2"], df, rule)
    assert "S1" in result.matched
    assert result.matched["S1"]["treatment"] == "ctrl"
    assert result.unmatched_sessions == []
    assert result.unmatched_metadata_rows == []


def test_join_unmatched_session() -> None:
    from track2data.core.models import MappingRule
    from track2data.metadata.join import match

    df = pd.DataFrame({"session_id": ["S1"], "treatment": ["ctrl"]})
    rule = MappingRule(join_keys=["session_id"])
    result = match(["S1", "S99"], df, rule)
    assert "S99" in result.unmatched_sessions
    assert 0 not in result.unmatched_metadata_rows  # S1 is matched


def test_join_unmatched_metadata_row() -> None:
    from track2data.core.models import MappingRule
    from track2data.metadata.join import match

    df = pd.DataFrame({"session_id": ["S1", "S_extra"], "treatment": ["ctrl", "exp"]})
    rule = MappingRule(join_keys=["session_id"])
    result = match(["S1"], df, rule)
    assert 1 in result.unmatched_metadata_rows  # S_extra row index 1


def test_join_conflict_logged() -> None:
    from track2data.core.models import MappingRule
    from track2data.metadata.join import match

    df = pd.DataFrame({"session_id": ["S1", "S1"], "treatment": ["ctrl", "exp"]})
    rule = MappingRule(join_keys=["session_id"])
    result = match(["S1"], df, rule)
    assert len(result.conflicts) == 1
    assert result.conflicts[0].session_id == "S1"


def test_join_regex() -> None:
    from track2data.core.models import MappingRule
    from track2data.metadata.join import match

    # session_id "tank3_t1" should match via named groups tank/timepoint.
    df = pd.DataFrame({"tank": ["3"], "trial_id": ["1"], "treatment": ["ctrl"]})
    rule = MappingRule(
        join_keys=["tank", "trial_id"],
        join_regex=r"tank(?P<tank>\d+)_t(?P<trial_id>\d+)",
    )
    result = match(["tank3_t1"], df, rule)
    assert "tank3_t1" in result.matched


def test_join_regex_no_match_is_unmatched() -> None:
    """A session_id the regex pattern doesn't match at all -> unmatched, not an error."""
    from track2data.core.models import MappingRule
    from track2data.metadata.join import match

    df = pd.DataFrame({"tank": ["3"], "treatment": ["ctrl"]})
    rule = MappingRule(join_regex=r"tank(?P<tank>\d+)")
    result = match(["not_a_tank_folder"], df, rule)
    assert "not_a_tank_folder" in result.unmatched_sessions
    assert "not_a_tank_folder" not in result.matched


def test_join_composite_key_without_session_id() -> None:
    """Composite key join on columns that don't include session_id at all."""
    from track2data.core.models import MappingRule
    from track2data.metadata.join import match

    df = pd.DataFrame(
        {
            "tank": ["3", "4"],
            "trial_date": ["2024-01-01", "2024-01-02"],
            "treatment": ["ctrl", "exp"],
        }
    )
    rule = MappingRule(join_keys=["tank", "trial_date"])
    result = match(["3_2024-01-01"], df, rule)
    assert "3_2024-01-01" in result.matched
    assert result.matched["3_2024-01-01"]["treatment"] == "ctrl"


def test_join_single_non_session_id_key() -> None:
    """A single join key that isn't 'session_id' (e.g. an external video ID)."""
    from track2data.core.models import MappingRule
    from track2data.metadata.join import match

    df = pd.DataFrame({"video_id": ["vid_42"], "treatment": ["ctrl"]})
    rule = MappingRule(join_keys=["video_id"])
    result = match(["vid_42"], df, rule)
    assert "vid_42" in result.matched
    assert result.matched["vid_42"]["treatment"] == "ctrl"


def test_join_key_column_absent_from_dataframe() -> None:
    """The configured join key doesn't exist in the metadata DataFrame at all."""
    from track2data.core.models import MappingRule
    from track2data.metadata.join import match

    df = pd.DataFrame({"treatment": ["ctrl"]})
    rule = MappingRule(join_keys=["video_id"])
    result = match(["vid_42"], df, rule)
    assert "vid_42" in result.unmatched_sessions


# ── Excel sheets ─────────────────────────────────────────────────────────────


def _workbook(path: Path, sheets: dict[str, list[list[str]]]) -> Path:
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    wb.save(path)
    return path


TWO_SHEETS = {
    "Notes": [["note"], ["read me"]],
    "Trials": [["Session ID", "Treatment"], ["s1", "ctrl"], ["s2", "drug"]],
}


def test_load_xlsx_defaults_to_the_first_sheet(tmp_path: Path) -> None:
    from track2data.metadata.loader import load

    df = load(_workbook(tmp_path / "m.xlsx", TWO_SHEETS))
    assert list(df.columns) == ["note"]


def test_load_xlsx_reads_a_named_sheet(tmp_path: Path) -> None:
    from track2data.metadata.loader import load

    df = load(_workbook(tmp_path / "m.xlsx", TWO_SHEETS), sheet="Trials")
    assert list(df.columns) == ["session id", "treatment"]
    assert df["treatment"].tolist() == ["ctrl", "drug"]


def test_an_unknown_sheet_name_lists_the_available_ones(tmp_path: Path) -> None:
    from track2data.metadata.loader import load

    path = _workbook(tmp_path / "m.xlsx", TWO_SHEETS)
    with pytest.raises(ValueError, match="Notes, Trials"):
        load(path, sheet="Missing")


def test_list_sheets_of_a_csv_is_empty(tmp_path: Path) -> None:
    from track2data.metadata.loader import list_sheets

    csv = tmp_path / "m.csv"
    csv.write_text("a,b\n1,2\n")
    assert list_sheets(csv) == []
    assert list_sheets(_workbook(tmp_path / "m.xlsx", TWO_SHEETS)) == ["Notes", "Trials"]


def test_an_old_xls_file_is_refused_with_a_clear_message(tmp_path: Path) -> None:
    from track2data.metadata.loader import list_sheets, load

    old = tmp_path / "old.xls"
    old.write_bytes(b"\xd0\xcf\x11\xe0")
    for call in (load, list_sheets):
        with pytest.raises(ValueError, match=r"\.xlsx"):
            call(old)


def test_preview_keeps_the_stored_header_case(tmp_path: Path) -> None:
    from track2data.metadata.loader import preview

    headers, rows = preview(_workbook(tmp_path / "m.xlsx", TWO_SHEETS), "Trials")
    assert headers == ["Session ID", "Treatment"]
    assert rows == [["s1", "ctrl"], ["s2", "drug"]]


# ── MetadataSource.sheet and the project hash ────────────────────────────────


def _manifest(**source):
    from datetime import UTC, datetime

    from track2data.core.models import MetadataSource, ProjectManifest

    t = datetime(2026, 1, 1, tzinfo=UTC)
    return ProjectManifest(
        project_name="p",
        created_at=t,
        updated_at=t,
        metadata_source=MetadataSource(path=Path("meta.csv"), sha256="ab" * 32, **source),
    )


def test_a_manifest_without_a_sheet_keeps_its_hash_and_json() -> None:
    manifest = _manifest()
    assert "sheet" not in manifest.model_dump()["metadata_source"]
    assert (
        '"metadata_source":{"path":"meta.csv","sha256":"' + "ab" * 32 + '"}'
        in manifest.model_dump_json()
    )
    # Hash pinned on the dump a manifest without the field produced before it existed.
    import hashlib
    import json

    data = manifest.model_dump(exclude={"created_at", "updated_at", "run_log_path"})
    legacy = json.dumps(data, sort_keys=True, default=str)
    assert '"sheet"' not in legacy
    assert manifest.project_hash() == hashlib.sha256(legacy.encode()).hexdigest()[:16]


def test_a_chosen_sheet_is_saved_and_changes_the_hash() -> None:
    from track2data.core.models import ProjectManifest

    plain, chosen = _manifest(), _manifest(sheet="Trials")
    assert chosen.project_hash() != plain.project_hash()
    assert '"sheet":"Trials"' in chosen.model_dump_json()
    again = ProjectManifest.model_validate_json(chosen.model_dump_json())
    assert again.metadata_source.sheet == "Trials"
    assert again.project_hash() == chosen.project_hash()
    old = ProjectManifest.model_validate_json(plain.model_dump_json())
    assert old.metadata_source.sheet is None

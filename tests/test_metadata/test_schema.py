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

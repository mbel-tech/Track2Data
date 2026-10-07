"""Per-animal metadata: mapping extras and the per-animal join (supersedes D-010)."""

from __future__ import annotations

import pandas as pd
import pytest

from track2data.core.models import MappingRule
from track2data.metadata.join import match
from track2data.metadata.mapping import apply_mapping


def _df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "session_id": ["s1", "s1", "s2", "s2"],
            "fish": ["1", "2", "1", "2"],
            "treatment": ["ctrl", "ctrl", "drug", "drug"],
            "weight": [1.1, 2.2, 3.3, 4.4],
            "sex": ["m", "f", "f", "f"],
        }
    )


# ── mapping ──────────────────────────────────────────────────────────────────


def test_extra_columns_are_dropped_by_default() -> None:
    rule = MappingRule(rules={"session_id": "session_id", "treatment": "treatment"})
    out = apply_mapping(_df(), rule)
    assert "weight" not in out.columns and "sex" not in out.columns


def test_extra_columns_are_carried_when_requested() -> None:
    rule = MappingRule(
        rules={"session_id": "session_id", "individual_id": "fish"},
        extra_columns=["weight", "sex"],
    )
    out = apply_mapping(_df(), rule)
    assert {"session_id", "individual_id", "weight", "sex"} <= set(out.columns)
    assert "fish" not in out.columns  # renamed to individual_id


def test_extra_column_names_are_lowercased_like_the_loader() -> None:
    df = _df().rename(columns={"weight": "weight"})
    rule = MappingRule(rules={"session_id": "session_id"}, extra_columns=["WEIGHT"])
    assert "weight" in apply_mapping(df, rule).columns


def test_extra_columns_that_collide_with_engine_columns_are_skipped() -> None:
    df = _df().assign(speed_px_s=1.0, bin_index=0, frame=3)
    rule = MappingRule(
        rules={"session_id": "session_id"},
        extra_columns=["speed_px_s", "bin_index", "frame", "sex"],
    )
    out = apply_mapping(df, rule)
    assert "sex" in out.columns
    assert not {"speed_px_s", "bin_index", "frame"} & set(out.columns)


def test_unknown_extra_column_is_ignored() -> None:
    base = list(apply_mapping(_df(), MappingRule(rules={"session_id": "session_id"})).columns)
    rule = MappingRule(rules={"session_id": "session_id"}, extra_columns=["nope"])
    assert list(apply_mapping(_df(), rule).columns) == base


# ── join ─────────────────────────────────────────────────────────────────────


def _per_animal_rule() -> MappingRule:
    return MappingRule(
        rules={"session_id": "session_id", "individual_id": "fish", "treatment": "treatment"},
        extra_columns=["weight", "sex"],
    )


def _mapped() -> pd.DataFrame:
    return apply_mapping(_df(), _per_animal_rule())


def test_one_row_per_animal_is_not_a_conflict() -> None:
    res = match(["s1", "s2"], _mapped(), _per_animal_rule())
    assert res.conflicts == []
    assert set(res.matched_individuals) == {"s1", "s2"}
    assert set(res.matched_individuals["s1"]) == {"1", "2"}
    assert res.matched_individuals["s1"]["2"]["weight"] == 2.2


def test_session_level_fields_are_the_columns_constant_across_the_session() -> None:
    res = match(["s1", "s2"], _mapped(), _per_animal_rule())
    assert res.matched["s1"]["treatment"] == "ctrl"
    assert res.matched["s2"]["treatment"] == "drug"
    assert "weight" not in res.matched["s1"]       # varies between animals
    assert "sex" not in res.matched["s1"]          # varies in s1 ...
    assert res.matched["s2"]["sex"] == "f"         # ... but constant in s2


def test_per_animal_rows_do_not_carry_the_key_columns() -> None:
    res = match(["s1"], _mapped(), _per_animal_rule())
    row = res.matched_individuals["s1"]["1"]
    assert "session_id" not in row and "individual_id" not in row


def test_duplicate_animal_rows_are_a_conflict_and_the_first_is_kept() -> None:
    df = pd.concat([_mapped(), _mapped().iloc[[0]].assign(weight=99.0)], ignore_index=True)
    res = match(["s1"], df, _per_animal_rule())
    assert [c.session_id for c in res.conflicts] == ["s1"]
    assert res.matched_individuals["s1"]["1"]["weight"] == 1.1


def test_integer_like_keys_are_normalised() -> None:
    df = _mapped().copy()
    df["individual_id"] = [1.0, 2.0, 1.0, 2.0]  # a CSV with a missing value reads as float
    res = match(["s1"], df, _per_animal_rule())
    assert set(res.matched_individuals["s1"]) == {"1", "2"}


def test_rows_without_an_animal_key_are_ignored() -> None:
    df = _mapped().copy()
    df.loc[1, "individual_id"] = None
    res = match(["s1"], df, _per_animal_rule())
    assert set(res.matched_individuals["s1"]) == {"1"}


def test_session_without_rows_is_unmatched() -> None:
    res = match(["nope"], _mapped(), _per_animal_rule())
    assert res.unmatched_sessions == ["nope"] and res.matched_individuals == {}


def test_without_an_individual_mapping_the_join_is_unchanged() -> None:
    rule = MappingRule(rules={"session_id": "session_id", "treatment": "treatment"})
    df = apply_mapping(_df(), rule)
    res = match(["s1"], df, rule)
    assert res.matched_individuals == {}
    assert [c.session_id for c in res.conflicts] == ["s1"]  # two rows for one session


def test_individual_match_defaults_to_label_and_validates() -> None:
    assert MappingRule().individual_match == "label"
    assert MappingRule(individual_match="index").individual_match == "index"
    with pytest.raises(ValueError):
        MappingRule(individual_match="position")  # type: ignore[arg-type]

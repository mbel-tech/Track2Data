"""Metadata reaches a 3-D run: a pair unit carries its TOP session's metadata, and per-animal
metadata matches the fused fish by the top session's label or index."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from track2data.api import Engine
from track2data.core.models import MappingRule, MetadataSource, ProjectManifest, ProjectMode

from .scene import build_scene, pair

EXPORTERS = ["csv_long", "csv_wide", "readme"]
SESSION_META = {
    "t1": ("ctrl", "A", "F"),
    "s1": ("ctrl_side", "SIDE", "M"),
    "t2": ("drug", "B", "M"),
    "s2": ("drug_side", "SIDE", "F"),
    "lone": ("lonely", "C", "F"),
}


def _with_session_meta(base: Path, manifest: ProjectManifest) -> ProjectManifest:
    path = base / "meta.csv"
    pd.DataFrame(
        [
            {"session_id": sid, "group_id": g, "treatment": t, "sex": s}
            for sid, (g, t, s) in SESSION_META.items()
        ]
    ).to_csv(path, index=False)
    return manifest.model_copy(
        update={
            "metadata_source": MetadataSource(path=path, sha256=""),
            "mapping": MappingRule(
                rules={"session_id": "session_id", "group_id": "group_id",
                       "treatment": "treatment"},
                extra_columns=["sex"],
            ),
        }
    )


def _with_animal_meta(base: Path, manifest: ProjectManifest, match: str) -> ProjectManifest:
    path = base / "animals.csv"
    rows = [
        {"session_id": sid, "individual_id": k, "group_id": f"g{sid}", "weight": 10.0 * k + n}
        for n, sid in enumerate(SESSION_META)
        for k in range(3)
    ]
    pd.DataFrame(rows).to_csv(path, index=False)
    return manifest.model_copy(
        update={
            "metadata_source": MetadataSource(path=path, sha256=""),
            "mapping": MappingRule(
                rules={"session_id": "session_id", "individual_id": "individual_id",
                       "group_id": "group_id"},
                extra_columns=["weight"],
                individual_match=match,  # type: ignore[arg-type]
            ),
        }
    )


def test_a_pair_unit_carries_the_top_sessions_metadata_everywhere(tmp_path: Path) -> None:
    manifest = _with_session_meta(tmp_path, build_scene(tmp_path / "data"))
    out = tmp_path / "out"
    Engine(manifest).run(out, exporters=EXPORTERS)
    for unit, top in (("t1+s1", "t1"), ("t2+s2", "t2")):
        want = dict(zip(("group_id", "treatment", "sex"), SESSION_META[top], strict=True))
        for name in ("master_fish_by_frame.csv", "trial_activity_summary.csv",
                     "trial_summary_wide.csv"):
            table = pd.read_csv(out / unit / name)
            for col, value in want.items():
                assert col in table.columns, (unit, name, col)
                assert set(table[col]) == {value}, (unit, name, col)
    for name in ("master_fish_by_frame.csv", "trial_activity_summary.csv"):
        pooled = pd.read_csv(out / "all_sessions" / name)
        by_unit = pooled.groupby("session_id")["group_id"].unique()
        assert {k: list(v) for k, v in by_unit.items()} == {
            "t1+s1": ["ctrl"], "t2+s2": ["drug"]
        }, name


def test_a_2d_run_still_attaches_metadata_by_session(tmp_path: Path) -> None:
    manifest = build_scene(tmp_path / "data").model_copy(
        update={"mode": ProjectMode(), "view_pairs": []}
    )
    manifest = _with_session_meta(tmp_path, manifest)
    out = tmp_path / "out"
    Engine(manifest).run(out, exporters=["csv_long"])
    for sid, (group, treatment, sex) in SESSION_META.items():
        frames = pd.read_csv(out / sid / "master_fish_by_frame.csv")
        assert set(frames["group_id"]) == {group}
        assert set(frames["treatment"]) == {treatment}
        assert set(frames["sex"]) == {sex}


@pytest.mark.parametrize("match", ["label", "index"])
def test_per_animal_metadata_matches_the_top_fish_with_a_partial_map(
    tmp_path: Path, match: str
) -> None:
    partial = {"0": "0", "2": "2"}  # top fish 1 is left out
    pairs = [
        pair("t1", "s1").model_copy(update={"fish_map": partial}),
        pair("t2", "s2"),
    ]
    manifest = _with_animal_meta(tmp_path, build_scene(tmp_path / "data", pairs=pairs), match)
    out = tmp_path / "out"
    Engine(manifest).run(out, exporters=["csv_long"])
    # weights: 10 * top index + the session's position in SESSION_META (t1 = 0, t2 = 2)
    for unit, want in (("t1+s1", {0: 0.0, 1: 20.0}), ("t2+s2", {0: 2.0, 1: 12.0, 2: 22.0})):
        for name in ("master_fish_by_frame.csv", "trial_activity_summary.csv"):
            table = pd.read_csv(out / unit / name)
            got = table.groupby("individual_id")["weight"].unique()
            assert {int(k): list(v) for k, v in got.items()} == {
                k: [w] for k, w in want.items()
            }, (unit, name)
    labels = pd.read_csv(
        out / "t1+s1" / "master_fish_by_frame.csv", dtype={"individual_label": str}
    )
    assert labels.groupby("individual_id")["individual_label"].first().to_dict() == {0: "0", 1: "2"}

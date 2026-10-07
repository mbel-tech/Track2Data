"""Per-animal metadata through the Engine (supersedes D-010)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from track2data.api import Engine
from track2data.core.models import (
    CalibrationConfig,
    MappingRule,
    MetadataSource,
    MetricSelection,
    ProjectManifest,
    SessionRef,
)

RULES = {
    "session_id": "session_id",
    "individual_id": "fish",
    "treatment": "treatment",
}


def _write_csv(tmp_path: Path, session: str, fish=("1", "2"), extra: dict | None = None) -> Path:
    data = {
        "session_id": [session] * len(fish),
        "fish": list(fish),
        "treatment": ["drug_a"] * len(fish),
        "weight": [1.5 + i for i in range(len(fish))],
        "sex": ["m", "f"][: len(fish)],
    }
    data.update(extra or {})
    path = tmp_path / "meta.csv"
    pd.DataFrame(data).to_csv(path, index=False)
    return path


def _engine(folder: Path, csv: Path, **rule_kw) -> Engine:
    now = datetime.now(tz=UTC)
    rule = MappingRule(rules=RULES, extra_columns=["weight", "sex"], **rule_kw)
    return Engine(
        ProjectManifest(
            project_name="p", created_at=now, updated_at=now,
            sessions=[SessionRef(session_id=folder.name, folder=folder, sha256="x")],
            calibration=CalibrationConfig(mode="scalar", px_per_cm=10.0),
            metrics=MetricSelection(individual=["IL-1", "IL-2"], group=["GL-1"], zone=[]),
            metadata_source=MetadataSource(path=csv, sha256="x"),
            mapping=rule,
        )
    )


def _psess(engine: Engine, folder: Path):
    return engine.preprocess(engine.import_session(folder))


def test_label_match_gives_each_animal_its_own_values(tmp_path, tiny_real_session) -> None:
    eng = _engine(tiny_real_session, _write_csv(tmp_path, tiny_real_session.name))
    fbf = eng.build_fish_by_frame(_psess(eng, tiny_real_session))
    per = fbf.groupby("individual_id")[["weight", "sex", "treatment"]].first()
    assert per.loc[0, "weight"] == 1.5 and per.loc[1, "weight"] == 2.5
    assert per.loc[0, "sex"] == "m" and per.loc[1, "sex"] == "f"
    assert (per["treatment"] == "drug_a").all()
    assert set(fbf["individual_id"]) == {0, 1}  # the real index is never overwritten


def test_label_match_follows_the_label_not_the_row_order(tmp_path, tiny_real_session) -> None:
    csv = _write_csv(tmp_path, tiny_real_session.name, fish=("2", "1"))  # reversed rows
    eng = _engine(tiny_real_session, csv)
    fbf = eng.build_fish_by_frame(_psess(eng, tiny_real_session))
    first = fbf.groupby("individual_id")["weight"].first()
    assert first.loc[1] == 1.5 and first.loc[0] == 2.5  # label "2" is animal 1


def test_index_match_uses_the_zero_based_position(tmp_path, tiny_real_session) -> None:
    csv = _write_csv(tmp_path, tiny_real_session.name, fish=("0", "1"))
    eng = _engine(tiny_real_session, csv, individual_match="index")
    fbf = eng.build_fish_by_frame(_psess(eng, tiny_real_session))
    first = fbf.groupby("individual_id")["weight"].first()
    assert first.loc[0] == 1.5 and first.loc[1] == 2.5


def test_metric_frames_with_individual_id_get_per_animal_values(
    tmp_path, tiny_real_session
) -> None:
    eng = _engine(tiny_real_session, _write_csv(tmp_path, tiny_real_session.name))
    out = eng.compute_metrics(_psess(eng, tiny_real_session))
    il1 = out["IL-1"].set_index("individual_id")
    assert il1.loc[0, "weight"] == 1.5 and il1.loc[1, "weight"] == 2.5


def test_group_frames_get_only_session_level_values(tmp_path, tiny_real_session) -> None:
    eng = _engine(tiny_real_session, _write_csv(tmp_path, tiny_real_session.name))
    gl1 = eng.compute_metrics(_psess(eng, tiny_real_session))["GL-1"]
    assert (gl1["treatment"] == "drug_a").all()
    assert "weight" not in gl1.columns and "sex" not in gl1.columns


def test_an_animal_without_a_row_gets_nan_and_a_warning(
    tmp_path, tiny_real_session, caplog
) -> None:
    csv = _write_csv(tmp_path, tiny_real_session.name, fish=("1",))
    eng = _engine(tiny_real_session, csv)
    with caplog.at_level(logging.WARNING):
        fbf = eng.build_fish_by_frame(_psess(eng, tiny_real_session))
    first = fbf.groupby("individual_id")["weight"].first()
    assert first.loc[0] == 1.5 and np.isnan(first.loc[1])
    assert any("no metadata row" in r.message and "animal 1" in r.message for r in caplog.records)


def test_a_metadata_key_that_matches_no_animal_is_reported(
    tmp_path, tiny_real_session, caplog
) -> None:
    csv = _write_csv(tmp_path, tiny_real_session.name, fish=("1", "7"))
    eng = _engine(tiny_real_session, csv)
    with caplog.at_level(logging.WARNING):
        eng.build_fish_by_frame(_psess(eng, tiny_real_session))
    assert any("'7'" in r.message and "matches no animal" in r.message for r in caplog.records)


def test_identity_free_sessions_get_no_per_animal_values(
    tmp_path, tiny_real_session, caplog
) -> None:
    csv = _write_csv(tmp_path, tiny_real_session.name)
    eng = _engine(tiny_real_session, csv)
    psess = _psess(eng, tiny_real_session)
    eng._manifest = eng._manifest.model_copy(
        update={
            "sessions": [
                eng._manifest.sessions[0].model_copy(update={"identity_free_override": True})
            ]
        }
    )
    with caplog.at_level(logging.WARNING):
        fbf = eng.build_fish_by_frame(psess, identity_free=True)
    assert "weight" not in fbf.columns
    assert (fbf["treatment"] == "drug_a").all()  # session-level still attaches
    assert any("identity-free" in r.message for r in caplog.records)


def test_without_an_individual_mapping_nothing_is_per_animal(tmp_path, tiny_real_session) -> None:
    """D-010's guarantee still holds when individual_id is not mapped."""
    csv = tmp_path / "m.csv"
    pd.DataFrame(
        {"session_id": [tiny_real_session.name], "fish_id": ["NOT_AN_INDEX"], "treatment": ["x"]}
    ).to_csv(csv, index=False)
    eng = _engine(tiny_real_session, csv)
    eng._manifest = eng._manifest.model_copy(
        update={"mapping": MappingRule(rules={"treatment": "treatment"})}
    )
    fbf = eng.build_fish_by_frame(_psess(eng, tiny_real_session))
    assert set(fbf["individual_id"]) == {0, 1} and (fbf["treatment"] == "x").all()


def test_extra_column_colliding_with_an_engine_column_never_overwrites_it(
    tmp_path, tiny_real_session
) -> None:
    csv = _write_csv(tmp_path, tiny_real_session.name, extra={"speed_px_s": [999.0, 999.0]})
    eng = _engine(tiny_real_session, csv)
    eng._manifest = eng._manifest.model_copy(
        update={
            "mapping": eng._manifest.mapping.model_copy(
                update={"extra_columns": ["weight", "speed_px_s"]}
            )
        }
    )
    fbf = eng.build_fish_by_frame(_psess(eng, tiny_real_session))
    assert (fbf["speed_px_s"].dropna() != 999.0).all()


def test_full_export_has_per_animal_columns_and_no_suffixes(tmp_path, tiny_real_session) -> None:
    import shutil

    folder = tmp_path / "sess"
    shutil.copytree(tiny_real_session, folder)
    eng = _engine(folder, _write_csv(tmp_path, "sess"))
    out = tmp_path / "out"
    res = eng.run(out, exporters=["csv_long", "csv_wide", "feather", "excel"])
    assert res.sessions[0].error is None, res.sessions[0].error
    long = pd.read_csv(out / "sess" / "trial_activity_summary.csv")
    assert list(long.sort_values("individual_id")["weight"]) == [1.5, 2.5]
    for csv_file in out.rglob("*.csv"):
        cols = pd.read_csv(csv_file, nrows=1).columns
        assert not [c for c in cols if c.endswith(("_x", "_y"))], csv_file.name
    group = pd.read_csv(out / "sess" / "group_dynamics_summary.csv")
    assert "weight" not in group.columns and (group["treatment"] == "drug_a").all()


def test_per_animal_warnings_are_logged_once_per_session(
    tmp_path, tiny_real_session, caplog
) -> None:
    csv = _write_csv(tmp_path, tiny_real_session.name, fish=("1",))
    eng = _engine(tiny_real_session, csv)
    psess = _psess(eng, tiny_real_session)
    with caplog.at_level(logging.WARNING):
        eng.compute_metrics(psess)
        eng.build_fish_by_frame(psess)
    assert sum("no metadata row for animal 1" in r.message for r in caplog.records) == 1

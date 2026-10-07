"""The shipped example must keep working.

An example that rots is worse than none: it is the first thing a new user
runs, and a broken one teaches them the tool is broken. This is cheap
insurance -- it runs the committed `examples/example.t2d.json` end to end
and checks the output is the shape the walkthrough describes.

It also pins the two things that make the example worth shipping at all:
the session is an inert CSV bundle rather than a pickle, and the simulated
behaviour actually shows up in the metrics.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
SESSION = EXAMPLES / "tiny_session"
PROJECT = EXAMPLES / "example.t2d.json"


def test_the_example_session_is_committed() -> None:
    assert SESSION.is_dir(), "examples/tiny_session is missing"
    assert PROJECT.exists(), "examples/example.t2d.json is missing"


def test_the_example_session_is_not_a_pickle() -> None:
    """Shipping a .npy trajectory would hand out an execution vector as a
    "try this" example -- and Track2Data would refuse to open it without an
    opt-in, so the walkthrough's first command would fail."""
    assert not list(SESSION.rglob("*.npy")), "the example must stay pickle-free"
    assert (SESSION / "trajectories" / "trajectories_csv" / "trajectories.csv").exists()


def test_the_example_imports_without_any_security_opt_in() -> None:
    from track2data.readers import read_session

    session = read_session(SESSION)

    assert session.trajectory_format == "csv"
    assert session.n_animals == 4
    assert session.video.fps == 30.0
    # Calibrated and labelled, so the example exercises the *_cm columns.
    assert session.length_unit == 10.0
    assert session.identities_labels == ["fish_1", "fish_2", "fish_3", "fish_4"]


def test_the_example_project_runs_end_to_end(tmp_path: Path) -> None:
    from track2data.api import Engine
    from track2data.core.manifest import read

    manifest = read(PROJECT)
    # Session folders are stored relative so the file works from any
    # checkout; resolve against the examples directory as the CLI does.
    manifest = manifest.model_copy(
        update={
            "sessions": [
                ref.model_copy(update={"folder": EXAMPLES / ref.folder})
                for ref in manifest.sessions
            ]
        }
    )

    result = Engine(manifest).run(tmp_path, exporters=["csv_long"])

    assert not [r.error for r in result.sessions if r.error]
    for name in ("PROJECT_SUMMARY.md", "sessions.csv", "codebook.csv"):
        assert (tmp_path / name).exists(), f"the run wrote no {name}"
    assert (tmp_path / "tiny_session" / "metrics_long.csv").exists()


def test_the_walkthrough_output_matches_what_the_readme_promises(
    tmp_path: Path,
) -> None:
    """examples/README.md shows a metrics_long.csv row and claims the two
    wall-hugging fish sit at 1.00 in the `wall` zone. If the simulation or
    the zone assignment drifts, that claim becomes a lie."""
    from track2data.api import Engine
    from track2data.core.manifest import read

    manifest = read(PROJECT)
    manifest = manifest.model_copy(
        update={
            "sessions": [
                ref.model_copy(update={"folder": EXAMPLES / ref.folder})
                for ref in manifest.sessions
            ]
        }
    )
    Engine(manifest).run(tmp_path, exporters=["csv_long"])

    long = pd.read_csv(tmp_path / "tiny_session" / "metrics_long.csv")

    path = long[long["column"] == "path_length_cm"]
    assert len(path) == 4
    assert set(path["unit"]) == {"cm"}
    assert (path["value"] > 0).all()

    # The simulated thigmotaxis split: fish 0 and 1 at the wall, 2 and 3 in
    # the centre. A metric suite that cannot recover a difference this stark
    # is not going to recover a real one.
    zone = long[(long["metric_id"] == "Z-1") & (long["column"] == "time_pct")]
    occupancy = zone.pivot_table(
        index="individual_id", columns="zone_name", values="value"
    ).fillna(0.0)
    assert occupancy.loc[0, "wall"] == pytest.approx(1.0)
    assert occupancy.loc[1, "wall"] == pytest.approx(1.0)
    assert occupancy.loc[2, "centre"] == pytest.approx(1.0)
    assert occupancy.loc[3, "centre"] == pytest.approx(1.0)


def test_the_generator_reproduces_the_committed_session(tmp_path: Path) -> None:
    """The committed data has to be regenerable, or `make_example_session.py`
    is decoration and the example becomes unmaintainable."""
    import subprocess
    import sys

    subprocess.run(
        [sys.executable, str(EXAMPLES / "make_example_session.py"),
         "--out", str(tmp_path / "regen")],
        check=True,
        capture_output=True,
    )

    committed = (
        SESSION / "trajectories" / "trajectories_csv" / "trajectories.csv"
    ).read_text(encoding="utf-8")
    regenerated = (
        tmp_path / "regen" / "trajectories" / "trajectories_csv" / "trajectories.csv"
    ).read_text(encoding="utf-8")

    assert regenerated == committed, (
        "make_example_session.py no longer reproduces the committed session; "
        "regenerate it or fix the seed"
    )

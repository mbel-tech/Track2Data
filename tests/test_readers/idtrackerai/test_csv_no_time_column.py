"""An idtracker.ai CSV written without a time column (frame rate unknown) must load.

idtracker.ai 6.0.15 omits the leading time column when the video's frame rate cannot be read.
The column count settles it: 2k columns are k animals' x,y; 2k+1 columns carry a leading time.
Data modelled on animovement/movement-data ``trajectories_csv_no_fps`` (CC BY 4.0).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from track2data.core.errors import DataValidationError
from track2data.readers import read_session
from track2data.readers.idtrackerai.formats.csv_bundle import load_csv_bundle

TRAJ = (
    "x1,y1,x2,y2\n853.333,173.355,879.044,323.819\n854.101,174.002,878.512,324.660\n"
    "855.020,174.871,nan,nan\n855.874,175.530,877.230,326.101\n"
)
PROB = (
    "id_probabilities1,id_probabilities2\n1.000e+00,9.980e-01\n1.000e+00,9.970e-01\n"
    "1.000e+00,nan\n1.000e+00,9.950e-01\n"
)
TRAJ_T = "seconds," + TRAJ.replace("\n", "\n", 1)
TRAJ_T = "seconds,x1,y1,x2,y2\n" + "".join(
    f"{i / 28:.3f},{line}\n" for i, line in enumerate(TRAJ.splitlines()[1:])
)
PROB_T = "seconds,id_probabilities1,id_probabilities2\n" + "".join(
    f"{i / 28:.3f},{line}\n" for i, line in enumerate(PROB.splitlines()[1:])
)


def _bundle(root: Path, traj: str, prob: str | None) -> Path:
    d = root / "trajectories" / "trajectories_csv"
    d.mkdir(parents=True)
    (d / "trajectories.csv").write_text(traj)
    if prob is not None:
        (d / "id_probabilities.csv").write_text(prob)
    return d


def test_loader_keeps_both_animals_without_a_time_column(tmp_path: Path) -> None:
    out = load_csv_bundle(_bundle(tmp_path, TRAJ, PROB))
    assert out["trajectories"].shape == (4, 2, 2)
    np.testing.assert_allclose(out["trajectories"][0], [[853.333, 173.355], [879.044, 323.819]])
    assert out["id_probabilities"].shape == (4, 2)
    assert out["id_probabilities"][0, 0] == pytest.approx(1.0)


def test_loader_still_drops_a_leading_time_column(tmp_path: Path) -> None:
    out = load_csv_bundle(_bundle(tmp_path, TRAJ_T, PROB_T))
    assert out["trajectories"].shape == (4, 2, 2)
    np.testing.assert_allclose(out["trajectories"][0], [[853.333, 173.355], [879.044, 323.819]])
    assert out["id_probabilities"].shape == (4, 2)


def test_time_column_in_one_file_only_is_handled_per_file(tmp_path: Path) -> None:
    out = load_csv_bundle(_bundle(tmp_path, TRAJ, PROB_T))
    assert out["trajectories"].shape == (4, 2, 2)
    assert out["id_probabilities"].shape == (4, 2)


def test_probability_columns_that_fit_no_animal_count_are_a_coded_error(tmp_path: Path) -> None:
    bad = "p1,p2,p3,p4,p5\n" + "1,1,1,1,1\n" * 4
    with pytest.raises(DataValidationError) as err:
        load_csv_bundle(_bundle(tmp_path, TRAJ, bad))
    assert err.value.code == "IDT_SHAPE_MISMATCH"


def test_probability_row_count_mismatch_is_a_coded_error(tmp_path: Path) -> None:
    short = "id_probabilities1,id_probabilities2\n1,1\n1,1\n"
    with pytest.raises(DataValidationError) as err:
        load_csv_bundle(_bundle(tmp_path, TRAJ, short))
    assert err.value.code == "IDT_SHAPE_MISMATCH"


def test_session_reads_two_animals_when_size_and_fps_are_supplied(tmp_path: Path) -> None:
    _bundle(tmp_path, TRAJ, PROB)
    (tmp_path / "session.json").write_text(
        json.dumps({"width": 1000, "height": 1000, "frames_per_second": 28})
    )
    session = read_session(tmp_path)
    assert session.raw_xy.shape == (4, 2, 2)
    assert session.id_probabilities is not None
    assert session.id_probabilities.shape == (4, 2)

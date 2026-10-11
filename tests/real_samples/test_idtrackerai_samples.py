"""Worked example: testing idtracker.ai sample datasets (rows `idtracker.ai` of tracker_test_datasets.csv)
in Track2Data. Place in tests/real_samples/ and merge fixtures_manifest_idtrackerai_additions.json into
fixtures_manifest.json first. Run:  pytest tests/real_samples/test_idtrackerai_samples.py -m contract

What it asserts, and which handoff finding each test documents:
  F1  flat folders are not claimed; the same files inside <session>/trajectories/ are
  F2  no video width/height in the files -> IDT_DICT_MISSING_KEY unless session.json supplies it
  F7  reader options (fps / width_px / height_px) supply what a bare export does not record
  oracle tests: positions equal an independent read of the file; h5 and CSV exports of one session agree
  F3  CSV without a time column keeps both animals (and their probabilities)
  FR-IMP-5  reading does not modify the input folder
The session.json width/height below are PLACEHOLDERS for the two test_B exports (true video size not recorded in the
files); only the mechanics are being tested.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import h5py
import numpy as np
import pytest

from track2data.core.errors import DataValidationError, ImportError_
from track2data.readers import detect_reader, read_session

pytestmark = pytest.mark.contract

H5 = "idtrackerai_test_B.trajectories.h5"
CSV_T, CSV_P, CSV_A = ("idtrackerai_test_B.trajectories.csv", "idtrackerai_test_B.id_probabilities.csv",
                       "idtrackerai_test_B.attributes.json")
NF_T, NF_P = "idtrackerai_synthetic_no_fps.trajectories.csv", "idtrackerai_synthetic_no_fps.id_probabilities.csv"
NPY = "MoveR_sample_1.IdTrackerOutput.2602_ISA3080_Low_5.npy"
SIZE_PLACEHOLDER = {"width": 1000, "height": 1000}


def _arrange(tmp: Path, name: str, files: list[tuple[str, str]], fx, session_json: dict | None = None) -> Path:
    root = tmp / name
    for fixture, dest in files:
        target = root / dest
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(fx(fixture), target)
    if session_json is not None:
        (root / "session.json").write_text(json.dumps(session_json))
    return root


def _h5(tmp, fx, size=True):
    return _arrange(tmp, "h5", [(H5, "trajectories/trajectories.h5")], fx, SIZE_PLACEHOLDER if size else None)


def _csv(tmp, fx, size=True):
    d = "trajectories/trajectories_csv/"
    return _arrange(tmp, "csv", [(CSV_T, d + "trajectories.csv"), (CSV_P, d + "id_probabilities.csv"),
                                 (CSV_A, d + "attributes.json")], fx, SIZE_PLACEHOLDER if size else None)


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


# --- F1: layout -------------------------------------------------------------------------------
def test_flat_folder_is_not_claimed(tmp_path, fx):
    root = _arrange(tmp_path, "flat", [(H5, "trajectories.h5")], fx, SIZE_PLACEHOLDER)
    assert detect_reader(root) is None


@pytest.mark.parametrize("build", [_h5, _csv], ids=["h5", "csv"])
def test_session_style_folder_is_claimed_by_the_idtrackerai_reader(tmp_path, fx, build):
    reader = detect_reader(build(tmp_path, fx))
    assert reader is not None and reader.name == "idtrackerai"


# --- F2 / F7: video size ------------------------------------------------------------------------
@pytest.mark.parametrize("build", [_h5, _csv], ids=["h5", "csv"])
def test_missing_video_size_is_refused_with_a_coded_error(tmp_path, fx, build):
    with pytest.raises(DataValidationError) as err:
        read_session(build(tmp_path, fx, size=False))
    assert err.value.code == "IDT_DICT_MISSING_KEY" and err.value.subject == "width"


def test_reader_options_supply_the_video_size_a_bare_export_lacks(tmp_path, fx):
    session = read_session(_h5(tmp_path, fx, size=False), options={"width_px": 1000, "height_px": 1000})
    assert (session.video.width_px, session.video.height_px) == (1000, 1000)
    assert session.video.fps == 28.0  # recorded in the file; options only fill gaps


# --- oracle tests -------------------------------------------------------------------------------
def test_h5_positions_equal_an_independent_read(tmp_path, fx):
    session = read_session(_h5(tmp_path, fx))
    with h5py.File(fx(H5), "r") as handle:
        expected = handle["trajectories"][:]
        fps = float(handle.attrs["frames_per_second"])
    assert session.raw_xy.shape == expected.shape == (508, 8, 2)
    np.testing.assert_array_equal(session.raw_xy, expected)  # NaN positions compare equal
    assert session.video.fps == fps == 28.0 and session.n_animals == 8


def test_csv_export_agrees_with_the_h5_export_of_the_same_session(tmp_path, fx):
    from_h5 = read_session(_h5(tmp_path, fx))
    from_csv = read_session(_csv(tmp_path, fx))
    assert np.array_equal(np.isnan(from_h5.raw_xy), np.isnan(from_csv.raw_xy))
    np.testing.assert_allclose(from_csv.raw_xy, from_h5.raw_xy, atol=6e-4, equal_nan=True)  # CSV keeps 3 decimals
    assert from_csv.video.fps == from_h5.video.fps == 28.0
    assert from_csv.id_probabilities.shape == from_h5.id_probabilities.shape == (508, 8)


# --- pickled dict (MoveR sample) ------------------------------------------------------------------
def _npy(tmp, fx):
    return _arrange(tmp, "npy", [(NPY, "trajectories/trajectories.npy")], fx, {"width": 3840, "height": 2160})


def test_pickled_dict_is_refused_without_consent(tmp_path, fx):
    with pytest.raises(ImportError_) as err:
        read_session(_npy(tmp_path, fx))
    assert "IDT_PICKLE_REFUSED" in str(err.value)


def test_pickled_dict_positions_with_consent_equal_an_independent_read(tmp_path, fx):
    # The fixture is sha256-pinned and its pickle opcodes reference numpy only, so loading it here is safe.
    expected = np.load(fx(NPY), allow_pickle=True).item()
    session = read_session(_npy(tmp_path, fx), allow_pickle=True)
    np.testing.assert_array_equal(session.raw_xy, expected["trajectories"])
    assert session.raw_xy.shape == (12033, 20, 2) and session.video.fps == 25.0


# --- F3: CSV without a time column ------------------------------------------------------------------
def test_csv_without_time_column_keeps_both_animals(tmp_path, fx):
    d = "trajectories/trajectories_csv/"
    root = _arrange(tmp_path, "nofps", [(NF_T, d + "trajectories.csv"), (NF_P, d + "id_probabilities.csv")], fx,
                    {**SIZE_PLACEHOLDER, "frames_per_second": 28})
    session = read_session(root)
    assert session.raw_xy.shape == (4, 2, 2)
    assert session.id_probabilities.shape == session.raw_xy.shape[:2]


# --- FR-IMP-5 -------------------------------------------------------------------------------------------
@pytest.mark.parametrize("build", [_h5, _csv], ids=["h5", "csv"])
def test_reading_does_not_modify_the_input_folder(tmp_path, fx, build):
    root = build(tmp_path, fx)
    before = _tree_hash(root)
    read_session(root)
    assert _tree_hash(root) == before

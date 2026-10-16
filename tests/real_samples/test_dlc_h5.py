"""The DeepLabCut ``.h5`` reader on the real EPM sample (D-050).

Skips when the fixture is not cached and cannot be downloaded. Runs **without** PyTables: the
reader's own h5py + restricted-unpickler path is what is under test, and ``tables`` is made
unimportable for the read. Values are cross-checked against the pandas/PyTables oracle in
``test_reader_contract.py`` (which needs ``tables`` and is skipped without it).
"""

import sys

import pytest

from tests.real_samples.fixtures import fetch
from track2data import readers

pytestmark = pytest.mark.contract

DLC_EPM = "DLC_single-mouse_EPM.predictions.h5"
BODYPARTS = [
    "snout",
    "left_ear",
    "right_ear",
    "centre",
    "lateral_left",
    "lateral_right",
    "tailbase",
    "tail_end",
]


def test_the_epm_real_sample_is_read_to_18485_frames(monkeypatch):
    path = fetch(DLC_EPM)
    monkeypatch.setitem(sys.modules, "tables", None)  # any import of PyTables would now fail
    session = readers.read_session(
        path,
        reader="deeplabcut_h5",
        options={"fps": 30.0, "width_px": 1000, "height_px": 1000},
    )
    assert session.n_frames == 18485
    assert session.keypoints is not None
    assert list(session.keypoints.names) == BODYPARTS
    assert session.reader == "deeplabcut_h5"

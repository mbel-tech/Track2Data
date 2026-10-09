"""The ``trx.mat`` reader, built from the documented layout (no real sample is pinned yet).

Pinned: what counts as a trx file (a ``trx`` struct, never Ctrax's raw variables), 1-based frame
numbering, that ``pxpermm`` (pixels per mm) becomes ``length_unit`` in pixels per cm, and that a
``pxpermm`` of exactly 1 (the tools' "never calibrated" default) is not taken as a scale.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import scipy.io as sio

from track2data import readers
from track2data.core.errors import Track2DataError
from track2data.readers.detection import Confidence
from track2data.readers.scan import scan
from track2data.readers.trx_mat import TrxMatReader

SIZE = {"width_px": 640, "height_px": 480}


def write_trx(path: Path, tracks, *, fps: float | None = 25.0, pxpermm=None) -> Path:
    """``tracks``: list of (firstframe_1based, x, y). ``pxpermm``: one value or one per track."""
    dtype = [("x", "O"), ("y", "O"), ("firstframe", "O"), ("endframe", "O"), ("nframes", "O")]
    if fps is not None:
        dtype.append(("fps", "O"))
    if pxpermm is not None:
        dtype.append(("pxpermm", "O"))
    trx = np.empty((1, len(tracks)), dtype=dtype)
    for i, (first, x, y) in enumerate(tracks):
        trx[0, i]["x"] = np.asarray(x, dtype=float).reshape(1, -1)
        trx[0, i]["y"] = np.asarray(y, dtype=float).reshape(1, -1)
        trx[0, i]["firstframe"] = np.array([[first]])
        trx[0, i]["endframe"] = np.array([[first + len(x) - 1]])
        trx[0, i]["nframes"] = np.array([[len(x)]])
        if fps is not None:
            trx[0, i]["fps"] = np.array([[fps]])
        if pxpermm is not None:
            v = pxpermm[i] if isinstance(pxpermm, list) else pxpermm
            trx[0, i]["pxpermm"] = np.array([[v]])
    sio.savemat(path, {"trx": trx})
    return path


TRACKS = [
    (1, [10.0, 11.0, 12.0, 13.0], [20.0, 21.0, 22.0, 23.0]),
    (3, [50.0, 51.0], [60.0, 61.0]),
]


def read(path: Path, **options):
    return readers.read_session(path, reader="trx_mat", options={**SIZE, **options})


def test_a_trx_file_is_detected(tmp_path: Path) -> None:
    write_trx(tmp_path / "trx.mat", TRACKS)
    (group,) = scan([tmp_path]).groups
    assert group.best.reader == "trx_mat" and group.best.confidence is Confidence.MEDIUM
    assert TrxMatReader.verification == "synthetic_only"


def test_raw_ctrax_and_ordinary_files_are_not_trx(tmp_path: Path) -> None:
    sio.savemat(tmp_path / "other.mat", {"data": np.zeros((3, 3))})
    sio.savemat(tmp_path / "t.mat", {"trx": np.zeros((1, 1))})  # not a struct
    assert not TrxMatReader.detect(tmp_path)


def test_frames_are_one_based_and_each_track_is_a_slot(tmp_path: Path) -> None:
    s = read(write_trx(tmp_path / "trx.mat", TRACKS))
    assert s.raw_xy.shape == (4, 2, 2)
    assert s.raw_xy[0, 0].tolist() == [10.0, 20.0]
    assert np.isnan(s.raw_xy[1, 1]).all() and s.raw_xy[2, 1].tolist() == [50.0, 60.0]
    assert s.video.fps == 25.0 and not s.has_stable_identities


def test_pxpermm_becomes_pixels_per_cm(tmp_path: Path) -> None:
    s = read(write_trx(tmp_path / "trx.mat", TRACKS, pxpermm=3.5))
    assert s.length_unit == pytest.approx(35.0)


@pytest.mark.parametrize("value", [1.0, 0.0, float("nan")])
def test_an_uncalibrated_default_is_not_a_scale(tmp_path: Path, value: float) -> None:
    assert read(write_trx(tmp_path / "trx.mat", TRACKS, pxpermm=value)).length_unit is None


def test_no_pxpermm_means_no_scale(tmp_path: Path) -> None:
    assert read(write_trx(tmp_path / "trx.mat", TRACKS)).length_unit is None


def test_tracks_that_disagree_on_the_scale_give_none_and_a_note(tmp_path: Path) -> None:
    s = read(write_trx(tmp_path / "trx.mat", TRACKS, pxpermm=[3.0, 4.0]))
    assert s.length_unit is None and "pxpermm" in (s.raw_attrs or {})


def test_the_frame_rate_comes_from_the_file_or_must_be_given(tmp_path: Path) -> None:
    f = write_trx(tmp_path / "trx.mat", TRACKS, fps=None)
    with pytest.raises(Track2DataError):
        read(f)
    assert read(f, fps=30.0).video.fps == 30.0


def test_top_n_keeps_the_longest(tmp_path: Path) -> None:
    s = read(write_trx(tmp_path / "trx.mat", TRACKS), top_n=1)
    assert s.n_animals == 1 and s.raw_xy[0, 0].tolist() == [10.0, 20.0]


def test_positions_outside_the_frame_are_refused(tmp_path: Path) -> None:
    with pytest.raises(Track2DataError):
        read(write_trx(tmp_path / "trx.mat", TRACKS), height_px=21, width_px=640)


def test_frame_numbers_that_disagree_with_the_positions_are_refused(tmp_path: Path) -> None:
    f = write_trx(tmp_path / "trx.mat", TRACKS)
    d = sio.loadmat(f)
    d["trx"][0, 0]["endframe"] = np.array([[9]])
    sio.savemat(f, d)
    with pytest.raises(Track2DataError):
        read(f)


def test_the_frame_size_must_be_given(tmp_path: Path) -> None:
    with pytest.raises(Track2DataError):
        readers.read_session(write_trx(tmp_path / "trx.mat", TRACKS), reader="trx_mat", options={})

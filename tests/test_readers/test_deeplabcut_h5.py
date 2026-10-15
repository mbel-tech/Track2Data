"""The DeepLabCut ``.h5`` reader: pandas ``table`` files, labels decoded without running code.

Files are written by ``tests/support/dlc.write_dlc_h5`` (h5py alone, in the layout PyTables gives
pandas; one test checks pandas itself reads them back). The real sample is exercised by the
opt-in suite in ``tests/real_samples``.
"""

from __future__ import annotations

import pickle
from pathlib import Path

import h5py
import numpy as np
import pytest

from tests.support.dlc import random_pose, write_dlc_csv, write_dlc_h5
from tests.support.sleap import random_tracks, write_sleap_analysis
from track2data import readers
from track2data.core.errors import Track2DataError
from track2data.readers.detection import Confidence
from track2data.readers.scan import scan

BODYPARTS = ["snout", "ear", "tail"]
VIDEO = {"fps": 30.0, "width_px": 640, "height_px": 480}


def pair(tmp_path: Path, *, n_animals: int = 1, seed: int = 0):
    """The same pose written as CSV and as h5 (with likelihoods, one NaN cell)."""
    xy = random_pose(40, n_animals, len(BODYPARTS), seed=seed)
    xy[3, 0, 1] = np.nan
    lik = np.random.default_rng(seed).uniform(0.7, 1.0, size=xy.shape[:3])
    individuals = [f"mouse{i}" for i in range(n_animals)] if n_animals > 1 else None
    kw = {"bodyparts": BODYPARTS, "individuals": individuals}
    csv = write_dlc_csv(tmp_path / "csv" / "trial.csv", xy, lik, **kw)
    h5 = write_dlc_h5(tmp_path / "h5" / "trial.h5", xy, lik, **kw)
    return csv, h5


def read(path: Path, reader: str = "deeplabcut_h5", **options):
    return readers.read_session(path, reader=reader, options={**VIDEO, **options})


def test_dlc_h5_matches_the_csv_reader_on_the_same_pose(tmp_path: Path) -> None:
    csv, h5 = pair(tmp_path)
    a, b = read(csv, "deeplabcut"), read(h5)
    np.testing.assert_allclose(a.raw_xy, b.raw_xy, rtol=1e-12, equal_nan=True)
    assert a.keypoints is not None and b.keypoints is not None
    np.testing.assert_allclose(a.keypoints.xy, b.keypoints.xy, rtol=1e-6, equal_nan=True)
    assert a.keypoints.names == b.keypoints.names
    assert b.reader == "deeplabcut_h5"
    assert b.trajectory_format == "deeplabcut_h5"


def test_a_multi_animal_file_matches_too_and_blocks_may_be_split(tmp_path: Path) -> None:
    xy = random_pose(30, 2, 3)
    lik = np.random.default_rng(1).uniform(0.7, 1.0, size=xy.shape[:3])
    kw = {"bodyparts": BODYPARTS, "individuals": ["m1", "m2"]}
    csv = write_dlc_csv(tmp_path / "a.csv", xy, lik, **kw)
    h5 = write_dlc_h5(tmp_path / "a.h5", xy, lik, split_blocks=True, **kw)
    a, b = read(csv, "deeplabcut"), read(h5)
    np.testing.assert_allclose(a.raw_xy, b.raw_xy, rtol=1e-12, equal_nan=True)
    assert b.identities_labels == ["m1", "m2"]


def test_an_h5_and_csv_pair_is_one_session(tmp_path: Path) -> None:
    csv, h5 = pair(tmp_path)
    folder = tmp_path / "both"
    folder.mkdir()
    (folder / "trial.csv").write_bytes(csv.read_bytes())
    (folder / "trial.h5").write_bytes(h5.read_bytes())
    result = scan([folder])
    sessions = [
        (d.reader, s.source.name) for g in result.groups for d in g.detections for s in d.sessions
    ]
    assert sessions == [("deeplabcut", "trial.csv")]


def test_an_h5_alone_is_detected_with_medium_confidence(tmp_path: Path) -> None:
    _, h5 = pair(tmp_path)
    (group,) = scan([h5.parent]).groups
    assert group.best.reader == "deeplabcut_h5"
    assert group.best.confidence is Confidence.MEDIUM
    assert [s.source for s in group.best.sessions] == [h5]


def test_scan_never_unpickles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, h5 = pair(tmp_path)

    def boom(*args, **kwargs):
        raise AssertionError("the scan unpickled something")

    monkeypatch.setattr(pickle, "loads", boom)
    monkeypatch.setattr(pickle, "load", boom)
    from track2data.readers import deeplabcut_h5

    monkeypatch.setattr(deeplabcut_h5, "_LabelUnpickler", boom)
    (group,) = scan([h5.parent]).groups
    assert group.best.reader == "deeplabcut_h5"


class _Evil:
    def __reduce__(self):
        import os

        return (os.system, ("touch " + str(MARKER),))


MARKER = Path("/tmp/claude-evil-marker-should-not-exist")


def test_a_hostile_pickled_label_is_refused_with_a_coded_error(tmp_path: Path) -> None:
    MARKER.unlink(missing_ok=True)
    xy = random_pose(10, 1, 3)
    h5 = write_dlc_h5(
        tmp_path / "evil.h5",
        xy,
        bodyparts=BODYPARTS,
        label_pickle=pickle.dumps([(1, [_Evil()])], protocol=0),
    )
    with pytest.raises(Track2DataError) as caught:
        read(h5)
    assert caught.value.code == "DLCH5_LABELS_REFUSED"
    assert caught.value.remediation
    assert not MARKER.exists()


def test_an_oversized_label_attribute_is_refused_unread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from track2data.readers import deeplabcut_h5

    _, h5 = pair(tmp_path)
    monkeypatch.setattr(deeplabcut_h5, "_MAX_LABEL_BYTES", 10)
    with pytest.raises(Track2DataError) as caught:
        read(h5)
    assert caught.value.code == "DLCH5_LABELS_REFUSED"


def test_sleap_and_dlc_h5_never_both_claim_a_file(tmp_path: Path) -> None:
    _, dlc = pair(tmp_path)
    tracks = random_tracks(30, 2, 3)
    sleap = write_sleap_analysis(
        tmp_path / "s" / "x.analysis.h5",
        tracks,
        node_names=BODYPARTS,
        track_names=["a", "b"],
    )
    claims: dict[Path, set[str]] = {}
    for folder in (dlc.parent, sleap.parent):
        for group in scan([folder]).groups:
            for d in group.detections:
                for s in d.sessions:
                    claims.setdefault(s.source, set()).add(d.reader)
    assert claims == {dlc: {"deeplabcut_h5"}, sleap: {"sleap_analysis"}}


def test_a_tracks_group_h5_is_refused_with_a_remediation(tmp_path: Path) -> None:
    path = tmp_path / "video_el.h5"
    with h5py.File(path, "w") as handle:
        handle.create_group("tracks")
    with pytest.raises(Track2DataError) as caught:
        read(path)
    assert caught.value.code == "DLCH5_LAYOUT_UNSUPPORTED"
    assert "tracklet" in str(caught.value)


def test_a_file_that_is_not_hdf5_is_unreadable(tmp_path: Path) -> None:
    path = tmp_path / "x.h5"
    path.write_bytes(b"not hdf5")
    with pytest.raises(Track2DataError) as caught:
        read(path)
    assert caught.value.code == "DLCH5_UNREADABLE"


def test_a_table_without_likelihood_is_not_a_prediction_file(tmp_path: Path) -> None:
    _csv, h5 = pair(tmp_path)
    # Replace the pickled labels so no column is a likelihood.
    labels = [("scorer", "a", "x"), ("scorer", "a", "y")]
    with h5py.File(h5, "r+") as handle:
        group = handle["df_with_missing"]
        table = group["table"]
        del group["table"]
        data = np.zeros(2, dtype=[("index", "<i8"), ("values_block_0", "<f8", (2,))])
        data["index"] = [0, 1]
        out = group.create_dataset("table", data=data)
        out.attrs["index_kind"] = table.attrs["index_kind"]
        out.attrs["values_block_0_kind"] = np.bytes_(pickle.dumps(labels, protocol=0))
        group.attrs["non_index_axes"] = np.bytes_(pickle.dumps([(1, labels)], protocol=0))
    with pytest.raises(Track2DataError) as caught:
        read(h5)
    assert caught.value.code == "DLCH5_LAYOUT_UNSUPPORTED"


def test_the_helper_writes_what_pandas_reads(tmp_path: Path) -> None:
    pd = pytest.importorskip("pandas")
    pytest.importorskip("tables")
    _, h5 = pair(tmp_path)
    frame = pd.read_hdf(h5, key="df_with_missing")
    assert frame.shape == (40, 9)
    assert frame.columns.nlevels == 3
    read_back = read(h5)
    np.testing.assert_allclose(
        read_back.keypoints.xy[:, 0, 0, 0],  # type: ignore[union-attr]
        frame[(frame.columns[0][0], "snout", "x")].to_numpy(),
    )


def test_a_pandas_written_file_is_read_without_pytables(tmp_path: Path) -> None:
    pd = pytest.importorskip("pandas")
    pytest.importorskip("tables")
    columns = pd.MultiIndex.from_product(
        [["DLC_scorer"], BODYPARTS, ["x", "y", "likelihood"]],
        names=["scorer", "bodyparts", "coords"],
    )
    values = np.random.default_rng(0).uniform(0, 100, size=(25, 9))
    path = tmp_path / "pandas_made.h5"
    pd.DataFrame(values, columns=columns).to_hdf(
        path, key="df_with_missing", format="table", mode="w"
    )
    session = read(path, likelihood_cutoff=0.0)
    assert session.n_frames == 25
    assert session.keypoints is not None and session.keypoints.names == BODYPARTS

"""Reader-contract tests.

Each case arranges real fixture files into a session folder, finds the registered
Track2Data reader that claims it, reads it, and checks the resulting Session
against an independent oracle (oracles.py).

While no reader claims a folder the test is reported as XFAIL ("reader not
implemented"), so the suite is green today and every case turns into a live test
the moment a reader is registered. Nothing here asserts a policy decision; where
a choice is open (how to reduce keypoints, where fps comes from) the tests check
only outcomes that every reasonable policy must satisfy. The open choices are
listed in README.md.
"""
from __future__ import annotations

import hashlib
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pytest

pytest.importorskip("track2data", reason="install Track2Data or put it on PYTHONPATH to run contract tests")

from tests.real_samples import oracles as O
from tests.real_samples.fixtures import build_folder, fetch, provide_video_info
from track2data import readers as registry
from track2data.core.errors import Track2DataError
from track2data.core.models import Session

pytestmark = pytest.mark.contract

OLD = [f"2602_ISA3080_Low_5_fish{i}.npz" for i in range(13)]
LOC_MEMBERS = [f"locusts-noqr_20250117_5_id{i}.npz" for i in range(5)]
H, W = 2160, 3840            # height is verified (Ctrax flip); width 3840 is assumed (4K) and only echoed back


@dataclass
class Case:
    id: str
    names: list[str]                       # fixtures copied into the session folder
    primary: str                           # file that is emptied/truncated in the error-path tests
    n_frames: int
    n_animals: int
    video: dict[str, float]                # what Session.video must report
    check: str                             # 'aligned' | 'frame_set' | 'corr'
    oracle: Callable[[], Any] | None = None
    supplied: dict[str, Any] = field(default_factory=dict)   # only what the FORMAT does not record
    unzip: str | None = None
    stable: bool | None = None             # expected has_stable_identities; None = not asserted
    binary: bool = False                   # truncation test applies
    n_frames_tol: int = 0


def _o(fn, *names, **kw):
    return lambda: fn(*[fetch(n) for n in names], **kw)


def _trex_members(zip_name):
    return lambda: O.oracle_trex_pose(O.trex_zip_members(fetch(zip_name)), tol=40.0)


CASES = [
    Case("dlc_single_animal_h5", ["DLC_single-mouse_EPM.predictions.h5"], "DLC_single-mouse_EPM.predictions.h5",
         18485, 1, dict(fps=30.0, width_px=1000, height_px=1000), "aligned",
         _o(O.oracle_dlc, "DLC_single-mouse_EPM.predictions.h5"),
         supplied=dict(fps=30.0, width_px=1000, height_px=1000), stable=True, binary=True),
    Case("dlc_two_mice_csv", ["DLC_two-mice.predictions.csv"], "DLC_two-mice.predictions.csv",
         59999, 2, dict(fps=100.0, width_px=1000, height_px=1000), "aligned",
         _o(O.oracle_dlc, "DLC_two-mice.predictions.csv"),
         supplied=dict(fps=100.0, width_px=1000, height_px=1000), stable=True),
    Case("lightning_pose_eks_csv", ["EKS_IBL-paw_multicam_left.predictions.csv"], "EKS_IBL-paw_multicam_left.predictions.csv",
         997, 1, dict(fps=60.0, width_px=1000, height_px=1000), "aligned",
         _o(O.oracle_dlc, "EKS_IBL-paw_multicam_left.predictions.csv"),
         supplied=dict(fps=60.0, width_px=1000, height_px=1000), stable=True),
    Case("sleap_named_tracks", ["SLEAP_three-mice_Aeon_mixed-labels.analysis.h5"], "SLEAP_three-mice_Aeon_mixed-labels.analysis.h5",
         601, 3, dict(fps=50.0, width_px=1000, height_px=1000), "aligned",
         _o(O.oracle_sleap, "SLEAP_three-mice_Aeon_mixed-labels.analysis.h5"),
         supplied=dict(fps=50.0, width_px=1000, height_px=1000), stable=True, binary=True),
    Case("sleap_no_tracks", ["SLEAP_single-mouse_EPM.analysis.h5"], "SLEAP_single-mouse_EPM.analysis.h5",
         18485, 1, dict(fps=30.0, width_px=1000, height_px=1000), "aligned",
         _o(O.oracle_sleap, "SLEAP_single-mouse_EPM.analysis.h5"),
         supplied=dict(fps=30.0, width_px=1000, height_px=1000), binary=True),
    Case("trex_new_export", ["TRex_five-locusts.zip"], LOC_MEMBERS[0], 2845, 5,
         dict(fps=30.0, width_px=4096, height_px=3000), "aligned", _trex_members("TRex_five-locusts.zip"),
         unzip="TRex_five-locusts.zip", stable=True, binary=True),
]
CASES += [
    Case("trex_old_export", OLD, OLD[0], 12024, 13, dict(fps=25.0, width_px=W, height_px=H), "aligned",
         lambda: O.oracle_trex_point(O.trex_npz_files([fetch(n) for n in OLD])),
         supplied=dict(width_px=W, height_px=H), stable=True, binary=True),
    Case("animalta_fixed_csv", ["2602_ISA3080_Low_5_Coordinates.csv"], "2602_ISA3080_Low_5_Coordinates.csv",
         12033, 12, dict(fps=25.0, width_px=W, height_px=H), "aligned",
         _o(O.oracle_animalta, "2602_ISA3080_Low_5_Coordinates.csv"),
         supplied=dict(width_px=W, height_px=H), stable=True),
    Case("ctrax_raw_mat", ["2602_ISA3080_Low_5.mat"], "2602_ISA3080_Low_5.mat", 12033, 193,
         dict(fps=25.0, width_px=W, height_px=H), "frame_set", None,
         supplied=dict(width_px=W, height_px=H), stable=False, binary=True),
    Case("toxtrac_realspace", ["Tracking_RealSpace_1.txt", "Stats_1.txt", "FrozenEvents_1.txt"], "Tracking_RealSpace_1.txt",
         18034, 1, dict(fps=29.8568, width_px=1920, height_px=1080), "corr", None, stable=True, n_frames_tol=12),
]


# ------------------------------------------------------------------ plumbing
def _tree_hash(folder: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(folder.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(folder)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def _claimants(folder: Path) -> list[type]:
    found = []
    for cls in registry._REGISTRY:          # private on purpose: detect_reader() hides ambiguity
        try:
            if cls.detect(folder):
                found.append(cls)
        except Exception:
            pass
    return found


@dataclass
class Loaded:
    case: Case
    folder: Path
    claimants: list[type]
    session: Session | None
    error: BaseException | None
    hash_before: str
    hash_after: str


@pytest.fixture(scope="module", params=CASES, ids=lambda c: c.id)
def loaded(request, tmp_path_factory) -> Loaded:
    case: Case = request.param
    folder = build_folder(tmp_path_factory.mktemp(case.id) / "session", case.names, case.unzip)
    if case.supplied:
        provide_video_info(folder, case.supplied)
    before = _tree_hash(folder)
    claimants = _claimants(folder)
    session = error = None
    if claimants:
        try:
            session = registry.detect_reader(folder)().read(folder)
        except BaseException as exc:         # surfaced by the tests, not swallowed
            error = exc
    return Loaded(case, folder, claimants, session, error, before, _tree_hash(folder))


def _need_reader(ld: Loaded) -> Session:
    if not ld.claimants:
        pytest.xfail(f"no registered reader claims the '{ld.case.id}' folder yet")
    if ld.error is not None:
        raise ld.error
    return ld.session


# ------------------------------------------------------------------ contract tests
def test_exactly_one_reader_claims_the_folder(loaded):
    if not loaded.claimants:
        pytest.xfail(f"no registered reader claims the '{loaded.case.id}' folder yet")
    assert len(loaded.claimants) == 1, f"ambiguous: {[c.name for c in loaded.claimants]}"


def test_session_is_well_formed(loaded):
    s, c = _need_reader(loaded), loaded.case
    assert isinstance(s, Session)
    assert s.folder == loaded.folder and s.reader and s.session_id
    assert s.raw_xy.dtype == np.float64 and s.raw_xy.ndim == 3 and s.raw_xy.shape[2] == 2
    assert not np.isinf(s.raw_xy).any(), "infinity must be converted to NaN"
    assert s.raw_xy.shape[1] == s.n_animals == c.n_animals
    assert abs(s.n_frames - c.n_frames) <= c.n_frames_tol
    assert s.video.n_frames == s.n_frames


def test_video_info_is_taken_from_the_file_or_the_supplied_metadata_never_invented(loaded):
    s, c = _need_reader(loaded), loaded.case
    assert s.video.fps == pytest.approx(c.video["fps"], rel=5e-3)
    assert (s.video.width_px, s.video.height_px) == (c.video["width_px"], c.video["height_px"])


def test_positions_match_the_independent_oracle(loaded):
    s, c = _need_reader(loaded), loaded.case
    if c.check == "aligned":
        orc = c.oracle()
        xy = orc.xy
        assert s.raw_xy.shape == (xy.shape[0], xy.shape[1], 2)
        no_data = np.isnan(xy).all(axis=(2, 3))
        finite = np.isfinite(s.raw_xy[..., 0])
        assert not (finite & no_data).any(), "reader invented positions where the source has none"
        assert finite.sum() >= 0.9 * (~no_data).sum(), "reader dropped most of the available positions"
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            lo, hi = np.nanmin(xy, axis=2), np.nanmax(xy, axis=2)
        inside = ((s.raw_xy >= lo - orc.tol) & (s.raw_xy <= hi + orc.tol)).all(axis=-1)
        assert not (finite & ~inside).any(), "positions fall outside the animal's own keypoints"

        # Temporal alignment: the reader's speed series must line up with the oracle's at lag 0.
        # Comparing speeds (not positions) is blind to HOW keypoints are reduced to one point.
        def speeds(p):
            return np.linalg.norm(np.diff(p, axis=0), axis=-1)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            sr, so = speeds(s.raw_xy), speeds(np.nanmean(xy, axis=2))

        def corr_at(lag: int) -> float:
            a = sr[max(0, -lag): len(sr) - max(0, lag)].ravel()
            b = so[max(0, lag): len(so) - max(0, -lag)].ravel()
            ok = np.isfinite(a) & np.isfinite(b)
            return float(np.corrcoef(a[ok], b[ok])[0, 1])

        assert corr_at(0) > 0.5, "reader and oracle disagree on how fast the animals move"
        assert corr_at(0) >= max(corr_at(-1), corr_at(1)) - 0.01, "frames are shifted by one"
    elif c.check == "frame_set":
        m = O.read_ctrax(fetch(c.names[0]))
        for f in (0, 3000, 9000, 12032):
            want = O.ctrax_points(m, f, height=H)
            got = s.raw_xy[f][np.isfinite(s.raw_xy[f]).all(axis=1)]
            assert len(got) == len(want)
            assert O.median_nn(got, want) < 1e-6 and O.median_nn(want, got) < 1e-6
    elif c.check == "corr":
        df = O.read_toxtrac(fetch("Tracking_RealSpace_1.txt"))
        pts = s.raw_xy[:, 0, :]
        fin = np.isfinite(pts).all(axis=1)
        assert int(fin.sum()) == len(df) == 17811, "absent rows must be NaN frames, present rows must all land"
        assert np.corrcoef(pts[fin, 0], df["Pos. X (mm)"])[0, 1] > 0.9999
        assert np.corrcoef(pts[fin, 1], df["Pos. Y (mm)"])[0, 1] > 0.9999, "y axis must not be flipped or swapped"


def test_identity_claim_is_honest(loaded):
    s, c = _need_reader(loaded), loaded.case
    if c.stable is None:
        pytest.skip("source has no identity information to assert on")
    assert s.has_stable_identities is c.stable


def test_reading_does_not_modify_the_input_folder(loaded):
    """FR-IMP-5: readers must not modify any file inside the session folder."""
    _need_reader(loaded)
    assert loaded.hash_after == loaded.hash_before


# ------------------------------------------------------------------ error paths
def _damaged(ld: Loaded, tmp_path: Path, how: str) -> Path:
    folder = tmp_path / how
    shutil.copytree(ld.folder, folder)
    target = folder / ld.case.primary
    data = target.read_bytes()
    target.write_bytes(b"" if how == "empty" else data[: len(data) // 2])
    return folder


def _assert_clean_failure(folder: Path):
    """Either no reader claims the damaged folder, or reading raises a structured error."""
    try:
        cls = registry.detect_reader(folder)
        if cls is None:
            return
        cls().read(folder)
    except Track2DataError as exc:
        assert exc.code != "UNKNOWN" and exc.remediation, "structured error needs a code and a remediation hint"
        return
    pytest.fail("a damaged file was read without any error")


def test_empty_primary_file_is_rejected_cleanly(loaded, tmp_path):
    _need_reader(loaded)
    _assert_clean_failure(_damaged(loaded, tmp_path, "empty"))


def test_truncated_binary_file_is_rejected_cleanly(loaded, tmp_path):
    _need_reader(loaded)
    if not loaded.case.binary:
        pytest.skip("text format: a truncated file can still be a valid shorter file")
    _assert_clean_failure(_damaged(loaded, tmp_path, "truncated"))

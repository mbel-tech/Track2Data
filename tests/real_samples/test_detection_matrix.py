"""Which reader claims which real tracker output, and none that it should not.

A reader that over-claims is worse than one that does not exist: it offers the wrong software to
the user, who may press Add. Each real case folder is scanned and the readers that report a
detection are compared with the one expected (``None``: no reader can read it yet). A new reader
adds its row here; a row that changes is a decision, not an accident.
"""

from __future__ import annotations

import pytest

pytest.importorskip("track2data", reason="install Track2Data or put it on PYTHONPATH")

from tests.real_samples.fixtures import build_folder
from tests.real_samples.test_reader_contract import CASES, Case
from track2data.readers.scan import scan

pytestmark = pytest.mark.contract

#: case id -> the reader that must claim it (and no other). None = nothing can read it yet.
EXPECTED: dict[str, str | None] = {
    "dlc_single_animal_h5": None,  # .h5: arrives with the G-H5 decision
    "dlc_two_mice_csv": "deeplabcut",
    "lightning_pose_eks_csv": "deeplabcut",
    "sleap_named_tracks": "sleap_analysis",
    "sleap_no_tracks": "sleap_analysis",
    "trex_new_export": None,
    "trex_old_export": None,
    "animalta_fixed_csv": None,
    "ctrax_raw_mat": "ctrax_mat",
    "toxtrac_realspace": None,
}


def test_every_case_has_a_row() -> None:
    assert {c.id for c in CASES} == set(EXPECTED)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_only_the_expected_reader_claims_the_folder(case: Case, tmp_path) -> None:
    folder = build_folder(tmp_path / "session", case.names, case.unzip)
    result = scan([folder])
    claimed = {d.reader for g in result.groups for d in g.detections}
    expected = EXPECTED[case.id]
    assert claimed == ({expected} if expected else set()), (
        f"{case.id}: readers that claim it are {sorted(claimed)}, expected {expected}"
    )

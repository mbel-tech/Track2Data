"""A bare idtracker.ai export records no video size; the reader takes it as options (F2/F7).

Precedence is trajectory file, then session.json, then the options: the options fill gaps and
never override what the tracker itself recorded.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from track2data.core.errors import DataValidationError, ImportError_
from track2data.readers import IDTrackerAiReader, read_session

TRAJ = "x1,y1,x2,y2\n1,2,3,4\n2,3,4,5\n3,4,5,6\n"
OPTS = {"width_px": 640, "height_px": 480, "fps": 25.0}


def _bare(root: Path) -> Path:
    d = root / "trajectories" / "trajectories_csv"
    d.mkdir(parents=True)
    (d / "trajectories.csv").write_text(TRAJ)
    return root


def test_reader_declares_optional_video_info_options() -> None:
    by_name = {p.name: p for p in IDTrackerAiReader.parameters}
    assert {"fps", "width_px", "height_px"} <= set(by_name)
    assert not any(by_name[n].required for n in ("fps", "width_px", "height_px"))


def test_options_supply_a_missing_video_size_and_fps(tmp_path: Path) -> None:
    session = read_session(_bare(tmp_path), options=OPTS)
    assert (session.video.width_px, session.video.height_px) == (640, 480)
    assert session.video.fps == 25.0


def test_without_options_or_session_json_it_is_still_refused(tmp_path: Path) -> None:
    with pytest.raises(DataValidationError) as err:
        read_session(_bare(tmp_path))
    assert err.value.code == "IDT_DICT_MISSING_KEY"
    assert "'fps'" in (err.value.remediation or "")


def test_session_json_wins_over_options(tmp_path: Path) -> None:
    root = _bare(tmp_path)
    (root / "session.json").write_text(
        json.dumps({"width": 1000, "height": 900, "frames_per_second": 30})
    )
    session = read_session(root, options=OPTS)
    assert (session.video.width_px, session.video.height_px) == (1000, 900)
    assert session.video.fps == 30.0


def test_an_invalid_option_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ImportError_) as err:
        read_session(_bare(tmp_path), options={**OPTS, "width_px": 0})
    assert err.value.code == "READER_OPTION_INVALID"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (640, True),
        (640.5, True),
        ("640", True),
        (np.int64(640), True),
        (np.float32(25.0), True),
        (True, False),
        (0, False),
        (-3, False),
        (float("nan"), False),
        (float("inf"), False),
        ("wide", False),
        (None, False),
    ],
)
def test_the_video_size_check_agrees_with_the_normaliser(value: object, expected: bool) -> None:
    """A session.json width of "640" is accepted by the normaliser, so it must also count as a
    video size already given (otherwise a pickle refusal wrongly asks for width_px/height_px)."""
    from track2data.readers.idtrackerai.normaliser import Normaliser
    from track2data.readers.idtrackerai.reader import _is_positive_number

    assert _is_positive_number(value) is expected
    if not isinstance(value, bool):
        try:
            Normaliser._require_positive_number("width", value, None)
            normaliser_accepts = True
        except DataValidationError:
            normaliser_accepts = False
        assert normaliser_accepts is expected

"""Reader advisories: what a project's sessions rest on, said before the run, never blocking.

Two things follow from *which reader* produced a session, and neither is visible in the numbers:
a reader written from documentation alone may be wrong in ways only real output reveals, and the
default body-length calibration needs a body length that most trackers do not report.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import pytest

from track2data import readers
from track2data.core.models import Session
from track2data.core.session_consistency import SessionSummary
from track2data.readers.advisories import reader_advisories
from track2data.readers.base import SessionReader


class _Stub(SessionReader):
    @classmethod
    def detect(cls, folder: Path) -> bool:
        return False

    def read(self, folder: Path, *, allow_pickle: bool = False) -> Session:
        raise NotImplementedError


class UnverifiedReader(_Stub):
    name = "adv_unverified"
    display_name: ClassVar[str] = "Adv tool"
    verification = "synthetic_only"


class OtherUnverifiedReader(_Stub):
    name = "adv_other"
    verification = "synthetic_only"


class VerifiedReader(_Stub):
    name = "adv_verified"
    display_name: ClassVar[str] = "Verified tool"
    verification = "real_sample"


@pytest.fixture(autouse=True)
def registered() -> Iterator[None]:
    for cls in (UnverifiedReader, OtherUnverifiedReader, VerifiedReader):
        readers.register(cls)
    yield
    for cls in (UnverifiedReader, OtherUnverifiedReader, VerifiedReader):
        readers._REGISTRY.remove(cls)


def _summary(
    session_id: str,
    reader: str,
    *,
    mode: str = "scalar",
    has_body_length: bool = True,
) -> SessionSummary:
    return SessionSummary(
        session_id=session_id,
        reader=reader,
        fps=25.0,
        n_frames=100,
        n_animals=2,
        width_px=100,
        height_px=80,
        length_unit=None,
        calibration_mode=mode,
        has_body_length=has_body_length,
    )


class TestAnUnverifiedReader:
    def test_is_flagged_once_naming_the_reader_and_its_sessions(self) -> None:
        advisories = reader_advisories(
            [_summary("a", "adv_unverified"), _summary("b", "adv_unverified")]
        )
        assert len(advisories) == 1
        text = advisories[0]
        assert "adv_unverified" in text
        assert "Adv tool" in text
        assert "a, b" in text
        assert "real tracker output" in text

    def test_each_unverified_reader_gets_its_own_advisory(self) -> None:
        advisories = reader_advisories(
            [_summary("a", "adv_unverified"), _summary("b", "adv_other")]
        )
        assert len(advisories) == 2

    def test_a_reader_without_a_display_name_is_named_by_its_registered_name(self) -> None:
        (advisory,) = reader_advisories([_summary("a", "adv_other")])
        assert "adv_other" in advisory

    def test_a_long_list_of_sessions_is_cut_short_and_counted(self) -> None:
        ids = [f"s{i}" for i in range(10)]
        (advisory,) = reader_advisories([_summary(i, "adv_unverified") for i in ids])
        assert "s0, s1, s2, s3" in advisory
        assert "s9" not in advisory
        assert "+6 more" in advisory


class TestAReaderThatIsNotFlagged:
    def test_one_tested_against_real_output(self) -> None:
        assert reader_advisories([_summary("a", "adv_verified")]) == []

    def test_the_built_in_idtracker_readers(self) -> None:
        sessions = [_summary("a", "idtrackerai"), _summary("b", "idtrackerai_v5")]
        assert reader_advisories(sessions) == []

    def test_one_that_is_not_registered_because_nothing_is_known_about_it(self) -> None:
        assert reader_advisories([_summary("a", "no_such_reader")]) == []

    def test_an_empty_project(self) -> None:
        assert reader_advisories([]) == []


class TestBodyLengthCalibrationWithoutABodyLength:
    def test_names_the_sessions_that_will_fall_back_to_pixels(self) -> None:
        advisories = reader_advisories(
            [
                _summary("lacks_bl", "adv_verified", mode="bodylength", has_body_length=False),
                _summary("has_bl", "adv_verified", mode="bodylength", has_body_length=True),
            ]
        )
        assert len(advisories) == 1
        text = advisories[0]
        assert "body length" in text
        assert "lacks_bl" in text
        assert "has_bl" not in text
        assert "pixels" in text
        assert "'scalar'" in text
        assert "'session'" in text

    def test_does_not_nest_the_reader_and_session_lists_in_parentheses(self) -> None:
        (advisory,) = reader_advisories(
            [_summary("a", "adv_verified", mode="bodylength", has_body_length=False)]
        )
        assert "(Verified tool: a)" not in advisory
        assert "Verified tool: a" in advisory

    def test_is_silent_under_any_other_calibration_mode(self) -> None:
        for mode in ("scalar", "session"):
            assert (
                reader_advisories(
                    [_summary("a", "adv_verified", mode=mode, has_body_length=False)]
                )
                == []
            )

    def test_is_silent_when_every_session_has_a_body_length(self) -> None:
        assert (
            reader_advisories([_summary("a", "adv_verified", mode="bodylength")]) == []
        )

    def test_describes_sessions_of_a_reader_nothing_is_known_about_by_the_reader_name(
        self,
    ) -> None:
        (advisory,) = reader_advisories(
            [_summary("a", "no_such_reader", mode="bodylength", has_body_length=False)]
        )
        assert "no_such_reader" in advisory

    def test_says_which_reader_each_session_came_from(self) -> None:
        advisories = reader_advisories(
            [
                _summary("a", "adv_verified", mode="bodylength", has_body_length=False),
                _summary("b", "adv_verified", mode="bodylength", has_body_length=False),
                _summary("c", "adv_other", mode="bodylength", has_body_length=False),
            ]
        )
        (body_length,) = [text for text in advisories if "body length" in text]
        assert "Verified tool: a, b" in body_length
        assert "adv_other: c" in body_length

    def test_is_one_advisory_however_many_readers_are_involved(self) -> None:
        advisories = reader_advisories(
            [
                _summary("a", "adv_verified", mode="bodylength", has_body_length=False),
                _summary("c", "adv_other", mode="bodylength", has_body_length=False),
            ]
        )
        # the second reader is also unverified, which is a separate advisory
        assert len([text for text in advisories if "body length" in text]) == 1
        assert len([text for text in advisories if "real tracker output" in text]) == 1


def test_the_summary_records_whether_the_session_carries_a_body_length() -> None:
    import numpy as np

    from track2data.core.models import VideoInfo

    def session(body_length: np.ndarray | None) -> Session:
        return Session(
            session_id="s",
            folder=Path("/tmp/s"),
            reader="adv_verified",
            video=VideoInfo(path=None, fps=25.0, n_frames=3, width_px=10, height_px=10),
            n_animals=1,
            trajectory_variant="with_gaps",
            has_stable_identities=True,
            raw_xy=np.zeros((3, 1, 2)),
            body_length_px=body_length,
        )

    with_it = SessionSummary.from_session(session(np.array([12.0])), calibration_mode="x")
    without = SessionSummary.from_session(session(None), calibration_mode="x")
    assert with_it.has_body_length is True
    assert without.has_body_length is False


def _native(session_id: str, reader: str, *, unit: str = "tu", reported: str | None = "mm"):
    return SessionSummary(
        session_id=session_id,
        reader=reader,
        fps=25.0,
        n_frames=100,
        n_animals=2,
        width_px=0,
        height_px=0,
        length_unit=None,
        calibration_mode="bodylength",
        has_body_length=False,
        coordinate_unit=unit,
        reported_unit=reported,
    )


class TestSessionsWithNoPixelFrame:
    def test_an_unconfirmed_unit_is_said_once_with_what_the_tool_calls_it(self) -> None:
        advisories = reader_advisories(
            [_native("a", "adv_verified"), _native("b", "adv_verified")]
        )
        assert len(advisories) == 1
        text = advisories[0]
        assert "no pixel frame" in text and "*_tu" in text and "'mm'" in text
        assert "a, b" in text and "Verified tool" in text

    def test_it_never_says_the_columns_stay_in_pixels(self) -> None:
        text = " ".join(reader_advisories([_native("a", "adv_verified")]))
        assert "stay in pixels" not in text

    def test_a_confirmed_unit_needs_no_advisory(self) -> None:
        assert reader_advisories([_native("a", "adv_verified", unit="mm")]) == []

    def test_a_tool_that_does_not_say_what_its_units_are_is_not_quoted(self) -> None:
        (text,) = reader_advisories([_native("a", "adv_verified", reported=None)])
        assert "tool calls them" not in text

    def test_pixel_sessions_beside_them_keep_their_own_advisory(self) -> None:
        advisories = reader_advisories(
            [
                _native("nat1", "adv_verified"),
                _summary("pix1", "adv_verified", mode="bodylength", has_body_length=False),
            ]
        )
        assert len(advisories) == 2
        body = next(a for a in advisories if "bodylength" in a)
        assert "pix1" in body and "nat1" not in body

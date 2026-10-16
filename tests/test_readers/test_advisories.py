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


class TestFragmentedSessions:
    @staticmethod
    def _fragmented(session_id: str, fraction: float | None, n_animals: int = 4):
        return SessionSummary(
            session_id=session_id,
            reader="adv_verified",
            fps=25.0,
            n_frames=100,
            n_animals=n_animals,
            width_px=100,
            height_px=80,
            length_unit=None,
            calibration_mode="scalar",
            nan_slot_fraction=fraction,
        )

    def test_a_fragment_heavy_session_gets_an_advisory_that_names_top_n(self) -> None:
        (text,) = reader_advisories([self._fragmented("flies", 0.8)])
        assert "flies" in text and "80%" in text
        assert "top_n" in text
        assert "any animal is missing" in text

    def test_a_summary_built_without_the_new_field_never_warns(self) -> None:
        assert reader_advisories([self._fragmented("x", None)]) == []

    def test_a_single_animal_session_never_warns(self) -> None:
        assert reader_advisories([self._fragmented("x", 0.9, n_animals=1)]) == []

    def test_a_session_below_the_threshold_does_not_warn(self) -> None:
        from track2data.readers.advisories import FRAGMENTED_NAN_FRACTION

        assert reader_advisories([self._fragmented("x", FRAGMENTED_NAN_FRACTION - 0.01)]) == []
        assert reader_advisories([self._fragmented("x", FRAGMENTED_NAN_FRACTION)]) != []

    def test_many_fragmented_sessions_are_truncated_with_plus_n_more(self) -> None:
        (text,) = reader_advisories([self._fragmented(f"s{i}", 0.9) for i in range(7)])
        assert "s0" in text and "s3" in text and "s4" not in text
        assert "+3 more" in text

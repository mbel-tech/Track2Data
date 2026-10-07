"""ConfirmDraft: what a scan found, what the user chose, and the sessions that would be added.

Qt-free on purpose. The confirm dialog and `track2data add` are two thin views over these rules,
so "can I press OK?" has one answer whichever of them asks. A scan result is plain data, so most
of this is tested on hand-built results; the last class runs a real scan.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from track2data.core.models import SessionRef
from track2data.readers.confirm import ConfirmDraft
from track2data.readers.detection import Confidence, Detection, SessionCandidate
from track2data.readers.params import ProposedValue, ReaderParameter
from track2data.readers.scan import FormatGroup, ScanResult

FPS = ReaderParameter(name="fps", label="Frame rate", kind="float", required=True, minimum=1)
SIZE = ReaderParameter(name="width_px", label="Frame width", kind="int", required=True)
KEYPOINT = ReaderParameter(name="keypoint", label="Keypoint", kind="str", default="nose")
ARENA = ReaderParameter(
    name="arena", label="Arena", kind="int", required=True, scope="session"
)


def detection(
    reader: str,
    ids: tuple[str, ...] = ("a", "b"),
    *,
    confidence: Confidence = Confidence.HIGH,
    parameters: tuple[ReaderParameter, ...] = (),
    proposed: dict[str, ProposedValue] | None = None,
    display_name: str | None = None,
) -> Detection:
    return Detection(
        reader=reader,
        display_name=display_name or reader.title(),
        confidence=confidence,
        evidence=(f"{reader} evidence",),
        sessions=tuple(
            SessionCandidate(session_id=i, source=Path("root") / i, warnings=()) for i in ids
        ),
        parameters=parameters,
        proposed=proposed or {},
        verification="synthetic_only",
    )


def result(*groups: tuple[Detection, ...]) -> ScanResult:
    return ScanResult(
        roots=(Path("root"),),
        groups=tuple(FormatGroup(detections=g) for g in groups),
        file_types={},
        truncated=False,
        warnings=(),
        entries=10,
        seconds=0.1,
    )


@pytest.fixture
def plain() -> ConfirmDraft:
    return ConfirmDraft(result((detection("alpha"),)))


class TestWhatItStartsAs:
    def test_the_best_reader_of_the_first_group_is_selected_as_detected(self) -> None:
        draft = ConfirmDraft(result((detection("alpha"), detection("beta"))))
        assert draft.reader == "alpha"
        assert draft.chosen_by == "detected"
        assert draft.confidence is Confidence.HIGH
        assert draft.display_name == "Alpha"
        assert draft.evidence == ("alpha evidence",)

    def test_every_session_is_included_under_the_id_the_scan_gave_it(
        self, plain: ConfirmDraft
    ) -> None:
        assert [(r.session_id, r.included) for r in plain.rows] == [("a", True), ("b", True)]

    def test_the_other_readers_of_the_group_are_listed_as_alternatives(self) -> None:
        draft = ConfirmDraft(
            result(
                (
                    detection("alpha"),
                    detection("beta", confidence=Confidence.LOW, display_name="Beta tool"),
                )
            )
        )
        assert [(a.reader, a.display_name, a.confidence) for a in draft.alternatives] == [
            ("alpha", "Alpha", Confidence.HIGH),
            ("beta", "Beta tool", Confidence.LOW),
        ]

    def test_a_scan_that_found_nothing_has_nothing_to_confirm(self) -> None:
        draft = ConfirmDraft(result())
        assert draft.is_empty
        assert draft.rows == ()
        assert [p.code for p in draft.problems()] == ["NOTHING_SELECTED"]

    def test_the_options_start_from_what_the_scan_could_read_out_of_the_files(self) -> None:
        proposed = {"fps": ProposedValue(value=30.0, source="file")}
        found = detection("alpha", parameters=(FPS, SIZE), proposed=proposed)
        draft = ConfirmDraft(result((found,)))
        assert draft.options == {"fps": 30.0}
        assert draft.option_source("fps") == "file"
        assert draft.option_source("width_px") == "required"


class TestChoosingAnotherGroupOrReader:
    def test_choosing_another_reader_marks_the_choice_as_the_users(self) -> None:
        draft = ConfirmDraft(result((detection("alpha"), detection("beta", ids=("a", "b", "c")))))
        draft.select_reader("beta")
        assert draft.reader == "beta"
        assert draft.chosen_by == "user"
        assert [r.session_id for r in draft.rows] == ["a", "b", "c"]

    def test_choosing_the_detected_reader_again_is_not_a_change(self) -> None:
        draft = ConfirmDraft(result((detection("alpha"), detection("beta"))))
        draft.select_reader("beta")
        draft.select_reader("alpha")
        assert draft.chosen_by == "detected"

    def test_a_reader_the_scan_did_not_offer_is_refused(self, plain: ConfirmDraft) -> None:
        with pytest.raises(ValueError, match="gamma"):
            plain.select_reader("gamma")

    def test_the_options_follow_the_reader(self) -> None:
        proposed = {"fps": ProposedValue(value=30.0, source="file")}
        draft = ConfirmDraft(
            result(
                (
                    detection("alpha", parameters=(FPS,), proposed=proposed),
                    detection("beta", parameters=(SIZE,)),
                )
            )
        )
        draft.set_option("fps", 50.0)
        draft.select_reader("beta")
        assert draft.options == {}
        draft.select_reader("alpha")
        assert draft.options == {"fps": 30.0}  # the user's 50 belonged to the earlier choice

    def test_choosing_another_group_starts_from_its_best_reader(self) -> None:
        draft = ConfirmDraft(
            result((detection("alpha"),), (detection("gamma", ids=("x",)), detection("beta")))
        )
        assert len(draft.groups) == 2
        draft.select_group(1)
        assert draft.reader == "gamma"
        assert draft.chosen_by == "detected"
        assert [r.session_id for r in draft.rows] == ["x"]

    def test_a_group_that_does_not_exist_is_refused(self, plain: ConfirmDraft) -> None:
        with pytest.raises(ValueError):
            plain.select_group(3)


class TestOptions:
    def test_a_value_the_user_types_replaces_the_proposal_and_says_so(self) -> None:
        proposed = {"fps": ProposedValue(value=30.0, source="video")}
        draft = ConfirmDraft(result((detection("alpha", parameters=(FPS,), proposed=proposed),)))
        draft.set_option("fps", 25.0)
        assert draft.options == {"fps": 25.0}
        assert draft.option_source("fps") == "user"

    def test_clearing_a_value_leaves_a_required_option_missing_again(self) -> None:
        proposed = {"fps": ProposedValue(value=30.0, source="file")}
        draft = ConfirmDraft(result((detection("alpha", parameters=(FPS,), proposed=proposed),)))
        draft.set_option("fps", None)
        assert draft.options == {}
        assert [p.code for p in draft.problems()] == ["OPTION_MISSING"]

    def test_an_option_the_reader_does_not_declare_is_refused(self, plain: ConfirmDraft) -> None:
        with pytest.raises(ValueError, match="fps"):
            plain.set_option("fps", 25.0)

    def test_a_per_session_option_is_set_for_one_session_only(self) -> None:
        draft = ConfirmDraft(result((detection("alpha", parameters=(ARENA,)),)))
        draft.set_session_option("a", "arena", 1)
        assert draft.session_options("a") == {"arena": 1}
        assert draft.session_options("b") == {}

    def test_a_shared_option_cannot_be_set_per_session_and_the_reverse(self) -> None:
        draft = ConfirmDraft(result((detection("alpha", parameters=(FPS, ARENA)),)))
        with pytest.raises(ValueError, match="fps"):
            draft.set_session_option("a", "fps", 25.0)
        with pytest.raises(ValueError, match="arena"):
            draft.set_option("arena", 1)


class TestSessions:
    def test_a_session_can_be_left_out(self, plain: ConfirmDraft) -> None:
        plain.set_included("a", False)
        assert [r.session_id for r in plain.rows if r.included] == ["b"]

    def test_a_session_can_be_renamed_and_keeps_its_place(self, plain: ConfirmDraft) -> None:
        plain.rename("a", "trial_1")
        assert [r.session_id for r in plain.rows] == ["trial_1", "b"]
        assert plain.rows[0].original_id == "a"

    def test_an_unknown_session_is_refused(self, plain: ConfirmDraft) -> None:
        with pytest.raises(KeyError):
            plain.set_included("nope", False)
        with pytest.raises(KeyError):
            plain.rename("nope", "x")

    def test_a_session_already_in_the_project_is_left_out_and_says_so(self) -> None:
        existing = [SessionRef(session_id="old", folder=Path("root") / "a", sha256="")]
        draft = ConfirmDraft(result((detection("alpha"),)), existing=existing)
        by_id = {r.original_id: r for r in draft.rows}
        assert by_id["a"].already_added and not by_id["a"].included
        assert not by_id["b"].already_added and by_id["b"].included

    def test_the_same_folder_saved_under_another_reader_is_not_a_duplicate(self) -> None:
        # Another reader could read the same files into different numbers, so it is another
        # session, not a second copy of the first.
        existing = [
            SessionRef(session_id="old", folder=Path("root") / "a", sha256="", reader="beta")
        ]
        draft = ConfirmDraft(result((detection("alpha"),)), existing=existing)
        assert not any(r.already_added for r in draft.rows)
        assert all(r.included for r in draft.rows)

    def test_the_same_folder_saved_under_the_same_reader_is_a_duplicate(self) -> None:
        existing = [
            SessionRef(session_id="old", folder=Path("root") / "a", sha256="", reader="alpha")
        ]
        draft = ConfirmDraft(result((detection("alpha"),)), existing=existing)
        assert {r.original_id for r in draft.rows if r.already_added} == {"a"}

    def test_choosing_another_reader_keeps_what_was_already_in_the_project(self) -> None:
        existing = [SessionRef(session_id="old", folder=Path("root") / "a", sha256="")]
        draft = ConfirmDraft(result((detection("alpha"), detection("beta"))), existing=existing)
        draft.select_reader("beta")
        assert {r.original_id for r in draft.rows if r.already_added} == {"a"}


class TestProblems:
    def test_a_clean_draft_has_none(self, plain: ConfirmDraft) -> None:
        assert plain.problems() == []

    def test_nothing_included_is_a_problem(self, plain: ConfirmDraft) -> None:
        plain.set_included("a", False)
        plain.set_included("b", False)
        assert [p.code for p in plain.problems()] == ["NOTHING_SELECTED"]

    def test_a_missing_required_option_is_named(self) -> None:
        draft = ConfirmDraft(result((detection("alpha", parameters=(FPS, SIZE)),)))
        problems = draft.problems()
        assert sorted(p.option for p in problems if p.code == "OPTION_MISSING") == [
            "fps",
            "width_px",
        ]
        assert all("Frame" in p.message for p in problems)

    def test_filling_it_in_clears_it(self) -> None:
        draft = ConfirmDraft(result((detection("alpha", parameters=(FPS,)),)))
        draft.set_option("fps", 25.0)
        assert draft.problems() == []

    def test_a_value_out_of_range_is_invalid_rather_than_missing(self) -> None:
        draft = ConfirmDraft(result((detection("alpha", parameters=(FPS,)),)))
        draft.set_option("fps", 0)
        assert [(p.code, p.option) for p in draft.problems()] == [("OPTION_INVALID", "fps")]

    def test_a_per_session_option_missing_for_one_session_names_that_session(self) -> None:
        draft = ConfirmDraft(result((detection("alpha", parameters=(ARENA,)),)))
        draft.set_session_option("a", "arena", 0)
        problems = draft.problems()
        assert [(p.code, p.session_id, p.option) for p in problems] == [
            ("OPTION_MISSING", "b", "arena")
        ]

    def test_leaving_the_offending_session_out_clears_its_problem(self) -> None:
        draft = ConfirmDraft(result((detection("alpha", parameters=(ARENA,)),)))
        draft.set_session_option("a", "arena", 0)
        draft.set_included("b", False)
        assert draft.problems() == []

    def test_two_sessions_with_one_id_are_a_problem(self, plain: ConfirmDraft) -> None:
        plain.rename("b", "a")
        assert [(p.code, p.session_id) for p in plain.problems()] == [("ID_DUPLICATE", "a")]

    def test_an_id_the_project_already_uses_is_a_problem(self) -> None:
        existing = [SessionRef(session_id="a", folder=Path("elsewhere"), sha256="")]
        draft = ConfirmDraft(result((detection("alpha"),)), existing=existing)
        assert [(p.code, p.session_id) for p in draft.problems()] == [("ID_DUPLICATE", "a")]

    @pytest.mark.parametrize("bad", ["", ".", "..", "a/b", "a\\b"])
    def test_an_id_that_could_escape_the_output_folder_is_a_problem(
        self, plain: ConfirmDraft, bad: str
    ) -> None:
        plain.rename("a", bad)
        assert [p.code for p in plain.problems()] == ["ID_UNSAFE"]

    def test_a_problem_always_says_what_to_do(self) -> None:
        draft = ConfirmDraft(result((detection("alpha", parameters=(FPS,)),)))
        assert all(p.message for p in draft.problems())


class TestTheSessionsItAdds:
    def test_each_carries_the_reader_the_options_and_who_chose_them(self) -> None:
        draft = ConfirmDraft(
            result((detection("alpha", parameters=(FPS, KEYPOINT), confidence=Confidence.MEDIUM),))
        )
        draft.set_option("fps", 25.0)
        refs = draft.to_session_refs()
        assert [r.session_id for r in refs] == ["a", "b"]
        first = refs[0]
        assert first.folder == Path("root") / "a"
        assert first.sha256 == ""
        assert first.reader == "alpha"
        assert first.reader_options == {"fps": 25.0}  # only what was given, not the defaults
        assert first.reader_chosen_by == "detected"
        assert first.reader_confidence == "MEDIUM"

    def test_a_choice_the_user_made_is_recorded_as_theirs(self) -> None:
        draft = ConfirmDraft(result((detection("alpha"), detection("beta"))))
        draft.select_reader("beta")
        assert {r.reader_chosen_by for r in draft.to_session_refs()} == {"user"}
        assert {r.reader for r in draft.to_session_refs()} == {"beta"}

    def test_left_out_sessions_are_not_added_and_renamed_ones_use_the_new_id(self) -> None:
        draft = ConfirmDraft(result((detection("alpha", ids=("a", "b", "c")),)))
        draft.set_included("b", False)
        draft.rename("c", "third")
        assert [r.session_id for r in draft.to_session_refs()] == ["a", "third"]

    def test_per_session_options_are_merged_over_the_shared_ones(self) -> None:
        draft = ConfirmDraft(result((detection("alpha", parameters=(FPS, ARENA)),)))
        draft.set_option("fps", 25.0)
        draft.set_session_option("a", "arena", 0)
        draft.set_session_option("b", "arena", 1)
        refs = draft.to_session_refs()
        assert [r.reader_options for r in refs] == [
            {"fps": 25.0, "arena": 0},
            {"fps": 25.0, "arena": 1},
        ]

    def test_the_options_of_one_session_are_not_shared_with_another(self) -> None:
        draft = ConfirmDraft(result((detection("alpha", parameters=(FPS,)),)))
        draft.set_option("fps", 25.0)
        refs = draft.to_session_refs()
        refs[0].reader_options["fps"] = 99.0
        assert refs[1].reader_options == {"fps": 25.0}
        assert draft.options == {"fps": 25.0}

    def test_it_refuses_while_there_are_problems(self) -> None:
        draft = ConfirmDraft(result((detection("alpha", parameters=(FPS,)),)))
        with pytest.raises(ValueError, match="fps"):
            draft.to_session_refs()


class TestAgainstARealScan:
    def test_an_idtracker_folder_of_sessions_becomes_a_project_ready_to_run(
        self, tiny_real_session: Path, tmp_path: Path
    ) -> None:
        import shutil

        from track2data.api import Engine
        from track2data.core.models import ProjectManifest
        from track2data.readers.scan import scan

        for name in ("s1", "s2"):
            shutil.copytree(tiny_real_session, tmp_path / "root" / name)
        draft = ConfirmDraft(scan([tmp_path / "root"]))
        assert draft.reader == "idtrackerai"
        assert draft.problems() == []
        refs = draft.to_session_refs()
        assert [r.reader_chosen_by for r in refs] == ["detected", "detected"]
        assert {r.reader_confidence for r in refs} == {"HIGH"}

        from datetime import UTC, datetime

        now = datetime.now(tz=UTC)
        manifest = ProjectManifest(project_name="p", created_at=now, updated_at=now, sessions=refs)
        session = Engine(manifest).import_ref(refs[0])
        assert session.n_animals == 2 and session.session_id == refs[0].session_id

"""ConfirmFormatDialog: the user's chance to confirm or amend what the scan found.

A thin view over ConfirmDraft: every rule (what is missing, what clashes, what the sessions are
called) lives there and is tested there. These tests check the dialog shows the draft's state
faithfully, sends the user's edits to it, and is safe to put in front of someone: it opens without
blocking, Escape cancels, and OK is disabled until adding would succeed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QWidget

from track2data.core.models import SessionRef
from track2data.readers.confirm import ConfirmDraft
from track2data.readers.detection import Confidence, Detection, SessionCandidate
from track2data.readers.params import ProposedValue, ReaderParameter
from track2data.readers.scan import FormatGroup, ScanResult
from ui.dialogs.confirm_format_dialog import ConfirmFormatDialog

FPS = ReaderParameter(name="fps", label="Frame rate", kind="float", required=True, minimum=1)
WIDTH = ReaderParameter(name="width_px", label="Frame width", kind="int", required=True)


def detection(
    reader: str = "alpha",
    ids: tuple[str, ...] = ("a", "b"),
    *,
    confidence: Confidence = Confidence.HIGH,
    parameters: tuple[ReaderParameter, ...] = (),
    proposed: dict[str, ProposedValue] | None = None,
    display_name: str | None = None,
    verification: str = "real_sample",
) -> Detection:
    return Detection(
        reader=reader,
        display_name=display_name or reader.title(),
        confidence=confidence,
        evidence=(f"{reader} looks right: 3 markers",),
        sessions=tuple(
            SessionCandidate(session_id=i, source=Path("root") / i, warnings=()) for i in ids
        ),
        parameters=parameters,
        proposed=proposed or {},
        verification=verification,
    )


def result(*groups: tuple[Detection, ...], truncated: bool = False, file_types=None) -> ScanResult:
    return ScanResult(
        roots=(Path("root"),),
        groups=tuple(FormatGroup(detections=g) for g in groups),
        file_types=file_types or {},
        truncated=truncated,
        warnings=("a warning",) if truncated else (),
        entries=412,
        seconds=0.4,
    )


def make(qtbot, *groups: tuple[Detection, ...], existing=(), **kwargs) -> ConfirmFormatDialog:
    draft = ConfirmDraft(result(*groups, **kwargs), existing=existing)
    dialog = ConfirmFormatDialog(draft)
    qtbot.addWidget(dialog)
    return dialog


def ok_text(dialog: ConfirmFormatDialog) -> str:
    return dialog.ok_button.text()


class TestWhatItShows:
    def test_the_detected_software_with_its_confidence_and_evidence(self, qtbot) -> None:
        dialog = make(qtbot, (detection(display_name="Alpha tracker"),))
        assert dialog.reader_combo.currentText().startswith("Alpha tracker")
        assert "High" in dialog.confidence_label.text()
        assert "3 markers" in dialog.evidence_label.text()

    def test_what_was_scanned(self, qtbot) -> None:
        dialog = make(qtbot, (detection(),))
        assert "412" in dialog.summary_label.text() and "root" in dialog.summary_label.text()

    def test_the_sessions_with_their_ids_and_places(self, qtbot) -> None:
        dialog = make(qtbot, (detection(),))
        table = dialog.table
        assert table.rowCount() == 2
        assert table.item(0, 1).text() == "a" and table.item(1, 1).text() == "b"
        assert str(Path("root") / "a") in table.item(0, 2).toolTip()
        assert table.item(0, 0).checkState() == Qt.CheckState.Checked

    def test_the_other_readers_that_recognised_it_are_offered(self, qtbot) -> None:
        dialog = make(
            qtbot,
            (detection("alpha"), detection("beta", confidence=Confidence.LOW)),
        )
        texts = [dialog.reader_combo.itemText(i) for i in range(dialog.reader_combo.count())]
        assert len(texts) == 2 and texts[1].startswith("Beta") and "Low" in texts[1]

    def test_a_reader_not_tested_against_real_output_says_so(self, qtbot) -> None:
        dialog = make(qtbot, (detection(verification="synthetic_only"),))
        assert not dialog.unverified_label.isHidden()
        assert "not yet checked" in dialog.unverified_label.text()

    def test_a_tested_reader_does_not(self, qtbot) -> None:
        assert make(qtbot, (detection(),)).unverified_label.isHidden()

    def test_a_scan_that_stopped_at_its_budget_says_so(self, qtbot) -> None:
        dialog = make(qtbot, (detection(),), truncated=True)
        assert not dialog.truncated_label.isHidden()
        assert make(qtbot, (detection(),)).truncated_label.isHidden()

    def test_the_group_chooser_appears_only_when_there_is_a_choice(self, qtbot) -> None:
        one = make(qtbot, (detection(),))
        assert one.group_combo.isHidden()
        two = make(qtbot, (detection("alpha"),), (detection("gamma", ids=("x",)),))
        assert not two.group_combo.isHidden() and two.group_combo.count() == 2

    def test_the_options_form_is_there_only_for_a_reader_that_has_options(self, qtbot) -> None:
        assert make(qtbot, (detection(),)).options_form.isHidden()
        with_options = make(qtbot, (detection(parameters=(FPS,)),))
        assert not with_options.options_form.isHidden()

    def test_a_value_the_files_gave_is_prefilled_and_says_where_from(self, qtbot) -> None:
        proposed = {"fps": ProposedValue(value=30.0, source="file")}
        dialog = make(qtbot, (detection(parameters=(FPS,), proposed=proposed),))
        assert dialog.options_form.widget_for("fps").value() == 30.0
        assert dialog.options_form.note_for("fps") == "from the file"


class TestAddingIsOnlyPossibleWhenItWouldWork:
    def test_a_clean_draft_can_be_added_and_says_how_many(self, qtbot) -> None:
        dialog = make(qtbot, (detection(),))
        assert dialog.ok_button.isEnabled()
        assert ok_text(dialog) == "Add 2 sessions"

    def test_a_missing_option_disables_it_and_the_tooltip_says_which(self, qtbot) -> None:
        dialog = make(qtbot, (detection(parameters=(FPS, WIDTH)),))
        assert not dialog.ok_button.isEnabled()
        assert "Frame rate" in dialog.ok_button.toolTip()
        assert "Frame width" in dialog.ok_button.toolTip()
        assert "Frame rate" in dialog.problems_label.text()

    def test_filling_it_in_enables_it(self, qtbot) -> None:
        dialog = make(qtbot, (detection(parameters=(FPS, WIDTH)),))
        dialog.options_form.widget_for("fps").setValue(25.0)
        assert not dialog.ok_button.isEnabled()
        dialog.options_form.widget_for("width_px").setValue(100)
        assert dialog.ok_button.isEnabled()
        assert dialog.ok_button.toolTip() == ""
        assert dialog.problems_label.isHidden()

    def test_what_is_typed_reaches_the_draft(self, qtbot) -> None:
        dialog = make(qtbot, (detection(parameters=(FPS,)),))
        dialog.options_form.widget_for("fps").setValue(25.0)
        assert dialog.draft.options == {"fps": 25.0}
        assert dialog.draft.option_source("fps") == "user"

    def test_leaving_a_session_out_changes_the_count(self, qtbot) -> None:
        dialog = make(qtbot, (detection(),))
        dialog.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
        assert ok_text(dialog) == "Add 1 session"
        dialog.table.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
        assert not dialog.ok_button.isEnabled()
        assert "Nothing is selected" in dialog.ok_button.toolTip()

    def test_renaming_a_session_to_a_name_in_use_is_refused(self, qtbot) -> None:
        dialog = make(qtbot, (detection(),))
        dialog.table.item(1, 1).setText("a")
        assert not dialog.ok_button.isEnabled()
        assert "a" in dialog.problems_label.text()
        dialog.table.item(1, 1).setText("second")
        assert dialog.ok_button.isEnabled()

    def test_a_session_already_in_the_project_is_left_out_and_marked(self, qtbot) -> None:
        existing = [SessionRef(session_id="old", folder=Path("root") / "a", sha256="")]
        dialog = make(qtbot, (detection(),), existing=existing)
        assert dialog.table.item(0, 0).checkState() == Qt.CheckState.Unchecked
        assert "already" in dialog.table.item(0, 3).text().lower()
        assert ok_text(dialog) == "Add 1 session"


class TestAmendingTheChoice:
    def test_choosing_another_reader_updates_everything_and_marks_it_as_the_users(
        self, qtbot
    ) -> None:
        dialog = make(
            qtbot,
            (
                detection("alpha"),
                detection("beta", ids=("a", "b", "c"), parameters=(FPS,), display_name="Beta"),
            ),
        )
        dialog.reader_combo.setCurrentIndex(1)
        assert dialog.draft.reader == "beta" and dialog.draft.chosen_by == "user"
        assert dialog.table.rowCount() == 3
        assert not dialog.options_form.isHidden()
        assert not dialog.ok_button.isEnabled()  # beta needs a frame rate

    def test_choosing_another_group_shows_its_sessions(self, qtbot) -> None:
        dialog = make(qtbot, (detection("alpha"),), (detection("gamma", ids=("x", "y", "z")),))
        dialog.group_combo.setCurrentIndex(1)
        assert dialog.draft.reader == "gamma"
        assert [dialog.table.item(r, 1).text() for r in range(3)] == ["x", "y", "z"]

    def test_the_combo_never_loops_back_into_the_draft(self, qtbot) -> None:
        dialog = make(qtbot, (detection("alpha"), detection("beta")))
        dialog.reader_combo.setCurrentIndex(1)
        dialog.reader_combo.setCurrentIndex(0)
        assert dialog.draft.chosen_by == "detected"


class TestWhatItHandsBack:
    def test_accepting_gives_sessions_that_save_the_reader_and_the_options(self, qtbot) -> None:
        dialog = make(qtbot, (detection(parameters=(FPS,)),))
        dialog.options_form.widget_for("fps").setValue(25.0)
        dialog.table.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
        dialog.ok_button.click()
        assert dialog.result() == QDialog.DialogCode.Accepted
        (ref,) = dialog.sessions()
        assert (ref.session_id, ref.reader, ref.reader_options) == ("a", "alpha", {"fps": 25.0})
        assert ref.reader_chosen_by == "detected"

    def test_cancel_adds_nothing(self, qtbot) -> None:
        dialog = make(qtbot, (detection(),))
        dialog.cancel_button.click()
        assert dialog.result() == QDialog.DialogCode.Rejected

    def test_a_disabled_ok_cannot_be_pressed(self, qtbot) -> None:
        dialog = make(qtbot, (detection(parameters=(FPS,)),))
        dialog.ok_button.click()
        assert dialog.result() != QDialog.DialogCode.Accepted


class TestItIsSafeToPutInFrontOfSomeone:
    def test_it_opens_without_blocking_and_announces_how_it_ended(self, qtbot) -> None:
        dialog = make(qtbot, (detection(),))
        ended: list[int] = []
        dialog.finished.connect(ended.append)
        dialog.open()  # never exec(): that would hang the screenshot driver
        assert dialog.isVisible()
        dialog.cancel_button.click()
        assert ended == [QDialog.DialogCode.Rejected.value]

    def test_escape_cancels(self, qtbot) -> None:
        dialog = make(qtbot, (detection(),))
        dialog.open()
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        assert dialog.result() == QDialog.DialogCode.Rejected and not dialog.isVisible()

    def test_enter_adds_when_that_is_possible(self, qtbot) -> None:
        dialog = make(qtbot, (detection(),))
        dialog.open()
        QTest.keyClick(dialog.ok_button, Qt.Key.Key_Return)
        assert dialog.result() == QDialog.DialogCode.Accepted

    def test_a_click_outside_does_not_dismiss_it(self, qtbot) -> None:
        # A combo popup is a separate window, so an outside-click filter would reject the dialog
        # while the user is merely choosing software.
        dialog = make(qtbot, (detection(),))
        dialog.open()
        other = QWidget()
        qtbot.addWidget(other)
        other.show()
        qtbot.mouseClick(other, Qt.MouseButton.LeftButton)
        assert dialog.isVisible()


class TestWhenNothingWasRecognised:
    def test_it_says_so_and_lists_what_it_did_see(self, qtbot) -> None:
        dialog = make(qtbot, file_types={".csv": 12, ".txt": 1})
        assert dialog.draft.is_empty
        assert "No tracking output" in dialog.summary_label.text()
        assert ".csv" in dialog.empty_label.text() and "12" in dialog.empty_label.text()
        assert dialog.empty_label.isVisibleTo(dialog)

    def test_there_is_nothing_to_add_and_only_a_way_out(self, qtbot) -> None:
        dialog = make(qtbot)
        assert dialog.ok_button.isHidden()
        assert not dialog.table.isVisibleTo(dialog)
        assert not dialog.reader_combo.isVisibleTo(dialog)
        assert dialog.cancel_button.text() == "Close"

    def test_it_names_the_software_this_version_can_read(self, qtbot) -> None:
        dialog = make(qtbot)
        assert "idtracker.ai" in dialog.empty_label.text()

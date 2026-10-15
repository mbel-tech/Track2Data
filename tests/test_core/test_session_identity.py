"""One rule for "the project already has this session", shared by the import dialog and the
project store. The truth table is written out as data so the two code paths cannot drift."""

from __future__ import annotations

from pathlib import Path

import pytest

from track2data.core.models import PanelRect, SessionRef
from track2data.core.session_identity import same_session_part

PANEL = PanelRect(x=0, y=0, width=100, height=50)
OTHER_PANEL = PanelRect(x=100, y=0, width=100, height=50)
FOLDER = Path("root") / "a"

# (existing reader, existing panel, candidate reader, candidate panel) -> duplicate?
# The candidate always sits in FOLDER, as does the existing entry; "same folder" is not the
# variable here. The rule is not symmetric: only the *existing* entry's missing reader is a
# wildcard.
TABLE = [
    (None, None, "a", None, True),  # legacy entry, any reader
    (None, None, None, None, True),
    ("a", None, "a", None, True),
    ("a", None, "b", None, False),  # another reader reads the same files differently
    ("a", None, None, None, False),  # a candidate without a reader is not a wildcard
    ("a", PANEL, "a", None, False),  # split into panels: the whole frame is offered again
    ("a", None, "a", PANEL, False),
    ("a", PANEL, "a", PANEL, True),
    ("a", PANEL, "a", OTHER_PANEL, False),
    (None, PANEL, "a", None, False),
]


def _ref(reader: str | None, panel: PanelRect | None, folder: Path = FOLDER) -> SessionRef:
    return SessionRef(session_id="s", folder=folder, sha256="", reader=reader, panel=panel)


@pytest.mark.parametrize(("e_reader", "e_panel", "c_reader", "c_panel", "duplicate"), TABLE)
def test_same_session_part_truth_table(e_reader, e_panel, c_reader, c_panel, duplicate) -> None:
    assert same_session_part(_ref(c_reader, c_panel), _ref(e_reader, e_panel)) is duplicate


def test_another_folder_is_never_the_same_session() -> None:
    assert not same_session_part(_ref("a", None), _ref("a", None, Path("root") / "b"))


@pytest.mark.parametrize(("e_reader", "e_panel", "c_reader", "c_panel", "duplicate"), TABLE)
def test_the_project_store_agrees(e_reader, e_panel, c_reader, c_panel, duplicate) -> None:
    from ui.store.project_store import _is_duplicate

    assert _is_duplicate(_ref(c_reader, c_panel), [_ref(e_reader, e_panel)]) is duplicate


@pytest.mark.parametrize(("e_reader", "e_panel", "c_reader", "c_panel", "duplicate"), TABLE)
def test_the_import_dialog_agrees_where_it_can_express_the_case(
    e_reader, e_panel, c_reader, c_panel, duplicate
) -> None:
    """The dialog's candidates are whole-frame sessions of the draft's reader."""
    from tests.test_readers.test_confirm import detection, result
    from track2data.readers.confirm import ConfirmDraft

    if c_reader is None or c_panel is not None:
        pytest.skip("a dialog candidate always has a reader and no panel")
    draft = ConfirmDraft(
        result((detection(c_reader, ids=("a",)),)), existing=[_ref(e_reader, e_panel)]
    )
    (row,) = draft.rows
    assert row.already_added is duplicate
    assert row.included is (not duplicate)

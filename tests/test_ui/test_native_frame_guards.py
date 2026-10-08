"""Screens that read a session's frame size, for a session that has none.

A tracker with no pixel frame stores a frame size of 0. Anything that sized a canvas from it would
get an empty one, so these places fall back to what the positions themselves say.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QDialog

from tests.support.toy_reader import NATIVE_OPTIONS, OPTIONS
from track2data.core.models import ProjectManifest, SessionRef
from ui.preview_screen import load_trajectory_data


def _manifest(folder: Path, reader: str, options: dict) -> ProjectManifest:
    now = datetime.now(tz=UTC)
    return ProjectManifest(
        project_name="p",
        created_at=now,
        updated_at=now,
        sessions=[
            SessionRef(
                session_id="trial1",
                folder=folder,
                sha256="",
                reader=reader,
                reader_options=options,
                reader_chosen_by="user",
                reader_confidence="HIGH",
            )
        ],
    )


def test_the_trajectory_viewer_is_given_no_frame_size_when_there_is_no_pixel_frame(
    toy_native_reader: None, toy_folder: Path
) -> None:
    data = load_trajectory_data(_manifest(toy_folder, "toy_native", NATIVE_OPTIONS), "trial1", None)
    assert data.size is None  # the viewer then sizes itself from the positions


def test_a_pixel_session_still_gets_its_frame_size(toy_reader: None, toy_folder: Path) -> None:
    data = load_trajectory_data(_manifest(toy_folder, "toy_csv", OPTIONS), "trial1", None)
    assert data.size == (float(OPTIONS["width_px"]), float(OPTIONS["height_px"]))


def test_the_ruler_gets_a_default_size_when_the_frame_is_zero_sized(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    from track2data.core.models import SessionRef as Ref
    from ui.calibration_screen import CalibrationScreen
    from ui.store.project_store import ProjectStore
    from ui.store.session_facts import SessionFacts
    from ui.widgets import ruler_dialog

    store = ProjectStore()
    store.new_project("p", tmp_path)
    store.update_sessions([Ref(session_id="a", folder=tmp_path / "a", sha256="")])
    store._session_facts["a"] = SessionFacts(
        session_id="a", reader="x", fps=30.0, n_frames=10, n_animals=1,
        width_px=0, height_px=0, has_stable_identities=True, track_wo_identities=None,
        idtrackerai_version=None, length_unit=None, setup_points=None, roi_list=None,
        has_body_length=False, background_image_path=None,
    )  # fmt: skip
    seen: list[tuple[float, float]] = []

    class Fake:
        DialogCode = QDialog.DialogCode

        def __init__(self, background, size, parent=None) -> None:
            seen.append(size)

        def exec(self):
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(ruler_dialog, "RulerDialog", Fake)
    screen = CalibrationScreen(store)
    qtbot.addWidget(screen)
    screen._measure_btn.click()
    assert seen == [(640.0, 480.0)]

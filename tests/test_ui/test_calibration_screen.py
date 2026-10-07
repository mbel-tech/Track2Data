"""
Tests for ui/calibration_screen.py.

No prior coverage existed for this screen (only the blanket
instantiate-all check in test_app_smoke.py). Added alongside the
scalar/bodylength -> scalar/bodylength/session three-mode split (Part 2
of the post-v0.1.0 GUI fixes plan) and the _apply() model_copy fix.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")


def _make_store(tmp_path: Path):
    from ui.store.project_store import ProjectStore

    store = ProjectStore()
    store.new_project("p", tmp_path)
    return store


# ── pretty labels ────────────────────────────────────────────────────────────


def test_radio_labels_are_pretty_not_raw_mode_literals(qtbot) -> None:
    from ui.calibration_screen import CalibrationScreen

    screen = CalibrationScreen()
    qtbot.addWidget(screen)

    labels = [
        screen._radio_bl.text(),
        screen._radio_scalar.text(),
        screen._radio_session.text(),
    ]
    assert "bodylength" not in labels
    assert "scalar" not in labels
    assert "session" not in labels
    assert any("Body length" in label for label in labels)
    assert any("Custom" in label for label in labels)
    assert any("Session calibration" in label for label in labels)


# ── mode visibility ──────────────────────────────────────────────────────────


def test_only_session_widget_visible_in_session_mode(qtbot) -> None:
    from ui.calibration_screen import CalibrationScreen

    screen = CalibrationScreen()
    qtbot.addWidget(screen)
    screen.show()

    screen._radio_session.setChecked(True)

    assert screen._session_widget.isVisible()
    assert not screen._scalar_widget.isVisible()
    assert not screen._bl_label.isVisible()


def test_only_scalar_widget_visible_in_custom_mode(qtbot) -> None:
    from ui.calibration_screen import CalibrationScreen

    screen = CalibrationScreen()
    qtbot.addWidget(screen)
    screen.show()

    screen._radio_scalar.setChecked(True)

    assert screen._scalar_widget.isVisible()
    assert not screen._session_widget.isVisible()
    assert not screen._bl_label.isVisible()


# ── apply(): each mode writes the right CalibrationConfig ───────────────────


def test_apply_custom_mode_sets_scalar_config(qtbot, tmp_path: Path) -> None:
    from ui.calibration_screen import CalibrationScreen

    store = _make_store(tmp_path)
    screen = CalibrationScreen(store)
    qtbot.addWidget(screen)

    screen._radio_scalar.setChecked(True)
    screen._px_spin.setValue(42.5)
    screen.flush()

    assert store.manifest.calibration.mode == "scalar"
    assert store.manifest.calibration.px_per_cm == pytest.approx(42.5)


def test_apply_bodylength_mode_clears_px_per_cm(qtbot, tmp_path: Path) -> None:
    from ui.calibration_screen import CalibrationScreen

    store = _make_store(tmp_path)
    screen = CalibrationScreen(store)
    qtbot.addWidget(screen)

    screen._radio_bl.setChecked(True)
    screen.flush()

    assert store.manifest.calibration.mode == "bodylength"
    assert store.manifest.calibration.px_per_cm is None


def test_apply_session_mode_sets_mode_unit_and_confirmation(qtbot, tmp_path: Path) -> None:
    from ui.calibration_screen import CalibrationScreen

    store = _make_store(tmp_path)
    screen = CalibrationScreen(store)
    qtbot.addWidget(screen)

    screen._radio_session.setChecked(True)
    screen._unit_combo.setCurrentText("mm")
    screen._confirm_check.setChecked(True)
    screen.flush()

    cfg = store.manifest.calibration
    assert cfg.mode == "session"
    assert cfg.length_unit_label == "mm"
    assert cfg.length_unit_confirmed_by_user is True


# ── the fresh-CalibrationConfig-discards-fields bug ──────────────────────────


def test_apply_preserves_bl_min_samples_across_mode_switches(qtbot, tmp_path: Path) -> None:
    """Regression: _apply() used to build a fresh CalibrationConfig(...)
    from only the two fields the widgets show for the active mode,
    silently resetting bl_min_samples (and length_unit_label/
    length_unit_confirmed_by_user) to their defaults on every Apply --
    even when the user was applying an unrelated mode."""
    from track2data.core.models import CalibrationConfig
    from ui.calibration_screen import CalibrationScreen

    store = _make_store(tmp_path)
    store.update_calibration(CalibrationConfig(mode="bodylength", bl_min_samples=99))

    screen = CalibrationScreen(store)
    qtbot.addWidget(screen)

    # Switch to Custom mode and apply -- bl_min_samples isn't shown by
    # this mode's widgets at all, so it must survive untouched.
    screen._radio_scalar.setChecked(True)
    screen._px_spin.setValue(5.0)
    screen.flush()

    assert store.manifest.calibration.bl_min_samples == 99


def test_apply_preserves_length_unit_confirmation_when_applying_another_mode(
    qtbot, tmp_path: Path
) -> None:
    from track2data.core.models import CalibrationConfig
    from ui.calibration_screen import CalibrationScreen

    store = _make_store(tmp_path)
    store.update_calibration(
        CalibrationConfig(
            mode="session", length_unit_label="mm", length_unit_confirmed_by_user=True
        )
    )

    screen = CalibrationScreen(store)
    qtbot.addWidget(screen)

    screen._radio_bl.setChecked(True)
    screen.flush()

    cfg = store.manifest.calibration
    assert cfg.mode == "bodylength"
    assert cfg.length_unit_label == "mm"
    assert cfg.length_unit_confirmed_by_user is True


# ── load-from-store round trip ───────────────────────────────────────────────


def test_on_calibration_changed_reselects_session_radio_and_widgets(
    qtbot, tmp_path: Path
) -> None:
    from track2data.core.models import CalibrationConfig
    from ui.calibration_screen import CalibrationScreen

    store = _make_store(tmp_path)
    store.update_calibration(
        CalibrationConfig(
            mode="session", length_unit_label="m", length_unit_confirmed_by_user=True
        )
    )

    screen = CalibrationScreen(store)
    qtbot.addWidget(screen)

    assert screen._radio_session.isChecked()
    assert screen._unit_combo.currentText() == "m"
    assert screen._confirm_check.isChecked()


# ── per-session readiness list ───────────────────────────────────────────────


def test_readiness_list_distinguishes_calibrated_from_uncalibrated_sessions(
    qtbot, tmp_path: Path
) -> None:
    from track2data.core.models import SessionRef
    from ui.calibration_screen import CalibrationScreen
    from ui.store.session_facts import SessionFacts

    store = _make_store(tmp_path)
    store.update_sessions(
        [
            SessionRef(session_id="calibrated", folder=tmp_path / "a", sha256=""),
            SessionRef(session_id="uncalibrated", folder=tmp_path / "b", sha256=""),
        ]
    )
    store._session_facts["calibrated"] = SessionFacts(
        session_id="calibrated", reader="idtrackerai", fps=30.0, n_frames=100, n_animals=1,
        width_px=640, height_px=480, has_stable_identities=True,
        track_wo_identities=False, idtrackerai_version=None,
        length_unit=12.5, setup_points=None, roi_list=None, has_body_length=False,
        background_image_path=None,
    )
    store._session_facts["uncalibrated"] = SessionFacts(
        session_id="uncalibrated", reader="idtrackerai", fps=30.0, n_frames=100, n_animals=1,
        width_px=640, height_px=480, has_stable_identities=True,
        track_wo_identities=False, idtrackerai_version=None,
        length_unit=None, setup_points=None, roi_list=None, has_body_length=False,
        background_image_path=None,
    )

    screen = CalibrationScreen(store)
    qtbot.addWidget(screen)

    rows = [screen._readiness_list.item(i).text() for i in range(screen._readiness_list.count())]
    assert any("calibrated" in r and "12.5" in r for r in rows if r.startswith("calibrated"))
    assert any("not calibrated" in r for r in rows if r.startswith("uncalibrated"))


def test_no_apply_button_and_change_autocommits(qtbot, tmp_path: Path) -> None:
    from PySide6.QtWidgets import QPushButton

    from ui.calibration_screen import CalibrationScreen

    store = _make_store(tmp_path)
    screen = CalibrationScreen(store)
    qtbot.addWidget(screen)
    assert not [b for b in screen.findChildren(QPushButton) if b.text() == "Apply"]

    screen._radio_scalar.setChecked(True)
    screen._px_spin.setValue(12.5)
    qtbot.waitUntil(lambda: store.manifest.calibration.px_per_cm == 12.5, timeout=2000)
    assert store.manifest.calibration.mode == "scalar"


def test_body_length_summary_reports_median_and_range(qtbot, tmp_path: Path) -> None:
    from track2data.core.models import SessionRef
    from ui.calibration_screen import CalibrationScreen
    from ui.store.session_facts import SessionFacts

    store = _make_store(tmp_path)
    store.update_sessions([SessionRef(session_id="a", folder=tmp_path / "a", sha256="")])
    store._session_facts["a"] = SessionFacts(
        session_id="a", reader="idtrackerai", fps=30.0, n_frames=100, n_animals=3,
        width_px=640, height_px=480, has_stable_identities=True,
        track_wo_identities=False, idtrackerai_version=None, length_unit=None,
        setup_points=None, roi_list=None, has_body_length=True, background_image_path=None,
        body_length_px=(20.0, 24.0, 28.0),
    )
    screen = CalibrationScreen(store)
    qtbot.addWidget(screen)
    text = screen._bl_label.text()
    assert "median 24.0 px" in text and "20.0 to 28.0" in text and "3 animal" in text


def test_measure_on_frame_sets_the_scale(qtbot, tmp_path: Path, monkeypatch) -> None:
    from ui.calibration_screen import CalibrationScreen
    from ui.widgets import ruler_dialog

    screen = CalibrationScreen(_make_store(tmp_path))
    qtbot.addWidget(screen)

    def fake_exec(self):
        self.canvas.click_at(0, 0)
        self.canvas.click_at(300, 0)
        self.length_spin.setValue(10.0)
        return ruler_dialog.RulerDialog.DialogCode.Accepted

    monkeypatch.setattr(ruler_dialog.RulerDialog, "exec", fake_exec)
    screen._measure_btn.click()
    assert screen._px_spin.value() == pytest.approx(30.0)

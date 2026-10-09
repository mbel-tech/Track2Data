#!/usr/bin/env python
"""Regenerate the screenshots used by docs/guide/.

Builds a small synthetic idtracker.ai session (two animals swimming in a
circular arena), drives the real ``MainWindow`` offscreen through the whole
workflow, and saves one PNG per wizard screen to ``docs/guide/images/``.

    python scripts/generate_guide_screenshots.py [--out docs/guide/images]

Needs the ``[ui]`` and ``[dev]`` extras (the demo session reuses the test
fixture builder in ``tests/conftest.py``). Output is deterministic apart from
fonts, so re-run it whenever a screen changes and commit the images.
"""

from __future__ import annotations

import argparse
import math
import os
import re
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402

N_FRAMES, FPS, WIDTH, HEIGHT = 900, 25.0, 800, 600
CENTRE, RADIUS = (400.0, 300.0), 250.0
SESSION = "animal_trial_01"


def _walk(rng: np.random.Generator, start: float) -> np.ndarray:
    """A smooth path that stays inside the arena (reflecting boundary)."""
    pos = np.array([CENTRE[0] + start, CENTRE[1] - start / 2])
    heading = rng.uniform(0, 2 * math.pi)
    out = np.empty((N_FRAMES, 2))
    for t in range(N_FRAMES):
        heading += rng.normal(0, 0.18)
        step = 4.0 + 2.0 * math.sin(t / 60.0)
        nxt = pos + step * np.array([math.cos(heading), math.sin(heading)])
        if math.hypot(nxt[0] - CENTRE[0], nxt[1] - CENTRE[1]) > RADIUS - 15:
            heading += math.pi * 0.8
            nxt = pos
        pos = nxt
        out[t] = pos
    return out


def build_demo_session(root: Path) -> Path:
    """Write the demo session folder and return it."""
    from tests import conftest as c

    rng = np.random.default_rng(7)
    xy = np.stack([_walk(rng, -80.0), _walk(rng, 90.0)], axis=1)
    xy[300:318, 1] = np.nan          # a short tracking gap
    xy[520, 0] += 160.0              # one identification jump
    xy[521:, 0] += 0.0

    c.TINY_REAL_N_FRAMES, c.TINY_REAL_FPS = N_FRAMES, FPS
    c.TINY_REAL_WIDTH, c.TINY_REAL_HEIGHT = WIDTH, HEIGHT
    real_dict = c._build_tiny_real_traj_dict

    def traj_dict(*args: Any, **kwargs: Any) -> dict:
        d = real_dict(*args, **kwargs)
        d["trajectories"] = xy
        d["id_probabilities"] = np.full((N_FRAMES, 2, 1), 0.97)
        d["body_length"] = 46.0
        return d

    c._build_tiny_real_traj_dict = traj_dict
    folder = root / SESSION
    c._build_tiny_real_session(folder)

    arena = [
        [CENTRE[0] + RADIUS * math.cos(a), CENTRE[1] + RADIUS * math.sin(a)]
        for a in np.linspace(0, 2 * math.pi, 25)[:-1]
    ]
    sj = folder / "session.json"
    text = sj.read_text(encoding="utf-8")
    text = text.replace(
        '"tracking_intervals": [[0, 9]]', f'"tracking_intervals": [[0, {N_FRAMES - 1}]]'
    )
    text = re.sub(
        r'"roi_list": \[.*?\],\n', f'"roi_list": ["+ Polygon {arena}"],\n', text, flags=re.S
    )
    sj.write_text(text, encoding="utf-8")
    _draw_background(folder / "preprocessing" / "background.png")
    return folder


def _draw_background(path: Path) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen

    img = QImage(WIDTH, HEIGHT, QImage.Format.Format_RGB32)
    img.fill(QColor("#cfd8dc"))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QBrush(QColor("#eceff1")))
    p.setPen(QPen(QColor("#90a4ae"), 4))
    r = int(RADIUS)
    p.drawEllipse(int(CENTRE[0]) - r, int(CENTRE[1]) - r, 2 * r, 2 * r)
    p.setPen(Qt.PenStyle.NoPen)
    p.end()
    img.save(str(path))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=REPO / "docs" / "guide" / "images")
    args = ap.parse_args()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)

    from PySide6.QtWidgets import QApplication, QWidget

    app = QApplication.instance() or QApplication([])

    from app.main_window import MainWindow
    from track2data.api import Engine
    from track2data.core.models import (
        ROI,
        CalibrationConfig,
        ExportTarget,
        ZoneSet,
    )

    work = Path(tempfile.mkdtemp(prefix="t2d_guide_"))
    folder = build_demo_session(work / "sessions")

    win = MainWindow()
    win.resize(1280, 800)
    win.show()
    store = win._store

    def pump(
        seconds: float = 0.0,
        until: Callable[[], bool] | None = None,
        timeout: float = 20.0,
    ) -> None:
        end = time.monotonic() + (timeout if until else seconds)
        while time.monotonic() < end:
            app.processEvents()
            if until is not None and until():
                break
            time.sleep(0.01)
        app.processEvents()

    def shot(name: str, page: int | None = None, widget: QWidget | None = None) -> None:
        """Save the main window, or *widget* (a dialog) when one is given."""
        if page is not None:
            win._go_to_page(page)
        pump(0.15)
        path = out / f"{name}.png"
        (widget or win).grab().save(str(path))
        print("wrote", path.relative_to(REPO) if path.is_relative_to(REPO) else path)

    def scroll_bottom(widget: QWidget) -> None:
        from PySide6.QtWidgets import QScrollArea

        area = widget.findChild(QScrollArea)
        if area is not None:
            area.verticalScrollBar().setValue(area.verticalScrollBar().maximum())
        pump(0.1)

    # 1 Project ---------------------------------------------------------------
    shot("01-project", 0)
    store.new_project("Animal demo", work)
    # 2 Sessions --------------------------------------------------------------
    win._go_to_page(1)
    sessions_page = win._stack.widget(1)
    sessions_page._import_paths([folder])  # the real flow: scan, then confirm, then add
    pump(until=lambda: sessions_page._dialog is not None)
    dialog = sessions_page._dialog
    pump(0.3)
    shot("02-sessions-confirm", widget=dialog)
    dialog.ok_button.click()
    pump(until=lambda: store.session_facts(SESSION) is not None)
    shot("02-sessions", 1)
    # 3 Calibration -----------------------------------------------------------
    win._go_to_page(2)
    shot("03-calibration-body-length")
    cal = win._stack.widget(2)
    cal._radio_scalar.setChecked(True)
    cal._px_spin.setValue(12.5)
    cal.flush()
    shot("03-calibration-custom")
    cal._radio_session.setChecked(True)
    cal.flush()
    shot("03-calibration-session")
    store.update_calibration(CalibrationConfig(mode="bodylength"))
    # 4 Zones -----------------------------------------------------------------
    zones = win._stack.widget(3)
    inner = [
        (CENTRE[0] + 110 * math.cos(a), CENTRE[1] + 110 * math.sin(a))
        for a in np.linspace(0, 2 * math.pi, 25)[:-1]
    ]
    outer = [
        (CENTRE[0] + RADIUS * math.cos(a), CENTRE[1] + RADIUS * math.sin(a))
        for a in np.linspace(0, 2 * math.pi, 25)[:-1]
    ]
    store.update_zones(
        ZoneSet(
            rois=[
                ROI(name="arena", level="main", vertices=outer),
                ROI(name="centre", level="secondary", vertices=inner),
            ],
            source_width_px=WIDTH,
            source_height_px=HEIGHT,
        )
    )
    zones._session_combo.setCurrentText(SESSION)
    pump(0.2)
    shot("04-zones", 3)
    scroll_bottom(zones)
    zones._tool_buttons["rect"].click()
    zones._canvas.drag_shape((250, 150), (550, 450))
    shot("04-zones-canvas")
    zones._canvas.clear_selection()
    zones._tool_buttons["points"].click()
    # 5 Metadata --------------------------------------------------------------
    csv_path = work / "trial_metadata.csv"
    csv_path.write_text(
        f"session_id,condition,date,tank\n{SESSION},control,2026-03-02,A\n", encoding="utf-8"
    )
    meta = win._stack.widget(4)
    meta.load_path(csv_path)
    meta.flush()
    pump(0.2)
    shot("05-metadata", 4)
    # 6 Preprocessing ---------------------------------------------------------
    shot("06-preprocessing", 5)
    scroll_bottom(win._stack.widget(5))
    shot("06-preprocessing-identity-switch")
    # 7 Metrics ---------------------------------------------------------------
    metrics = win._stack.widget(6)
    metrics.apply_preset("Standard locomotor")
    from PySide6.QtCore import Qt

    for table in (metrics._grp_table, metrics._zone_table):
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item.data(Qt.ItemDataRole.UserRole) in {"GL-1", "GL-2", "Z-1"}:
                item.setCheckState(Qt.CheckState.Checked)
    metrics.flush()
    pump(0.2)
    shot("07-metrics", 6)
    # 8 Processing ------------------------------------------------------------
    run_dir = work / "exports" / "run1"
    engine = Engine(store.manifest, cache_dir=store.cache_dir)
    result = engine.run(run_dir, exporters=["csv_long", "feather"])
    store.set_run_results(result)
    processing = win._stack.widget(7)
    processing._rebuild_status_table()
    for sr in result.sessions:
        row = processing._session_rows[sr.session_id]
        from PySide6.QtWidgets import QTableWidgetItem

        processing._status_table.setItem(row, 1, QTableWidgetItem("Done"))
        processing._status_table.setItem(row, 3, QTableWidgetItem(f"{sr.duration_s:.1f}s"))
    processing._progress.setValue(100)
    processing._status_label.setText("Finished.")
    shot("08-processing", 7)
    # 9 Preview ---------------------------------------------------------------
    preview = win._stack.widget(8)
    win._go_to_page(8)
    from PySide6.QtWidgets import QTabWidget

    tab_widget = preview.findChild(QTabWidget)
    from ui.preview_screen import load_trajectory_data

    data = load_trajectory_data(store.manifest, SESSION, store.cache_dir)
    preview._traj_view.set_data(
        data.raw_xy, data.xy, data.fps, rois=store.manifest.zones.rois,
        background_path=data.background, size=data.size,
    )
    preview._traj_slider.setRange(0, preview._traj_view.n_frames - 1)
    preview._traj_slider.setValue(700)
    preview._traj_source_combo.setCurrentIndex(preview._traj_source_combo.findData("both"))
    tab_widget.setCurrentIndex(3)
    shot("09-preview-trajectories")
    preview._traj_heatmap_check.setChecked(True)
    preview._traj_source_combo.setCurrentIndex(0)
    shot("09-preview-heatmap")
    tab_widget.setCurrentIndex(1)
    shot("09-preview-diagnostics")
    # 10 Export ---------------------------------------------------------------
    store.update_export_targets(
        [ExportTarget(exporter_name="csv_long"), ExportTarget(exporter_name="feather")]
    )
    export = win._stack.widget(9)
    export._checks["csv_long"].setChecked(True)
    export._checks["feather"].setChecked(True)
    export._last_out_dir = run_dir
    export._last_selected_exporters = ["csv_long", "feather"]
    export._populate_receipt_table(result)
    export._update_snippets(result)
    export._open_folder_btn.setEnabled(True)
    export._copy_cli_btn.setEnabled(True)
    export._status_label.setText("Finished.")
    shot("10-export", 9)
    scroll_bottom(export)
    shot("10-export-code")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

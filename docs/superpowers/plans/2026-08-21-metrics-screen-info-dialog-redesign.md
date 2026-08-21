# Metrics screen + MetricInfoDialog redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the QListWidget-based `ui/metrics_screen.py` and the metric_id-string `MetricInfoDialog` (issue #26's deliberately minimal v1) with the registry-driven `QTableWidget` design already documented in `docs/UI_DESIGN.md`/`docs/METRICS_SPEC.md` §6 — including identity-aware graying, zone-tab disabling, copy-citation, and full close behavior — while keeping the ⚙ per-metric-config icon as an explicit stub (Screen 6.3 doesn't exist).

**Architecture:** `SessionRef` gains a `has_stable_identities` field populated by a background `TaskRunner` probe when a session is added; `MetricsScreen` rebuilds each tab as a `QTableWidget` sourced from `metrics.list_for_level(level)` with per-row ⓘ/⚙ `QPushButton` cell widgets; `MetricInfoDialog` takes a `Metric` class directly and gains a copy-citation button plus an application-wide event filter for outside-click close.

**Tech Stack:** PySide6 (`QTableWidget`, `QDialog`, `QThreadPool` via the existing `TaskRunner`), Pydantic models, pytest + pytest-qt.

**Spec:** `docs/superpowers/specs/2026-08-21-metrics-screen-info-dialog-redesign-design.md`

---

## Task 1: `SessionRef.has_stable_identities` field

**Files:**
- Modify: `track2data/core/models.py:175-178`
- Test: `tests/test_core/test_models.py` (append at end; also add `SessionRef` to the existing import block)

- [ ] **Step 1: Write the failing test**

In `tests/test_core/test_models.py`, change the import block:

```python
from track2data.core.models import (
    ROI,
    CalibrationConfig,
    MetricSelection,
    PreprocessConfig,
    ProjectManifest,
    Session,
    VideoInfo,
    ZoneSet,
)
```

to:

```python
from track2data.core.models import (
    ROI,
    CalibrationConfig,
    MetricSelection,
    PreprocessConfig,
    ProjectManifest,
    Session,
    SessionRef,
    VideoInfo,
    ZoneSet,
)
```

Then append this to the end of the file:

```python

# ── SessionRef ─────────────────────────────────────────────────────────────────

class TestSessionRef:
    def test_has_stable_identities_defaults_to_none(self, tmp_path: Path) -> None:
        ref = SessionRef(session_id="s1", folder=tmp_path, sha256="abc")
        assert ref.has_stable_identities is None

    def test_has_stable_identities_can_be_set_explicitly(self, tmp_path: Path) -> None:
        ref = SessionRef(
            session_id="s1", folder=tmp_path, sha256="abc", has_stable_identities=True
        )
        assert ref.has_stable_identities is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_core/test_models.py::TestSessionRef -v`
Expected: FAIL with `AttributeError: 'SessionRef' object has no attribute 'has_stable_identities'`

- [ ] **Step 3: Write minimal implementation**

In `track2data/core/models.py`, change:

```python
class SessionRef(BaseModel):
    session_id: str
    folder: Path
    sha256: str
```

to:

```python
class SessionRef(BaseModel):
    session_id: str
    folder: Path
    sha256: str
    has_stable_identities: bool | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_core/test_models.py::TestSessionRef -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add track2data/core/models.py tests/test_core/test_models.py
git commit -m "feat(models): add SessionRef.has_stable_identities"
```

---

## Task 2: `ProjectStore` background identity probe

**Files:**
- Modify: `ui/store/project_store.py`
- Test: Create `tests/test_ui/test_project_store.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ui/test_project_store.py`:

```python
"""
Tests for the identity-probe extension to
ui/store/project_store.py's add_session(): a background reader read
(via TaskRunner) that fills in SessionRef.has_stable_identities once
it completes. See
docs/superpowers/specs/2026-08-21-metrics-screen-info-dialog-redesign-design.md
§5.1.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")

from track2data.core.models import ProjectManifest, Session, VideoInfo


@pytest.fixture
def store(tmp_path: Path):
    from ui.store.project_store import ProjectStore

    now = datetime.now(tz=UTC)
    s = ProjectStore()
    s._manifest = ProjectManifest(project_name="test_project", created_at=now, updated_at=now)
    s._project_dir = tmp_path
    yield s
    s.tasks.shutdown(3000)


def test_add_session_registers_ref_immediately(qtbot, store, tmp_path: Path) -> None:
    folder = tmp_path / "session_a"
    folder.mkdir()

    with qtbot.waitSignal(store.sessionsChanged, timeout=1000):
        store.add_session(folder)

    assert [s.session_id for s in store.manifest.sessions] == ["session_a"]
    assert store.manifest.sessions[0].has_stable_identities is None


def test_add_session_fills_in_has_stable_identities_on_probe_success(
    qtbot, monkeypatch, store, tmp_path: Path
) -> None:
    def fake_read_session(folder: Path) -> Session:
        return Session(
            session_id=folder.name,
            folder=folder,
            reader="fake",
            video=VideoInfo(fps=25.0, n_frames=10, width_px=100, height_px=100),
            n_animals=1,
            trajectory_variant="wo_gaps",
            has_stable_identities=True,
            raw_xy=np.zeros((10, 1, 2)),
        )

    monkeypatch.setattr("track2data.readers.read_session", fake_read_session)

    folder = tmp_path / "session_a"
    folder.mkdir()

    with qtbot.waitSignal(store.sessionsChanged, timeout=1000):
        store.add_session(folder)  # first emission: immediate registration

    with qtbot.waitSignal(store.sessionsChanged, timeout=2000):
        pass  # second emission: probe completion

    assert store.manifest.sessions[0].has_stable_identities is True


def test_add_session_leaves_has_stable_identities_none_on_probe_failure(
    qtbot, monkeypatch, store, tmp_path: Path
) -> None:
    def fake_read_session(folder: Path) -> Session:
        raise RuntimeError("not a real session folder")

    monkeypatch.setattr("track2data.readers.read_session", fake_read_session)

    logged: list[str] = []
    store.runLogAppended.connect(logged.append)

    folder = tmp_path / "session_a"
    folder.mkdir()

    with qtbot.waitSignal(store.sessionsChanged, timeout=1000):
        store.add_session(folder)

    with qtbot.waitSignal(store.runLogAppended, timeout=2000):
        pass

    assert store.manifest.sessions[0].has_stable_identities is None
    assert any("Identity probe failed" in line for line in logged)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui/test_project_store.py -v`
Expected: FAIL — `test_add_session_fills_in_has_stable_identities_on_probe_success` and the failure-path test time out waiting for a second `sessionsChanged`/`runLogAppended` emission that never comes (today's `add_session` never probes anything).

- [ ] **Step 3: Write minimal implementation**

In `ui/store/project_store.py`, change the import block:

```python
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
```

to:

```python
from __future__ import annotations

from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any
```

Change `__init__`:

```python
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._manifest: ProjectManifest | None = None
        self._project_dir: Path | None = None
        self._run_results: RunResult | None = None

        self._tasks = TaskRunner(self)
        self._tasks.taskProgress.connect(self.taskProgress)
        self._tasks.taskFinished.connect(self.taskFinished)
        self._tasks.taskFailed.connect(self._on_task_failed)
        self._tasks.taskLog.connect(lambda _task_id, line: self.append_log(line))
```

to:

```python
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._manifest: ProjectManifest | None = None
        self._project_dir: Path | None = None
        self._run_results: RunResult | None = None
        self._identity_probes: dict[str, str] = {}  # task_id -> session_id

        self._tasks = TaskRunner(self)
        self._tasks.taskProgress.connect(self.taskProgress)
        self._tasks.taskFinished.connect(self.taskFinished)
        self._tasks.taskFailed.connect(self._on_task_failed)
        self._tasks.taskLog.connect(lambda _task_id, line: self.append_log(line))
        self.taskFinished.connect(self._on_identity_probe_finished)
```

Change `add_session`:

```python
    def add_session(self, folder: Path) -> None:
        """Append a new SessionRef for *folder* and emit sessionsChanged."""
        if self._manifest is None:
            return
        session_id = folder.name
        ref = SessionRef(session_id=session_id, folder=folder, sha256="")
        sessions = [*list(self._manifest.sessions), ref]
        self._manifest = self._manifest.model_copy(update={"sessions": sessions})
        self.sessionsChanged.emit()
```

to:

```python
    def add_session(self, folder: Path) -> None:
        """Append a new SessionRef for *folder*, emit sessionsChanged, and
        submit a background probe (see _on_identity_probe_finished) that
        fills in has_stable_identities once the reader has read it."""
        if self._manifest is None:
            return
        from track2data.readers import read_session

        session_id = folder.name
        ref = SessionRef(session_id=session_id, folder=folder, sha256="")
        sessions = [*list(self._manifest.sessions), ref]
        self._manifest = self._manifest.model_copy(update={"sessions": sessions})
        self.sessionsChanged.emit()

        task_id = self._tasks.submit(partial(read_session, folder))
        self._identity_probes[task_id] = session_id

    def _on_identity_probe_finished(self, task_id: str, result: object) -> None:
        session_id = self._identity_probes.pop(task_id, None)
        if session_id is None:
            return  # not an identity-probe task (e.g. a pipeline run/preview)
        if isinstance(result, Exception):
            self.append_log(f"_Identity probe failed for `{session_id}`: {result}_\n")
            return
        self._set_session_identity(session_id, result.has_stable_identities)

    def _set_session_identity(self, session_id: str, has_stable_identities: bool) -> None:
        if self._manifest is None:
            return
        sessions = [
            s.model_copy(update={"has_stable_identities": has_stable_identities})
            if s.session_id == session_id else s
            for s in self._manifest.sessions
        ]
        self._manifest = self._manifest.model_copy(update={"sessions": sessions})
        self.sessionsChanged.emit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ui/test_project_store.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add ui/store/project_store.py tests/test_ui/test_project_store.py
git commit -m "feat(store): probe has_stable_identities in the background on add_session"
```

---

## Task 3: `MetricInfoDialog` rewrite (Metric class, copy-citation, close behavior)

**Files:**
- Modify (full rewrite): `ui/dialogs/metric_info_dialog.py`
- Modify (full rewrite): `tests/test_ui/test_metric_info_dialog.py`

- [ ] **Step 1: Write the failing tests**

Replace the entire contents of `tests/test_ui/test_metric_info_dialog.py` with:

```python
"""
Tests for ui/dialogs/metric_info_dialog.py -- a read-only dialog that
renders a Metric subclass's `MetricDocumentation`. The dialog takes a
`Metric` class directly (the caller already has it from the registry),
not a metric_id string to look up.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QTextEdit, QWidget

from track2data import metrics


def _dialog_text(widget) -> str:
    """Collect every bit of visible/plain text under *widget*.

    Assertions below check for real ``MetricDocumentation`` content, so
    tests shouldn't care whether that content lives in a QLabel or a
    QTextEdit -- only that it's genuinely on screen somewhere.
    """
    chunks = [widget.windowTitle()]
    for lbl in widget.findChildren(QLabel):
        chunks.append(lbl.text())
    for edit in widget.findChildren(QTextEdit):
        chunks.append(edit.toPlainText())
    for edit in widget.findChildren(QPlainTextEdit):
        chunks.append(edit.toPlainText())
    return "\n".join(chunks)


# ── MetricInfoDialog: real, fully-documented metric ─────────────────────────


def test_dialog_shows_id_name_and_label_for_a_known_metric(qtbot) -> None:
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    dlg = MetricInfoDialog(metrics.get("IL-1"))
    qtbot.addWidget(dlg)
    text = _dialog_text(dlg)

    assert "IL-1" in text
    assert "path_length" in text
    assert "Distance Travelled" in text


def test_dialog_shows_real_definition_and_formula_text(qtbot) -> None:
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    dlg = MetricInfoDialog(metrics.get("IL-1"))
    qtbot.addWidget(dlg)
    text = _dialog_text(dlg)

    assert "Total distance travelled by each individual over the session." in text
    assert "sum of ||xy[t+1,k] - xy[t,k]|| for non-NaN consecutive frame pairs" in text


def test_dialog_shows_inputs_assumptions_and_warnings(qtbot) -> None:
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    dlg = MetricInfoDialog(metrics.get("IL-1"))
    qtbot.addWidget(dlg)
    text = _dialog_text(dlg)

    assert "PreprocessedSession.xy" in text
    assert "Post-smoothing xy is used; gaps produce no displacement" in text
    assert "Under-smoothed data inflates path length" in text


def test_dialog_shows_citation_and_doi_when_present(qtbot) -> None:
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    # GL-3 (Polarisation) has both citation and citation_doi set.
    dlg = MetricInfoDialog(metrics.get("GL-3"))
    qtbot.addWidget(dlg)
    text = _dialog_text(dlg)

    assert "Couzin et al. 2002, J. Theor. Biol." in text
    assert "10.1006/jtbi.2002.3065" in text


def test_dialog_shows_formula_latex_source_when_present(qtbot) -> None:
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    # D-1 (TrackingCoverage) is the one built-in metric with formula_latex
    # set. Per the issue, a plain-text dump of the LaTeX source is an
    # acceptable "not feasible to render" fallback -- no LaTeX renderer.
    dlg = MetricInfoDialog(metrics.get("D-1"))
    qtbot.addWidget(dlg)
    text = _dialog_text(dlg)

    assert r"\text{coverage}_k" in text
    # D-1 has no citation -- make sure that doesn't leak a literal "None".
    assert "None" not in text


# ── Copy citation ────────────────────────────────────────────────────────────


def test_copy_citation_button_disabled_when_no_citation(qtbot) -> None:
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    dlg = MetricInfoDialog(metrics.get("D-1"))  # no citation
    qtbot.addWidget(dlg)

    assert dlg._copy_citation_btn.isEnabled() is False


def test_copy_citation_button_writes_citation_and_doi_to_clipboard(qtbot) -> None:
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    dlg = MetricInfoDialog(metrics.get("GL-3"))
    qtbot.addWidget(dlg)

    dlg._copy_citation_btn.click()

    clipboard_text = QGuiApplication.clipboard().text()
    assert "Couzin et al. 2002, J. Theor. Biol." in clipboard_text
    assert "10.1006/jtbi.2002.3065" in clipboard_text


# ── Close behaviour ───────────────────────────────────────────────────────────


def test_escape_key_closes_the_dialog(qtbot) -> None:
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    dlg = MetricInfoDialog(metrics.get("IL-1"))
    qtbot.addWidget(dlg)
    dlg.show()

    qtbot.keyClick(dlg, Qt.Key.Key_Escape)

    assert dlg.isVisible() is False


def test_click_outside_dialog_closes_it(qtbot) -> None:
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    other = QWidget()
    qtbot.addWidget(other)
    other.move(2000, 2000)
    other.resize(50, 50)
    other.show()

    dlg = MetricInfoDialog(metrics.get("IL-1"))
    qtbot.addWidget(dlg)
    dlg.move(0, 0)
    dlg.show()

    qtbot.mouseClick(other, Qt.MouseButton.LeftButton)

    assert dlg.isVisible() is False


def test_click_inside_dialog_does_not_close_it(qtbot) -> None:
    from ui.dialogs.metric_info_dialog import MetricInfoDialog

    dlg = MetricInfoDialog(metrics.get("IL-1"))
    qtbot.addWidget(dlg)
    dlg.show()

    qtbot.mouseClick(dlg, Qt.MouseButton.LeftButton)

    assert dlg.isVisible() is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui/test_metric_info_dialog.py -v`
Expected: FAIL — `MetricInfoDialog(metrics.get("IL-1"))` raises because the current constructor expects a string `metric_id` and calls `metrics.get(metric_id)` on it (a `type[Metric]` object, not a string); `_copy_citation_btn` doesn't exist.

- [ ] **Step 3: Write minimal implementation**

Replace the entire contents of `ui/dialogs/metric_info_dialog.py` with:

```python
"""
Metric info dialog -- a read-only ``QDialog`` that renders a
``Metric`` subclass's ``documentation: MetricDocumentation`` --
definition, formula, inputs, assumptions, warnings, and citation. See
``docs/METRICS_SPEC.md`` §5.2/§6 for the canonical field list.
``formula_latex`` is shown as a raw LaTeX source string (no renderer)
-- the "not feasible to render" fallback the spec itself allows.

Closes on the title-bar close button, Escape (QDialog's own default
behaviour), or a click outside the dialog's own rect (a
QApplication-wide event filter installed for the dialog's lifetime).
"""

from __future__ import annotations

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from track2data.metrics.base import Metric


class MetricInfoDialog(QDialog):
    """Read-only popup showing the documentation for one metric."""

    def __init__(self, metric_cls: type[Metric], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._metric_cls = metric_cls
        self.setWindowTitle(f"Metric info — {metric_cls.id}")
        self.resize(480, 420)
        self.setModal(True)

        layout = QVBoxLayout(self)

        header = QLabel(f"{metric_cls.id} — {metric_cls.name} ({metric_cls.label})")
        header.setStyleSheet("font-weight: bold; font-size: 14px;")
        header.setWordWrap(True)
        layout.addWidget(header)

        body = QTextEdit()
        body.setReadOnly(True)
        body.setPlainText(self._format_documentation(metric_cls))
        layout.addWidget(body)

        footer = QHBoxLayout()
        doc = metric_cls.documentation
        self._copy_citation_btn = QPushButton("Copy citation")
        self._copy_citation_btn.setEnabled(doc.citation is not None)
        self._copy_citation_btn.clicked.connect(self._copy_citation)
        footer.addWidget(self._copy_citation_btn)
        footer.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(90)
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        layout.addLayout(footer)

    def _copy_citation(self) -> None:
        doc = self._metric_cls.documentation
        if doc.citation is None:
            return
        text = doc.citation
        if doc.citation_doi:
            text += f" (DOI: {doc.citation_doi})"
        QApplication.clipboard().setText(text)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def hideEvent(self, event) -> None:
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        super().hideEvent(event)

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if event.type() == QEvent.Type.MouseButtonPress:
            local_pos = self.mapFromGlobal(event.globalPosition().toPoint())
            if not self.rect().contains(local_pos):
                self.reject()
                return True
        return super().eventFilter(watched, event)

    @staticmethod
    def _format_documentation(metric_cls: type[Metric]) -> str:
        """Render a MetricDocumentation as readable multi-line plain text."""
        doc = metric_cls.documentation
        lines: list[str] = ["Definition:", doc.definition, "", "Formula:", doc.formula_plain]

        if doc.formula_latex:
            lines += ["", "Formula (LaTeX source):", doc.formula_latex]

        lines += ["", "Inputs:"]
        lines += [f"- {item}" for item in doc.inputs]

        lines += ["", "Assumptions:"]
        lines += [f"- {item}" for item in doc.assumptions]

        lines += ["", "Warnings:"]
        lines += [f"- {item}" for item in doc.warnings]

        if doc.citation:
            citation_line = doc.citation
            if doc.citation_doi:
                citation_line += f" (DOI: {doc.citation_doi})"
            lines += ["", "Citation:", citation_line]

        return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ui/test_metric_info_dialog.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add ui/dialogs/metric_info_dialog.py tests/test_ui/test_metric_info_dialog.py
git commit -m "feat(ui): MetricInfoDialog takes a Metric class, adds copy-citation and outside-click close"
```

---

## Task 4: `MetricsScreen` — `QTableWidget` skeleton, registry-driven rows

**Files:**
- Modify (full rewrite): `ui/metrics_screen.py`
- Create: `tests/test_ui/test_metrics_screen.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ui/test_metrics_screen.py`:

```python
"""
Tests for ui/metrics_screen.py -- the registry-driven QTableWidget
metrics-selection screen. See
docs/superpowers/specs/2026-08-21-metrics-screen-info-dialog-redesign-design.md
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt

from track2data import metrics
from track2data.core.models import MetricSelection, ProjectManifest


def _make_store():
    from ui.store.project_store import ProjectStore

    now = datetime.now(tz=UTC)
    store = ProjectStore()
    store._manifest = ProjectManifest(project_name="test_project", created_at=now, updated_at=now)
    return store


def _row_for_id(table, metric_id: str) -> int:
    for row in range(table.rowCount()):
        if table.item(row, 1).text() == metric_id:
            return row
    raise AssertionError(f"{metric_id} not found in table")


# ── registry-driven rows ──────────────────────────────────────────────────────


def test_individual_tab_has_one_row_per_registered_individual_metric(qtbot) -> None:
    from ui.metrics_screen import MetricsScreen

    screen = MetricsScreen()
    qtbot.addWidget(screen)

    expected_ids = sorted(m.id for m in metrics.list_for_level("individual"))
    actual_ids = [
        screen._ind_table.item(row, 1).text() for row in range(screen._ind_table.rowCount())
    ]
    assert actual_ids == expected_ids


def test_group_tab_has_one_row_per_registered_group_metric(qtbot) -> None:
    from ui.metrics_screen import MetricsScreen

    screen = MetricsScreen()
    qtbot.addWidget(screen)

    expected_ids = sorted(m.id for m in metrics.list_for_level("group"))
    actual_ids = [
        screen._grp_table.item(row, 1).text() for row in range(screen._grp_table.rowCount())
    ]
    assert actual_ids == expected_ids


# ── checkbox selection round-trip ─────────────────────────────────────────────


def test_apply_selection_reads_checked_rows_from_each_tab(qtbot) -> None:
    from ui.metrics_screen import MetricsScreen

    store = _make_store()
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)

    row = _row_for_id(screen._ind_table, "IL-1")
    screen._ind_table.item(row, 0).setCheckState(Qt.CheckState.Checked)

    screen._apply()

    assert store.manifest.metrics.individual == ["IL-1"]


def test_load_from_store_checks_rows_matching_the_manifest_selection(qtbot) -> None:
    from ui.metrics_screen import MetricsScreen

    store = _make_store()
    store._manifest = store._manifest.model_copy(
        update={"metrics": MetricSelection(individual=["IL-1"])}
    )
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)

    store.metricsChanged.emit()

    row = _row_for_id(screen._ind_table, "IL-1")
    assert screen._ind_table.item(row, 0).checkState() == Qt.CheckState.Checked
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui/test_metrics_screen.py -v`
Expected: FAIL — `ui/metrics_screen.py` doesn't have `_ind_table`/`_grp_table` yet (current attributes are `_ind_list`/`_grp_list`, `QListWidget`-based).

- [ ] **Step 3: Write minimal implementation**

Replace the entire contents of `ui/metrics_screen.py` with:

```python
"""
Stage 6b — Metric selection screen (registry-driven QTableWidget).

QTabWidget with three tabs: Individual / Group / Zone. Each tab is a
QTableWidget populated from track2data.metrics.list_for_level(level),
columns: include (checkbox) / metric_id / metric_name / info (ⓘ) /
config (⚙, stub). Quality threshold QDoubleSpinBox + Apply button.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from track2data import metrics
from track2data.core.models import MetricSelection

_COLUMN_HEADERS = ["Include", "ID", "Name", "Info", "Config"]
_COL_INCLUDE, _COL_ID, _COL_NAME, _COL_INFO, _COL_CONFIG = range(5)
_ROLE_METRIC_ID = Qt.ItemDataRole.UserRole
_ROLE_REQUIRES_IDENTITY = Qt.ItemDataRole.UserRole + 1


class MetricsScreen(QWidget):
    """Stage 6b — Select behavioural metrics to compute."""

    def __init__(self, store=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._build_ui()
        if store is not None:
            store.metricsChanged.connect(self._load_from_store)
            store.projectChanged.connect(self._load_from_store)

    # ── build ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(48, 36, 48, 36)
        root.setSpacing(16)

        title = QLabel("Metrics")
        title.setStyleSheet("font-size: 26px; font-weight: bold; color: #2c3e50;")
        root.addWidget(title)

        subtitle = QLabel("Choose which behavioural metrics to extract.")
        subtitle.setStyleSheet("font-size: 14px; color: #555;")
        root.addWidget(subtitle)

        self._tabs = QTabWidget()

        self._ind_table = self._make_table("individual")
        self._grp_table = self._make_table("group")
        self._zone_table = self._make_table("zone")

        self._tabs.addTab(self._ind_table, "Individual")
        self._tabs.addTab(self._grp_table, "Group")
        self._tabs.addTab(self._zone_table, "Zone")

        root.addWidget(self._tabs, 1)

        qform = QFormLayout()
        self._quality_spin = QDoubleSpinBox()
        self._quality_spin.setRange(0.0, 1.0)
        self._quality_spin.setSingleStep(0.05)
        self._quality_spin.setDecimals(2)
        self._quality_spin.setValue(0.0)
        qform.addRow("Quality threshold:", self._quality_spin)
        root.addLayout(qform)

        apply_btn = QPushButton("Apply selection")
        apply_btn.setFixedWidth(130)
        apply_btn.clicked.connect(self._apply)
        root.addWidget(apply_btn)

    def _make_table(self, level: str) -> QTableWidget:
        metric_classes = sorted(metrics.list_for_level(level), key=lambda m: m.id)
        table = QTableWidget(len(metric_classes), len(_COLUMN_HEADERS))
        table.setHorizontalHeaderLabels(_COLUMN_HEADERS)
        table.horizontalHeader().setSectionResizeMode(
            _COL_NAME, QHeaderView.ResizeMode.Stretch
        )
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        for row, metric_cls in enumerate(metric_classes):
            include_item = QTableWidgetItem()
            include_item.setFlags(
                include_item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
            )
            include_item.setCheckState(Qt.CheckState.Unchecked)
            include_item.setData(_ROLE_METRIC_ID, metric_cls.id)
            include_item.setData(_ROLE_REQUIRES_IDENTITY, metric_cls.requires_identity)
            table.setItem(row, _COL_INCLUDE, include_item)

            table.setItem(row, _COL_ID, QTableWidgetItem(metric_cls.id))
            table.setItem(row, _COL_NAME, QTableWidgetItem(metric_cls.name))

        return table

    # ── slots ──────────────────────────────────────────────────────────────

    def _checked_ids(self, table: QTableWidget) -> list[str]:
        result = []
        for row in range(table.rowCount()):
            item = table.item(row, _COL_INCLUDE)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                result.append(item.data(_ROLE_METRIC_ID))
        return result

    def _apply(self) -> None:
        if self._store is None:
            QMessageBox.information(self, "Info", "No project open.")
            return
        sel = MetricSelection(
            individual=self._checked_ids(self._ind_table),
            group=self._checked_ids(self._grp_table),
            zone=self._checked_ids(self._zone_table),
            quality_threshold=self._quality_spin.value(),
        )
        try:
            self._store.update_metrics(sel)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to apply metric selection:\n{exc}")

    def _load_from_store(self) -> None:
        if self._store is None or self._store.manifest is None:
            return
        sel = self._store.manifest.metrics
        self._set_checked(self._ind_table, sel.individual)
        self._set_checked(self._grp_table, sel.group)
        self._set_checked(self._zone_table, sel.zone)
        self._quality_spin.setValue(sel.quality_threshold)

    @staticmethod
    def _set_checked(table: QTableWidget, ids: list[str]) -> None:
        for row in range(table.rowCount()):
            item = table.item(row, _COL_INCLUDE)
            if item is not None:
                state = (
                    Qt.CheckState.Checked
                    if item.data(_ROLE_METRIC_ID) in ids
                    else Qt.CheckState.Unchecked
                )
                item.setCheckState(state)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ui/test_metrics_screen.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add ui/metrics_screen.py tests/test_ui/test_metrics_screen.py
git commit -m "feat(ui): rewrite MetricsScreen as a registry-driven QTableWidget"
```

---

## Task 5: `MetricsScreen` — per-row ⓘ / ⚙ buttons

**Files:**
- Modify: `ui/metrics_screen.py`
- Modify: `tests/test_ui/test_metrics_screen.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ui/test_metrics_screen.py`:

```python

# ── per-row ⓘ / ⚙ buttons ─────────────────────────────────────────────────────


def test_every_row_has_a_config_stub_button_that_shows_a_message(qtbot, monkeypatch) -> None:
    from ui.metrics_screen import MetricsScreen

    messages: list[str] = []
    monkeypatch.setattr(
        "ui.metrics_screen.QMessageBox.information",
        staticmethod(lambda *a, **k: messages.append(a[2]) or None),
    )

    screen = MetricsScreen()
    qtbot.addWidget(screen)

    row = _row_for_id(screen._ind_table, "IL-1")
    screen._ind_table.cellWidget(row, 4).click()

    assert messages == ["Per-metric configuration isn't available yet."]


def test_info_button_opens_metric_info_dialog_for_that_row(qtbot, monkeypatch) -> None:
    from ui.metrics_screen import MetricsScreen

    opened: list[str] = []

    class _StubDialog:
        def __init__(self, metric_cls, parent=None) -> None:
            opened.append(metric_cls.id)

        def exec(self) -> None:
            return None

    monkeypatch.setattr("ui.metrics_screen.MetricInfoDialog", _StubDialog)

    screen = MetricsScreen()
    qtbot.addWidget(screen)

    row = _row_for_id(screen._ind_table, "IL-1")
    screen._ind_table.cellWidget(row, 3).click()

    assert opened == ["IL-1"]


def test_info_button_is_absent_when_metric_has_no_formula_or_citation(qtbot, monkeypatch) -> None:
    from track2data.metrics.base import MetricDocumentation
    from ui.metrics_screen import MetricsScreen

    class _NoDocMetric:
        id = "X-1"
        name = "No-doc metric"
        label = "No-doc metric"
        level = "individual"
        priority = "diagnostic"
        requires_identity = False
        output_columns: list[str] = []
        documentation = MetricDocumentation.model_construct(
            definition="d", formula_plain=None, inputs=[], assumptions=[],
            warnings=[], citation=None, citation_doi=None,
        )

    monkeypatch.setattr("ui.metrics_screen.metrics.list_for_level", lambda level: [_NoDocMetric])

    screen = MetricsScreen()
    qtbot.addWidget(screen)

    assert screen._ind_table.cellWidget(0, 3) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui/test_metrics_screen.py -v -k "config_stub or info_button"`
Expected: FAIL — no cell widgets exist yet at columns 3/4.

- [ ] **Step 3: Write minimal implementation**

In `ui/metrics_screen.py`, change the top of the file:

```python
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from track2data import metrics
from track2data.core.models import MetricSelection
```

to:

```python
from __future__ import annotations

from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from track2data import metrics
from track2data.core.models import MetricSelection
from ui.dialogs.metric_info_dialog import MetricInfoDialog
```

Change the `_make_table` per-row loop:

```python
            table.setItem(row, _COL_ID, QTableWidgetItem(metric_cls.id))
            table.setItem(row, _COL_NAME, QTableWidgetItem(metric_cls.name))

        return table
```

to:

```python
            table.setItem(row, _COL_ID, QTableWidgetItem(metric_cls.id))
            table.setItem(row, _COL_NAME, QTableWidgetItem(metric_cls.name))

            doc = metric_cls.documentation
            if doc.formula_plain is not None or doc.citation is not None:
                info_btn = QPushButton("ⓘ")
                info_btn.setFixedWidth(28)
                info_btn.clicked.connect(partial(self._show_metric_info, metric_cls))
                table.setCellWidget(row, _COL_INFO, info_btn)

            config_btn = QPushButton("⚙")
            config_btn.setFixedWidth(28)
            config_btn.clicked.connect(self._show_config_stub)
            table.setCellWidget(row, _COL_CONFIG, config_btn)

        return table
```

Add two new methods right after `_make_table`:

```python
    def _show_metric_info(self, metric_cls) -> None:
        dlg = MetricInfoDialog(metric_cls, self)
        dlg.exec()

    def _show_config_stub(self) -> None:
        QMessageBox.information(
            self, "Not yet implemented", "Per-metric configuration isn't available yet."
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ui/test_metrics_screen.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add ui/metrics_screen.py tests/test_ui/test_metrics_screen.py
git commit -m "feat(ui): wire per-row info button to MetricInfoDialog, add config stub button"
```

---

## Task 6: `MetricsScreen` — identity graying + zone-tab disabling

**Files:**
- Modify: `ui/metrics_screen.py`
- Modify: `tests/test_ui/test_metrics_screen.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ui/test_metrics_screen.py` (also add `from pathlib import Path` to the top-of-file imports):

```python

# ── identity-aware graying ────────────────────────────────────────────────────


def test_identity_required_rows_greyed_when_every_session_lacks_stable_identities(qtbot) -> None:
    from track2data.core.models import SessionRef
    from ui.metrics_screen import MetricsScreen

    store = _make_store()
    store._manifest = store._manifest.model_copy(
        update={
            "sessions": [
                SessionRef(
                    session_id="s1", folder=Path("s1"), sha256="x",
                    has_stable_identities=False,
                ),
            ]
        }
    )
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)

    row = _row_for_id(screen._ind_table, "IL-1")  # IL-1.requires_identity is True
    include_item = screen._ind_table.item(row, 0)
    assert not (include_item.flags() & Qt.ItemFlag.ItemIsEnabled)


def test_rows_not_greyed_when_sessions_are_unprobed(qtbot) -> None:
    from track2data.core.models import SessionRef
    from ui.metrics_screen import MetricsScreen

    store = _make_store()
    store._manifest = store._manifest.model_copy(
        update={"sessions": [SessionRef(session_id="s1", folder=Path("s1"), sha256="x")]}
    )
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)

    row = _row_for_id(screen._ind_table, "IL-1")
    include_item = screen._ind_table.item(row, 0)
    assert bool(include_item.flags() & Qt.ItemFlag.ItemIsEnabled)


def test_rows_not_greyed_when_at_least_one_session_has_stable_identities(qtbot) -> None:
    from track2data.core.models import SessionRef
    from ui.metrics_screen import MetricsScreen

    store = _make_store()
    store._manifest = store._manifest.model_copy(
        update={
            "sessions": [
                SessionRef(
                    session_id="s1", folder=Path("s1"), sha256="x",
                    has_stable_identities=False,
                ),
                SessionRef(
                    session_id="s2", folder=Path("s2"), sha256="y",
                    has_stable_identities=True,
                ),
            ]
        }
    )
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)

    row = _row_for_id(screen._ind_table, "IL-1")
    include_item = screen._ind_table.item(row, 0)
    assert bool(include_item.flags() & Qt.ItemFlag.ItemIsEnabled)


# ── zone tab disabling ────────────────────────────────────────────────────────


def test_zone_tab_disabled_when_no_zones_defined(qtbot) -> None:
    from ui.metrics_screen import MetricsScreen

    store = _make_store()
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)

    zone_index = screen._tabs.indexOf(screen._zone_table)
    assert screen._tabs.isTabEnabled(zone_index) is False


def test_zone_tab_enabled_when_zones_are_defined(qtbot) -> None:
    from track2data.core.models import ROI, ZoneSet
    from ui.metrics_screen import MetricsScreen

    store = _make_store()
    store._manifest = store._manifest.model_copy(
        update={"zones": ZoneSet(rois=[ROI(name="arena", vertices=[(0, 0), (1, 0), (1, 1)])])}
    )
    screen = MetricsScreen(store=store)
    qtbot.addWidget(screen)

    zone_index = screen._tabs.indexOf(screen._zone_table)
    assert screen._tabs.isTabEnabled(zone_index) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui/test_metrics_screen.py -v -k "greyed or zone_tab"`
Expected: FAIL — graying/zone-tab-disabling logic doesn't exist yet (all rows enabled, zone tab always enabled).

- [ ] **Step 3: Write minimal implementation**

In `ui/metrics_screen.py`, change `__init__`:

```python
    def __init__(self, store=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._build_ui()
        if store is not None:
            store.metricsChanged.connect(self._load_from_store)
            store.projectChanged.connect(self._load_from_store)
```

to:

```python
    def __init__(self, store=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._build_ui()
        if store is not None:
            store.metricsChanged.connect(self._load_from_store)
            store.projectChanged.connect(self._load_from_store)
            store.sessionsChanged.connect(self._update_identity_graying)
            store.zonesChanged.connect(self._update_zone_tab_enabled)
            self._update_identity_graying()
            self._update_zone_tab_enabled()
```

Change `_load_from_store`:

```python
    def _load_from_store(self) -> None:
        if self._store is None or self._store.manifest is None:
            return
        sel = self._store.manifest.metrics
        self._set_checked(self._ind_table, sel.individual)
        self._set_checked(self._grp_table, sel.group)
        self._set_checked(self._zone_table, sel.zone)
        self._quality_spin.setValue(sel.quality_threshold)
```

to:

```python
    def _load_from_store(self) -> None:
        if self._store is None or self._store.manifest is None:
            return
        sel = self._store.manifest.metrics
        self._set_checked(self._ind_table, sel.individual)
        self._set_checked(self._grp_table, sel.group)
        self._set_checked(self._zone_table, sel.zone)
        self._quality_spin.setValue(sel.quality_threshold)
        self._update_identity_graying()
        self._update_zone_tab_enabled()
```

Add two new methods right after `_load_from_store` (before the `_set_checked` staticmethod):

```python
    def _update_identity_graying(self) -> None:
        if self._store is None or self._store.manifest is None:
            return
        sessions = self._store.manifest.sessions
        probed = [
            s.has_stable_identities for s in sessions if s.has_stable_identities is not None
        ]
        all_identity_free = bool(probed) and all(not v for v in probed)

        for table in (self._ind_table, self._grp_table, self._zone_table):
            for row in range(table.rowCount()):
                include_item = table.item(row, _COL_INCLUDE)
                id_item = table.item(row, _COL_ID)
                if include_item is None or id_item is None:
                    continue
                requires_identity = bool(include_item.data(_ROLE_REQUIRES_IDENTITY))
                flags = include_item.flags()
                if requires_identity and all_identity_free:
                    include_item.setFlags(flags & ~Qt.ItemFlag.ItemIsEnabled)
                    id_item.setToolTip(
                        "No session in this project has stable identities; "
                        "this metric will be skipped for every session."
                    )
                else:
                    include_item.setFlags(flags | Qt.ItemFlag.ItemIsEnabled)
                    id_item.setToolTip("")

    def _update_zone_tab_enabled(self) -> None:
        if self._store is None or self._store.manifest is None:
            return
        zone_index = self._tabs.indexOf(self._zone_table)
        self._tabs.setTabEnabled(zone_index, bool(self._store.manifest.zones.rois))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ui/test_metrics_screen.py -v`
Expected: PASS (12 tests)

- [ ] **Step 5: Commit**

```bash
git add ui/metrics_screen.py tests/test_ui/test_metrics_screen.py
git commit -m "feat(ui): grey identity-required rows and disable the zone tab when unavailable"
```

---

## Task 7: Docs reconciliation

**Files:**
- Modify: `docs/UI_DESIGN.md`
- Modify: `docs/METRICS_SPEC.md`

- [ ] **Step 1: Update `docs/UI_DESIGN.md`'s Page 6 metric-catalogue paragraph**

Change:

```markdown
**Right — metric catalogue:** three tabs (Individual / Group / Zone)
populated from `metrics.registry.list_for_level(level)`. Each row =
checkbox + name + ⓘ icon + per-metric config button. Identity-aware
metrics greyed-out for identity-free sessions with an explanatory
tooltip.
```

to:

```markdown
**Right — metric catalogue:** three tabs (Individual / Group / Zone)
populated from `metrics.list_for_level(level)`. Each row = checkbox +
id + name + ⓘ icon + ⚙ config icon (stub in v1 — see below).
Identity-aware metrics (`Metric.requires_identity`) greyed-out when
every session in the project has `has_stable_identities is False`,
with an explanatory tooltip. Zone tab disabled when no zones are
defined.
```

- [ ] **Step 2: Update the `MetricInfoDialog (info-button modal)` subsection**

Change:

```markdown
#### MetricInfoDialog (info-button modal)

Clicking the ⓘ icon next to a metric opens a `MetricInfoDialog`
(`QDialog` subclass) that renders the metric's `documentation:
MetricDocumentation` field:

- Definition · Formula · Inputs · Assumptions / warnings · Reference
- Footer button: **Copy citation** (writes citation + DOI to clipboard)
- Closes on: ✕ button · `Escape` key · click outside the dialog area
  (`setModal(True)` + a `mousePressEvent` hook on the dimmed overlay)

The ⓘ icon is **hidden** when both `documentation.formula_plain` and
`documentation.citation` are `None` — those metrics fall back to the
existing tooltip-only behaviour. See
[`METRICS_SPEC.md` §6](./METRICS_SPEC.md) for the canonical
architecture and the per-metric content this dialog renders.
```

to:

```markdown
#### MetricInfoDialog (info-button modal)

Clicking the ⓘ icon next to a metric opens a `MetricInfoDialog`
(`QDialog` subclass, constructed from a `Metric` class — not an id
string) that renders the metric's `documentation:
MetricDocumentation` field:

- Definition · Formula · Inputs · Assumptions / warnings · Reference
- Footer button: **Copy citation** (writes citation + DOI to clipboard)
- Closes on: title-bar ✕ · `Escape` key (QDialog's own default
  behaviour) · click outside the dialog's rect (a QApplication-wide
  event filter installed for the dialog's lifetime, not a separate
  overlay widget)

The ⓘ icon is **hidden** when both `documentation.formula_plain` and
`documentation.citation` are `None` — those metrics fall back to the
existing tooltip-only behaviour. In practice this never currently
hides anything, since `MetricDocumentation.formula_plain` is a
required (non-`None`) `str` field on every built-in metric today; the
check is implemented as specified for forward compatibility. See
[`METRICS_SPEC.md` §6](./METRICS_SPEC.md) for the canonical
architecture and the per-metric content this dialog renders.
```

- [ ] **Step 3: Update §6.10 Screen 6.2's per-tab structure, MetricInfoDialog, data bindings, and validation rules**

Change:

```markdown
**Per-tab structure:**
- QTableWidget: `metric_list`
  - Columns: `include` (checkbox), `metric_id`, `metric_name`, `info` (ⓘ icon), `config` (⚙ icon)
  - Rows: auto-populated from `metrics.registry` filtered by level
  - Greyed rows: identity-aware metrics for identity-free sessions (with tooltip)
  - Greyed Zone tab if no zones defined on Stage 4

**MetricInfoDialog (Modal):**
- Opens on ⓘ click
- Renders `Metric.documentation` fields (definition, formula_plain, formula_latex, inputs, assumptions, warnings, citation, citation_doi)
- Footer button: "Copy citation" (to clipboard)
- Close: ✕, Escape, or outside-click

**Data Bindings:**
- Checkboxes ↔ `ProjectStore.metrics.individual` / `.group` / `.zone`

**Validation Rules:**
- ≥1 metric selected across all tabs (required)
- Identity-free sessions → IL-* greyed (still count if checked; engine skips per-session)
- No zones → Z-* tab disabled
```

to:

```markdown
**Per-tab structure:**
- QTableWidget: `metric_list`
  - Columns: `include` (checkbox), `metric_id`, `metric_name`, `info` (ⓘ icon), `config` (⚙ icon — **stub in v1**: shows "Not yet implemented"; no Screen 6.3 or config schema exists yet)
  - Rows: auto-populated from `metrics.list_for_level(level)`
  - Greyed rows: metrics where `Metric.requires_identity` is `True`, when every session in the project has `has_stable_identities is False` (with tooltip). Sessions with `has_stable_identities is None` (not yet probed, or probe failed) are treated as unknown, not identity-free — they don't trigger greying.
  - Disabled Zone tab if no zones defined on Stage 4

**MetricInfoDialog (Modal):**
- Opens on ⓘ click, constructed from the row's `Metric` class directly
- Renders `Metric.documentation` fields (definition, formula_plain, formula_latex, inputs, assumptions, warnings, citation, citation_doi)
- Footer button: "Copy citation" (to clipboard)
- Close: title-bar ✕, Escape, or a click outside the dialog's rect (QApplication-wide event filter)

**Data Bindings:**
- Checkboxes ↔ `ProjectStore.metrics.individual` / `.group` / `.zone`
- `SessionRef.has_stable_identities` ↔ populated by a background probe (`read_session` via `TaskRunner`) when a session is added in Stage 2

**Validation Rules:**
- ≥1 metric selected across all tabs (required)
- Identity-free sessions → rows for `requires_identity` metrics greyed when *every* session lacks stable identities (still count if checked; engine skips per-session)
- No zones → Z-* tab disabled
```

- [ ] **Step 4: Update `docs/METRICS_SPEC.md` §6.1 surface diagram**

Change:

```markdown
### 6.1 Surface

In `UI_DESIGN.md` Page 6, each row in the metric-selection list becomes:

```
[ ✓ ]  IL-2 Speed (mean/median/max)         ⓘ   ⚙
```

- ✓ — selection checkbox (existing)
- ⓘ — info icon (NEW)
- ⚙ — per-metric config (existing; some metrics only)
```

to:

```markdown
### 6.1 Surface

In `UI_DESIGN.md` Page 6, each row in the metric-selection list becomes:

```
[ ✓ ]  IL-2 Speed (mean/median/max)         ⓘ   ⚙
```

- ✓ — selection checkbox (existing)
- ⓘ — info icon
- ⚙ — per-metric config — **stub in v1**: present on every row, but
  clicking it shows a "Not yet implemented" message. No metric has a
  config schema and Screen 6.3 does not exist yet.
```

- [ ] **Step 5: Update §6.3 close behaviour**

Change:

```markdown
### 6.3 Close behaviour

The modal closes on:

- ✕ button click
- `Escape` key
- click outside the modal area (modal is `Qt.Popup` style, or a
  `QDialog` with `setModal(True)` + outside-click hook)
```

to:

```markdown
### 6.3 Close behaviour

The modal closes on:

- title-bar ✕
- `Escape` key (QDialog's own default behaviour)
- click outside the modal's rect — implemented as a QApplication-wide
  event filter installed for the dialog's lifetime, checking whether a
  `MouseButtonPress` falls outside `self.rect()`
```

- [ ] **Step 6: Update §6.4 implementation list**

Change:

```markdown
### 6.4 Implementation

`MetricInfoDialog` is a small `QDialog` subclass that:

1. Receives a `Metric` instance.
2. Reads `metric.documentation` (the `MetricDocumentation` model from §5.2).
3. Renders the panels above with `QLabel` (Markdown-styled text).
4. Provides a "Copy citation" button that copies the citation string to
   the clipboard.
5. Has `keyPressEvent` for Escape and `mousePressEvent` on the
   semi-transparent overlay for outside-click closure.
```

to:

```markdown
### 6.4 Implementation

`MetricInfoDialog` is a small `QDialog` subclass that:

1. Receives a `Metric` class.
2. Reads `metric.documentation` (the `MetricDocumentation` model from §5.2).
3. Renders the panels above as plain text in a read-only `QTextEdit`
   (no Markdown/LaTeX rendering — `formula_latex`, when present, is
   shown as its raw source string).
4. Provides a "Copy citation" button that copies the citation string
   (plus DOI, when present) to the clipboard.
5. Relies on `QDialog`'s own default Escape handling, plus a
   QApplication-wide event filter installed while shown/removed when
   hidden, for outside-click closure.
```

- [ ] **Step 7: Update §6.5 visibility rule**

Change:

```markdown
### 6.5 Visibility rule

Show the ⓘ icon **only when** `metric.documentation.citation is not
None` *or* `metric.documentation.formula_plain is not None`. Metrics
without a published formula or canonical reference (e.g. ad-hoc
diagnostic outputs) get a tooltip instead, not the modal.
```

to:

```markdown
### 6.5 Visibility rule

Show the ⓘ icon **only when** `metric.documentation.citation is not
None` *or* `metric.documentation.formula_plain is not None`. Metrics
without a published formula or canonical reference (e.g. ad-hoc
diagnostic outputs) get a tooltip instead, not the modal.

Note: `MetricDocumentation.formula_plain` (§5.2) is currently a
required, non-`None` `str` field on every built-in metric, so this
rule never actually hides the ⓘ icon today. It's implemented as
specified for forward compatibility, in case a future metric type
legitimately has no formula.
```

- [ ] **Step 8: Commit**

```bash
git add docs/UI_DESIGN.md docs/METRICS_SPEC.md
git commit -m "docs: reconcile UI_DESIGN.md/METRICS_SPEC.md with the shipped metrics-screen redesign"
```

---

## Task 8: Repo-wide check + full targeted test run

**Files:** none modified unless the check in Step 1 finds something.

- [ ] **Step 1: Confirm no other caller of the old `MetricInfoDialog(metric_id: str)` signature exists**

Run: `grep -rn "MetricInfoDialog(" --include=*.py .`
Expected: only `ui/metrics_screen.py` (the `functools.partial(self._show_metric_info, metric_cls)` call site and the `_show_metric_info` method body) and the test files touched in Tasks 3 and 5 appear. If any other caller shows up, update it to pass a `Metric` class instead of a string before continuing.

- [ ] **Step 2: Run every test file touched by this plan together**

Run: `pytest tests/test_core/test_models.py tests/test_ui/test_project_store.py tests/test_ui/test_metric_info_dialog.py tests/test_ui/test_metrics_screen.py -v`
Expected: PASS (all tests from Tasks 1–6, no failures, no test order dependencies)

- [ ] **Step 3: Run the full test suite to check for unrelated regressions**

Run: `pytest -q`
Expected: PASS (or only pre-existing unrelated failures, if any — compare against a baseline run on `main` if something fails here that isn't obviously related to this change)

- [ ] **Step 4: Commit (only if Step 1 required a code change)**

```bash
git add -A
git commit -m "fix: update remaining MetricInfoDialog caller for the new Metric-class constructor"
```

If Step 1 found no other callers, skip this commit — there's nothing to commit.

---

## Left to do after this plan (explicitly out of scope — see the design spec §4 and §8)

- Screen 6.3 (Per-Metric Advanced Configuration) and any real `Metric` config schema behind the ⚙ stub.
- `SessionRef.sha256` is still never computed at `add_session` time (pre-existing, unrelated gap).
- Zone overlap policy (`METRICS_SPEC.md` §8, open question 2).
- Per-metric config value storage (`METRICS_SPEC.md` §8, open question 3).

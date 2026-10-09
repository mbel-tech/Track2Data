"""Fusion section of the Views page: set up and check the fusion of the selected pair.

Shown only for a 3-D project. A background task fuses the selected pair (when it has
fusion settings) and its report drives the status line; the "Set up fusion…" button first
loads both preprocessed sessions on the store's worker pool, then opens the dialog, whose
accepted result is written through the store. A rebuild never writes, and it re-runs the
status task only when the pair, its settings or the session facts changed.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from track2data.core.models import ViewPair
from track2data.fusion.align import FusionError
from ui.dialogs.fusion_dialog import FusionDialog
from ui.widgets.weak_slot import weak_slot

NO_PAIR_TEXT = "Select a pair."
NEEDS_SETUP_TEXT = "Fusion setup needed."
CHECKING_TEXT = "Checking the fusion…"
LOADING_TEXT = "Loading the sessions…"


def fuse_status(manifest, pair: ViewPair, cache_dir: Path | None):
    """Fuse one pair. Runs on a worker thread; raises FusionError with a message."""
    from track2data.api import Engine

    try:
        return Engine(manifest, cache_dir=cache_dir).fuse_pair(pair)
    except FusionError:
        raise
    except Exception as exc:  # the task runner keeps only the message, so name the type here
        name = type(exc).__name__
        raise FusionError(f"{name}: {exc}" if str(exc) else name) from exc


def load_pair_sessions(manifest, pair: ViewPair, cache_dir: Path | None):
    """Preprocess both sessions of a pair -> (top, side). Runs on a worker; raises on failure."""
    from track2data.api import Engine

    engine = Engine(manifest, cache_dir=cache_dir)
    refs = {r.session_id: r for r in manifest.sessions}
    return tuple(
        engine.preprocess_ref(refs[sid]) for sid in (pair.top_session_id, pair.side_session_id)
    )


def ready_text(report) -> str:
    text = (
        f"Ready: {report.overlap_frames} shared frames, {len(report.fused_labels)} fish fused, "
        f"{report.n_outside_column} positions outside the water column"
    )
    if report.agreement_rms_cm is not None:
        text += f", agreement {report.agreement_rms_cm:.2f} cm"
    elif report.agreement_skipped:
        text += f", agreement not checked ({report.agreement_skipped})"
    if report.agreement_warning:
        text += "; agreement warning: the views disagree by more than 10% of the top-view range"
    return text


class FusionSection(QGroupBox):
    def __init__(self, store=None, parent: QWidget | None = None) -> None:
        super().__init__("Fusion", parent)
        self._store = store
        self._ids: tuple[str, str] | None = None
        self._key: object = None  # what the last status task / result was computed for
        self._result_text: str | None = None  # status for self._key once known
        self._note = ""  # a transient message (loading, error) that overrides the status
        self._status_pending: dict[str, object] = {}  # task id -> key
        self._load_pending: dict[str, tuple[str, str]] = {}  # task id -> pair ids
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lead = QLabel("Combine the top and side view of the pair into one 3-D session.")
        lead.setObjectName("PageLead")
        lead.setWordWrap(True)
        lay.addWidget(lead)
        self._status = QLabel(NO_PAIR_TEXT)
        self._status.setWordWrap(True)
        lay.addWidget(self._status)
        row = QHBoxLayout()
        self._btn = QPushButton("Set up fusion…")
        row.addWidget(self._btn)
        row.addStretch(1)
        lay.addLayout(row)

        self._btn.clicked.connect(weak_slot(self._start))
        if store is not None:
            store.taskFinished.connect(self._on_task_finished)
            store.projectChanged.connect(self._on_project_changed)
        self.rebuild()

    # ── store helpers ──────────────────────────────────────────────────────

    def _manifest(self):
        return None if self._store is None else self._store.manifest

    def _applies(self) -> bool:
        m = self._manifest()
        return m is not None and m.mode.dimension == "3d"

    def _find_pair(self, ids: tuple[str, str] | None) -> ViewPair | None:
        m = self._manifest()
        if ids is None or m is None:
            return None
        return next((p for p in m.view_pairs if (p.top_session_id, p.side_session_id) == ids), None)

    def _ref(self, session_id: str):
        m = self._manifest()
        return next((r for r in m.sessions if r.session_id == session_id), None) if m else None

    def _key_of(self, pair: ViewPair) -> object:
        """Everything the status depends on: the pair with its settings, both session
        entries and their derived facts, and the layout."""
        m = self._manifest()
        ids = (pair.top_session_id, pair.side_session_id)
        refs = tuple(
            r.model_dump_json() if (r := self._ref(sid)) is not None else None for sid in ids
        )
        facts = tuple(self._store.session_facts(sid) for sid in ids)
        # Engine.fuse_pair also depends on these project settings (see Engine._cache_key).
        settings = (
            m.preprocess.model_dump_json(),
            m.calibration.model_dump_json(),
            m.zones.model_dump_json(),
            m.security.allow_pickle_trajectories,
            m.blob_diagnostics,
            tuple(str(m.video_overrides.get(sid)) for sid in ids),
            tuple(
                m.video_overrides[sid].exists() if sid in m.video_overrides else None for sid in ids
            ),
        )
        return (pair.model_dump_json(), refs, facts, m.mode.layout, settings)

    # ── selection and rebuild (never writes) ───────────────────────────────

    def set_pair(self, ids: object) -> None:
        new = tuple(ids) if ids else None
        if new != self._ids:
            self._ids = new  # type: ignore[assignment]
            self._note = ""
            self._load_pending = {}
        self.rebuild()

    def rebuild(self) -> None:
        applies = self._applies()
        self.setVisible(applies)
        pair = self._find_pair(self._ids) if applies else None
        self._btn.setEnabled(pair is not None)
        if pair is None or pair.fusion is None:
            self._key = None
            self._result_text = None
            self._status_pending = {}
        else:
            key = self._key_of(pair)
            if key != self._key:
                self._key = key
                self._result_text = None
                self._start_status(pair, key)
        self._render(pair)

    def _render(self, pair: ViewPair | None) -> None:
        if self._note:
            text = self._note
        elif pair is None:
            text = NO_PAIR_TEXT
        elif pair.fusion is None:
            text = NEEDS_SETUP_TEXT
        else:
            text = self._result_text or CHECKING_TEXT
        self._status.setText(text)

    def _start_status(self, pair: ViewPair, key: object) -> None:
        self._status_pending = {}  # a newer request supersedes an in-flight one
        store = self._store
        manifest, cache_dir = store.manifest, store.cache_dir
        pair_copy = pair.model_copy(deep=True)
        self._status_pending[
            store.tasks.submit(lambda: fuse_status(manifest, pair_copy, cache_dir))
        ] = key

    # ── dialog ─────────────────────────────────────────────────────────────

    def _start(self) -> None:
        pair = self._find_pair(self._ids)
        if pair is None or self._store is None:
            return
        self._note = LOADING_TEXT
        self._load_pending = {}  # a newer click supersedes an in-flight load
        store = self._store
        manifest, cache_dir = store.manifest, store.cache_dir
        pair_copy = pair.model_copy(deep=True)
        self._load_pending[
            store.tasks.submit(lambda: load_pair_sessions(manifest, pair_copy, cache_dir))
        ] = (pair.top_session_id, pair.side_session_id)
        self._render(pair)

    def _on_project_changed(self) -> None:
        self._status_pending = {}
        self._load_pending = {}
        self._key = None
        self._result_text = None
        self._note = ""
        self._ids = None
        self.rebuild()

    def _on_task_finished(self, task_id: str, result: object) -> None:
        try:
            if task_id in self._status_pending:
                self._on_status_finished(self._status_pending.pop(task_id), result)
            elif task_id in self._load_pending:
                self._on_load_finished(self._load_pending.pop(task_id), result)
        except Exception as exc:  # never raise out of a slot
            self._note = str(exc) or type(exc).__name__
            self._render(self._find_pair(self._ids))

    def _on_status_finished(self, key: object, result: object) -> None:
        if key != self._key:
            return  # the pair, its settings or its sessions changed meanwhile
        if isinstance(result, BaseException):
            self._result_text = str(result) or type(result).__name__
        else:
            self._result_text = ready_text(result.report)  # type: ignore[attr-defined]
        self._note = ""
        self._render(self._find_pair(self._ids))

    def _on_load_finished(self, ids: tuple[str, str], result: object) -> None:
        if ids != self._ids:
            return  # another pair was selected while loading
        if isinstance(result, BaseException):
            self._note = f"Could not load the sessions: {result}"
            self._render(self._find_pair(ids))
            return
        self._note = ""
        pair = self._find_pair(ids)
        if pair is None or any(self._ref(sid) is None for sid in ids):
            self._note = f"{' / '.join(ids)} is no longer in the project."
            self._render(pair)
            return
        self._run_dialog(pair, result)

    def _run_dialog(self, pair: ViewPair, sessions: object) -> None:
        top, side = sessions  # type: ignore[misc]
        ids = (pair.top_session_id, pair.side_session_id)
        bg = getattr(side.session, "background_image_path", None)
        bg = Path(bg) if bg is not None and Path(bg).is_file() else None
        same_video = self._manifest().mode.layout == "single_video_two_panels"
        side_ref = self._ref(pair.side_session_id)
        crop = side_ref.panel if side_ref is not None else None
        dialog = FusionDialog(top, side, pair, same_video, bg, self, background_crop=crop)
        if not dialog.exec():
            self._render(self._find_pair(self._ids))
            return
        if self._find_pair(ids) is None or any(self._ref(sid) is None for sid in ids):
            self._note = f"{' / '.join(ids)} is no longer in the project."
            self._render(self._find_pair(self._ids))
            return
        try:
            self._store.update_fusion(ids[0], ids[1], dialog.result_settings())
        except Exception as exc:  # the store rejected the change, or the dialog failed
            self._note = str(exc) or type(exc).__name__
        self.rebuild()

"""Banner shown on 2-D-only screens while the project is in 3-D mode."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel

BANNER_TEXT = "3-D mode: this screen applies to the 2-D tracks only until fusion is available"


class ModeBanner(QLabel):
    """Hidden for no project or a 2-D project; follows the store otherwise."""

    def __init__(self, store, parent=None) -> None:
        super().__init__(BANNER_TEXT, parent)
        self._store = store
        self.setObjectName("ModeBanner")
        self.setProperty("role", "warn")
        self.setWordWrap(True)
        store.projectChanged.connect(self._refresh)
        store.modeChanged.connect(self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        manifest = self._store.manifest
        self.setHidden(manifest is None or manifest.mode.dimension != "3d")

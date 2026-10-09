"""Views page (3-D projects only): assign view roles and pair the two views."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class ViewsScreen(QWidget):
    """Skeleton of the Views page; the pairing controls arrive in later tasks."""

    def __init__(self, store=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 26, 26, 26)
        root.setSpacing(14)

        title = QLabel("Views")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        lead = QLabel("Say which session is the top view and which is the side view.")
        lead.setObjectName("PageLead")
        lead.setWordWrap(True)
        lead.setMaximumWidth(600)
        root.addWidget(lead)
        root.addStretch(1)

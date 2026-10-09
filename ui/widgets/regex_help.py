"""Small help bubble explaining the session-name patterns on the Views page."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

REGEX_HELP_TEXT = (
    "A pattern describes the part of a session name that tells the views apart.\n"
    "Mark the part that identifies the fish or trial as (?P<key>...). "
    "Sessions with the same key are paired.\n"
    "Example 1: (?P<key>.+)_top$ matches trial01_top with key trial01, "
    "and (?P<key>.+)_side$ matches trial01_side with the same key, so the two are paired.\n"
    "Example 2: ^dorsal_(?P<key>\\d+)$ and ^lateral_(?P<key>\\d+)$ pair dorsal_01 "
    "with lateral_01 (key 01).\n"
    "Example 3: ^top_(?P<key>.+)$ and ^side_(?P<key>.+)$ pair top_fish3_day2 "
    "with side_fish3_day2 (key fish3_day2)."
)


class RegexHelpPopover(QFrame):
    """A frameless popup showing ``REGEX_HELP_TEXT``; closes when clicked outside."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("RegexHelpPopover")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        label = QLabel(REGEX_HELP_TEXT)
        label.setWordWrap(True)
        label.setMaximumWidth(380)
        layout.addWidget(label)

"""Command palette (Ctrl+K): type to filter, Up/Down to move, Enter to run, Esc to close.

``filter_commands`` is pure; ``CommandPalette`` is the dialog around it. The
caller supplies the commands, so the palette runs exactly what the menus run.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.weak_slot import weak_slot


@dataclass(frozen=True)
class Command:
    kind: str  # "Go to", "Run", "View", "File", "Help"
    label: str
    run: Callable[[], None]
    shortcut: str = ""
    enabled: bool = True


def filter_commands(commands: list[Command], query: str) -> list[Command]:
    """Enabled commands whose kind or label contains every word of *query*, best first.

    A label that starts with the query ranks above one that only contains it.
    """
    words = query.lower().split()
    scored: list[tuple[int, int, Command]] = []
    for index, command in enumerate(commands):
        if not command.enabled:
            continue
        haystack = f"{command.kind} {command.label}".lower()
        if not all(word in haystack for word in words):
            continue
        starts = command.label.lower().startswith(query.lower().strip()) if words else False
        scored.append((0 if starts else 1, index, command))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [command for _, _, command in scored]


class CommandPalette(QDialog):
    WIDTH = 560

    def __init__(self, commands: list[Command], parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("CommandPalette")
        self.setModal(True)
        self.setFixedWidth(self.WIDTH)
        self._commands = commands
        self._shown: list[Command] = []

        col = QVBoxLayout(self)
        col.setContentsMargins(16, 16, 16, 12)
        col.setSpacing(10)
        self._search = QLineEdit()
        self._search.setObjectName("PaletteSearch")
        self._search.setPlaceholderText("Type a command…")
        self._search.textChanged.connect(self._refresh)
        self._search.installEventFilter(self)
        col.addWidget(self._search)
        self._list = QListWidget()
        self._list.setObjectName("PaletteList")
        self._list.setFixedHeight(320)
        self._list.itemActivated.connect(weak_slot(self._run_current))
        self._list.itemClicked.connect(weak_slot(self._run_current))
        col.addWidget(self._list)
        self._refresh()

    # ── public for tests ───────────────────────────────────────────────────

    def shown_labels(self) -> list[str]:
        return [c.label for c in self._shown]

    def set_query(self, text: str) -> None:
        self._search.setText(text)

    def step(self, delta: int) -> None:
        if not self._shown:
            return
        row = (self._list.currentRow() + delta) % len(self._shown)
        self._list.setCurrentRow(row)

    def run_current(self) -> None:
        self._run_current()

    # ── internals ──────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        self._shown = filter_commands(self._commands, self._search.text())
        self._list.clear()
        for command in self._shown:
            shortcut = f"    {command.shortcut}" if command.shortcut else ""
            item = QListWidgetItem(f"{command.kind:<8}  {command.label}{shortcut}")
            self._list.addItem(item)
        if self._shown:
            self._list.setCurrentRow(0)

    def _run_current(self) -> None:
        row = self._list.currentRow()
        if not 0 <= row < len(self._shown):
            return
        command = self._shown[row]
        self.accept()
        command.run()

    def eventFilter(self, obj, event) -> bool:
        if obj is self._search and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Down:
                self.step(1)
                return True
            if key == Qt.Key.Key_Up:
                self.step(-1)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._run_current()
                return True
        return super().eventFilter(obj, event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        parent = self.parentWidget()
        if parent is not None:
            top_left = parent.mapToGlobal(parent.rect().topLeft())
            self._place(top_left.x() + (parent.width() - self.width()) // 2, top_left.y() + 96)
        self._search.setFocus()

    def _place(self, x: int, y: int) -> None:
        self.move(x, y)

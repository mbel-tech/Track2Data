"""The receipt shown after an export: what was written, how big, and its checksum."""

from __future__ import annotations

import contextlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from track2data.core.hashing import file_sha256

#: Hex characters of the SHA-256 shown in the table; the CLI/README carry the full hash.
SHORT_HASH_LEN = 8


@dataclass(frozen=True)
class ReceiptRow:
    name: str
    size: str
    short_hash: str


def receipt_rows(written: Iterable[Path], out_dir: Path | None) -> list[ReceiptRow]:
    """One row per written file: path relative to *out_dir*, byte size, short SHA-256."""
    rows = []
    for path in written:
        name = str(path)
        if out_dir is not None:
            with contextlib.suppress(ValueError):
                name = path.relative_to(out_dir).as_posix()
        size = "—"
        with contextlib.suppress(OSError):
            size = f"{path.stat().st_size:,}".replace(",", chr(0x202F))
        digest = "—"
        with contextlib.suppress(OSError):
            full = file_sha256(path)
            digest = f"{full[: SHORT_HASH_LEN // 2]}…{full[-SHORT_HASH_LEN // 2:]}"
        rows.append(ReceiptRow(name, size, digest))
    return rows


class ExportReceiptDialog(QDialog):
    """Mustard tick, title, where it went, the file list, and Copy CLI / Done."""

    def __init__(
        self,
        out_dir: Path,
        n_sessions: int,
        rows: list[ReceiptRow],
        cli_command: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ExportReceipt")
        self.setWindowTitle("Dataset exported")
        self.setMinimumWidth(620)
        self._cli = cli_command

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        body = QWidget()
        col = QVBoxLayout(body)
        col.setContentsMargins(24, 22, 24, 18)
        col.setSpacing(14)
        outer.addWidget(body, 1)

        head = QHBoxLayout()
        head.setSpacing(14)
        tick = QLabel("✓")
        tick.setObjectName("ReceiptTick")
        tick.setFixedSize(40, 40)
        tick.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.addWidget(tick)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel("Dataset exported")
        title.setObjectName("DialogTitle")
        noun = "session" if n_sessions == 1 else "sessions"
        where = QLabel(f"{out_dir.as_posix()} · {n_sessions} {noun}")
        where.setProperty("role", "mono")
        where.setWordWrap(True)
        titles.addWidget(title)
        titles.addWidget(where)
        head.addLayout(titles, 1)
        col.addLayout(head)

        self._table = QTableWidget(len(rows), 3)
        self._table.setHorizontalHeaderLabels(["File", "Size (bytes)", "SHA-256"])
        self._table.verticalHeader().hide()
        self._table.setShowGrid(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setMinimumHeight(180)
        for r, row in enumerate(rows):
            self._table.setItem(r, 0, QTableWidgetItem(row.name))
            self._table.setItem(r, 1, QTableWidgetItem(row.size))
            self._table.setItem(r, 2, QTableWidgetItem(row.short_hash))
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        col.addWidget(self._table)

        footer = QFrame()
        footer.setObjectName("DialogFooter")
        foot = QHBoxLayout(footer)
        foot.setContentsMargins(24, 12, 24, 12)
        copy = QPushButton("Copy CLI command")
        copy.setProperty("role", "outline")
        copy.clicked.connect(self.copy_cli)
        done = QPushButton("Done")
        done.setProperty("role", "primary")
        done.setDefault(True)
        done.clicked.connect(self.accept)
        foot.addWidget(copy)
        foot.addStretch()
        foot.addWidget(done)
        outer.addWidget(footer)

    def copy_cli(self) -> None:
        QApplication.clipboard().setText(self._cli)

    def row_names(self) -> list[str]:
        return [self._table.item(r, 0).text() for r in range(self._table.rowCount())]

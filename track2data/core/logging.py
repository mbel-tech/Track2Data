"""Structured logger and run-log Markdown writer."""

from __future__ import annotations

import logging


def get_logger(name: str) -> logging.Logger:
    """Return a standard library logger; structlog integration is a v1.1 feature."""
    return logging.getLogger(name)


class RunLogWriter:
    """Accumulates Markdown lines for the run log (emitted to UI via signal)."""

    def __init__(self) -> None:
        self._lines: list[str] = []

    def log(self, markdown: str) -> None:
        self._lines.append(markdown)

    def header(self, title: str) -> None:
        self._lines.append(f"## {title}")

    def bullet(self, text: str) -> None:
        self._lines.append(f"- {text}")

    def render(self) -> str:
        return "\n".join(self._lines)

    def clear(self) -> None:
        self._lines.clear()

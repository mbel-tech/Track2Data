"""Exception hierarchy for track2data.

Every exception carries machine-readable metadata so the UI can surface
a contextual banner with a one-line remediation hint.
"""

from __future__ import annotations

from typing import Literal


class Track2DataError(Exception):
    """Base exception for all track2data errors."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "UNKNOWN",
        severity: Literal["error", "warning", "info"] = "error",
        subject: str = "",
        remediation: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.severity = severity
        self.subject = subject
        self.remediation = remediation

    def __str__(self) -> str:
        parts = [f"[{self.code}] {super().__str__()}"]
        if self.subject:
            parts.append(f"  subject: {self.subject}")
        if self.remediation:
            parts.append(f"  fix: {self.remediation}")
        return "\n".join(parts)


class ConfigError(Track2DataError):
    """Bad user-supplied parameters."""


class DataValidationError(Track2DataError):
    """Input data fails a validation rule (DV-1..DV-8)."""


class ImportError_(DataValidationError):
    """Session folder cannot be read (missing files, bad format)."""


class MetadataValidationError(DataValidationError):
    """Metadata file is missing required columns or has join conflicts."""


class CalibrationError(DataValidationError):
    """Calibration parameters are invalid or cannot be derived."""


class ZoneValidationError(DataValidationError):
    """Zone polygon definition is invalid (too few vertices, self-intersecting, etc.)."""


class ProcessingError(Track2DataError):
    """Runtime error inside preprocessing or metric computation."""


class ExportError(Track2DataError):
    """Error writing output files."""

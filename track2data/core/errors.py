"""Exception hierarchy for track2data.

Every exception carries machine-readable metadata so the UI can surface
a contextual banner with a one-line remediation hint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from track2data.core.models import PreprocessReport


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


class PreprocessStageError(ProcessingError):
    """A stage that runs *after* the preprocessing pipeline -- calibration
    or zone assignment -- failed, once the pipeline's own step report had
    already been computed.

    The failure is still raised, never swallowed: continuing past a failed
    calibration would emit pixel-unit numbers as if they were real-world
    units, and continuing past a failed zone assignment would compute zone
    metrics against no zones. Both are wrong results wearing a success
    costume, which is exactly what issue #7's fail-loud rule exists to
    prevent.

    What this exception adds is ``report``: the already-computed
    ``PreprocessReport``, carried alongside the failure so callers can
    still show the step log. That log is usually what explains why the
    later stage blew up, and it would otherwise be lost purely because of
    where the exception happened to be raised.
    """

    def __init__(
        self,
        message: str,
        *,
        report: PreprocessReport,
        code: str = "PREPROCESS_STAGE_FAILED",
        severity: Literal["error", "warning", "info"] = "error",
        subject: str = "",
        remediation: str = "",
    ) -> None:
        super().__init__(
            message,
            code=code,
            severity=severity,
            subject=subject,
            remediation=remediation,
        )
        self.report = report


class ExportError(Track2DataError):
    """Error writing output files."""

"""The user's side of adding sessions: what a scan found, what they chose, what will be added.

A scan reports ranked detections. Before anything is added to a project the user confirms the
software, can amend the choice, fills in the options the files do not record (frame rate, frame
size, which keypoint), and can leave sessions out or rename them. ``ConfirmDraft`` holds those
choices and every rule about them, with no Qt in it: the confirm dialog and ``track2data add``
are two thin views over it, so "can the user press OK?" has one answer whichever asks.

It never reads a session. The options are validated against the reader's declared parameters
(``readers/params.py``), so what it accepts is what ``read(..., options=...)`` accepts.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from track2data.core.errors import ImportError_
from track2data.core.models import SessionRef
from track2data.readers.detection import Confidence, Detection
from track2data.readers.params import ReaderParameter, ValueSource, resolve_options
from track2data.readers.scan import FormatGroup, ScanResult

ProblemCode = Literal[
    "NOTHING_SELECTED", "OPTION_MISSING", "OPTION_INVALID", "ID_DUPLICATE", "ID_UNSAFE"
]


@dataclass(frozen=True)
class Problem:
    """Why the draft cannot be confirmed yet, in words that say what to do."""

    code: ProblemCode
    message: str
    session_id: str | None = None
    option: str | None = None


@dataclass(frozen=True)
class Alternative:
    """Another reader that recognised the same sessions."""

    reader: str
    display_name: str
    confidence: Confidence


@dataclass(frozen=True)
class SessionRow:
    """One session as the user sees it in the confirm list."""

    #: The id the scan gave it; the stable handle for every change below.
    original_id: str
    #: What it will be called in the project (the user may have renamed it).
    session_id: str
    source: Path
    included: bool
    #: Already in the project under the same reader, so adding it again is a duplicate.
    already_added: bool
    warnings: tuple[str, ...] = ()


def _resolved(path: Path) -> Path:
    try:
        return Path(path).resolve()
    except OSError:
        return Path(path)


class ConfirmDraft:
    """The choices made about one scan, from the first suggestion to the sessions to add.

    Starts on the best reader of the first group, every session included, the options
    pre-filled with whatever the scan could read out of the files. Everything the user changes
    is recorded here; :meth:`problems` says whether the result can be added, and
    :meth:`to_session_refs` produces the entries.
    """

    def __init__(self, result: ScanResult, *, existing: Sequence[SessionRef] = ()) -> None:
        self._result = result
        # (resolved folder, reader or None) of what the project already holds. A legacy entry
        # (no saved reader) is the same session whichever reader reads it.
        self._existing = [(_resolved(ref.folder), ref.reader) for ref in existing]
        self._existing_ids = {ref.session_id for ref in existing}
        self._group_index = 0
        self._detection: Detection | None = None
        self._chosen_by: Literal["detected", "user"] = "detected"
        self._values: dict[str, Any] = {}
        self._sources: dict[str, ValueSource] = {}
        self._per_session: dict[str, dict[str, Any]] = {}
        self._ids: dict[str, str] = {}
        self._included: dict[str, bool] = {}
        if result.groups:
            self._enter(result.groups[0].best, "detected")

    # ── what the scan found ─────────────────────────────────────────────────

    @property
    def result(self) -> ScanResult:
        return self._result

    @property
    def groups(self) -> tuple[FormatGroup, ...]:
        return self._result.groups

    @property
    def group_index(self) -> int:
        return self._group_index

    @property
    def is_empty(self) -> bool:
        """True when the scan recognised nothing, so there is nothing to confirm."""
        return self._detection is None

    @property
    def alternatives(self) -> tuple[Alternative, ...]:
        """The readers that recognised the selected group, best first."""
        if self.is_empty:
            return ()
        return tuple(
            Alternative(d.reader, d.display_name, d.confidence)
            for d in self._result.groups[self._group_index].detections
        )

    # ── the selected reader ─────────────────────────────────────────────────

    @property
    def reader(self) -> str:
        return self._detection.reader if self._detection else ""

    @property
    def display_name(self) -> str:
        return self._detection.display_name if self._detection else ""

    @property
    def confidence(self) -> Confidence:
        return self._detection.confidence if self._detection else Confidence.LOW

    @property
    def evidence(self) -> tuple[str, ...]:
        return self._detection.evidence if self._detection else ()

    @property
    def verification(self) -> str:
        return self._detection.verification if self._detection else "synthetic_only"

    @property
    def parameters(self) -> tuple[ReaderParameter, ...]:
        return self._detection.parameters if self._detection else ()

    @property
    def chosen_by(self) -> Literal["detected", "user"]:
        """"detected" while the suggestion stands, "user" once the user picked another reader."""
        return self._chosen_by

    def select_group(self, index: int) -> None:
        """Move to another group of sessions (a root that holds more than one format)."""
        if not 0 <= index < len(self._result.groups):
            raise ValueError(f"There is no group {index}; the scan found {len(self.groups)}.")
        self._group_index = index
        self._enter(self._result.groups[index].best, "detected")

    def select_reader(self, name: str) -> None:
        """Amend the suggestion: read the selected group with another reader that recognised it."""
        if self.is_empty:
            raise ValueError("The scan recognised nothing, so there is no reader to choose.")
        group = self._result.groups[self._group_index]
        for detection in group.detections:
            if detection.reader == name:
                self._enter(detection, "detected" if detection is group.best else "user")
                return
        offered = ", ".join(d.reader for d in group.detections)
        raise ValueError(f"No reader {name!r} recognised these sessions; offered: {offered}.")

    # ── options ─────────────────────────────────────────────────────────────

    @property
    def options(self) -> dict[str, Any]:
        """The shared options set so far: proposals from the files and what the user typed."""
        return dict(self._values)

    def option_source(self, name: str) -> ValueSource:
        """Where an option's value came from, or why it has none."""
        if name in self._sources:
            return self._sources[name]
        spec = next((p for p in self.parameters if p.name == name), None)
        return "required" if spec is not None and spec.required else "tool-default"

    def set_option(self, name: str, value: Any) -> None:
        """Set an option every session shares; ``None`` clears it."""
        self._shared_parameter(name)
        if value is None:
            self._values.pop(name, None)
            self._sources.pop(name, None)
        else:
            self._values[name] = value
            self._sources[name] = "user"

    def set_session_option(self, session_id: str, name: str, value: Any) -> None:
        """Set an option that differs per session (which arena); ``None`` clears it."""
        self._row_key(session_id)
        spec = next((p for p in self.parameters if p.name == name), None)
        if spec is None or spec.scope != "session":
            raise ValueError(f"Option {name!r} is not a per-session option of {self.reader!r}.")
        chosen = self._per_session.setdefault(session_id, {})
        if value is None:
            chosen.pop(name, None)
        else:
            chosen[name] = value

    def session_options(self, session_id: str) -> dict[str, Any]:
        self._row_key(session_id)
        return dict(self._per_session.get(session_id, {}))

    # ── sessions ────────────────────────────────────────────────────────────

    @property
    def rows(self) -> tuple[SessionRow, ...]:
        if self._detection is None:
            return ()
        return tuple(
            SessionRow(
                original_id=candidate.session_id,
                session_id=self._ids[candidate.session_id],
                source=candidate.source,
                included=self._included[candidate.session_id],
                already_added=self._already_added(candidate.source),
                warnings=candidate.warnings,
            )
            for candidate in self._detection.sessions
        )

    def set_included(self, session_id: str, included: bool) -> None:
        self._row_key(session_id)
        self._included[session_id] = included

    def rename(self, session_id: str, new_id: str) -> None:
        self._row_key(session_id)
        self._ids[session_id] = new_id

    # ── can it be added? ────────────────────────────────────────────────────

    def problems(self) -> list[Problem]:
        """Everything standing between the user and "Add": empty when it can be confirmed."""
        chosen = [row for row in self.rows if row.included]
        if not chosen:
            return [
                Problem(
                    "NOTHING_SELECTED",
                    "Nothing is selected to add. Tick at least one session.",
                )
            ]
        problems = self._id_problems(chosen)
        for spec in self.parameters:
            if spec.scope == "group":
                problems += self._option_problems(spec, self._values, None)
            else:
                for row in chosen:
                    values = self._per_session.get(row.original_id, {})
                    problems += self._option_problems(spec, values, row.session_id)
        return problems

    def to_session_refs(self) -> list[SessionRef]:
        """The project entries for the chosen sessions, each saving the reader and its options.

        Only the options that were given are saved, not the defaults: a default the reader
        changes later should not be frozen into a project that never chose it.
        """
        problems = self.problems()
        if problems:
            raise ValueError("; ".join(p.message for p in problems))
        assert self._detection is not None
        sources = {c.session_id: c.source for c in self._detection.sessions}
        return [
            SessionRef(
                session_id=row.session_id,
                folder=sources[row.original_id],
                sha256="",
                reader=self.reader,
                reader_options={**self._values, **self._per_session.get(row.original_id, {})},
                reader_chosen_by=self._chosen_by,
                reader_confidence=self.confidence.name,
            )
            for row in self.rows
            if row.included
        ]

    # ── internals ───────────────────────────────────────────────────────────

    def _enter(self, detection: Detection, chosen_by: Literal["detected", "user"]) -> None:
        """Start over on *detection*: its sessions, its proposals, nothing the user changed."""
        self._detection = detection
        self._chosen_by = chosen_by
        shared = {p.name for p in detection.parameters if p.scope == "group"}
        self._values = {}
        self._sources = {}
        for name, proposal in detection.proposed.items():
            if name in shared and proposal.value is not None:
                self._values[name] = proposal.value
                self._sources[name] = proposal.source
        self._per_session = {}
        self._ids = {c.session_id: c.session_id for c in detection.sessions}
        self._included = {
            c.session_id: not self._already_added(c.source) for c in detection.sessions
        }

    def _already_added(self, source: Path) -> bool:
        resolved = _resolved(source)
        return any(
            path == resolved and (reader is None or reader == self.reader)
            for path, reader in self._existing
        )

    def _row_key(self, session_id: str) -> None:
        if session_id not in self._ids:
            raise KeyError(f"No session {session_id!r} in this scan.")

    def _shared_parameter(self, name: str) -> ReaderParameter:
        spec = next((p for p in self.parameters if p.name == name), None)
        if spec is None or spec.scope != "group":
            raise ValueError(f"Option {name!r} is not a shared option of {self.reader!r}.")
        return spec

    def _option_problems(
        self, spec: ReaderParameter, values: dict[str, Any], session_id: str | None
    ) -> list[Problem]:
        """The problem with one option's value, if any, by the reader's own validation."""
        try:
            resolve_options(self.reader, [spec], {spec.name: values.get(spec.name)})
        except ImportError_ as exc:
            if exc.code == "READER_OPTION_MISSING":
                message = f"{spec.label} ({spec.name}) is required: the files do not record it."
                return [Problem("OPTION_MISSING", message, session_id, spec.name)]
            return [Problem("OPTION_INVALID", str(exc).splitlines()[0], session_id, spec.name)]
        return []

    def _id_problems(self, chosen: Sequence[SessionRow]) -> list[Problem]:
        problems: list[Problem] = []
        seen: dict[str, int] = {}
        for row in chosen:
            try:
                SessionRef(session_id=row.session_id, folder=Path("."), sha256="")
            except ValidationError:
                problems.append(
                    Problem(
                        "ID_UNSAFE",
                        f"{row.session_id!r} cannot be used as a session name. "
                        "Rename it without slashes or an empty name.",
                        row.session_id,
                    )
                )
                continue
            seen[row.session_id] = seen.get(row.session_id, 0) + 1
        for session_id, count in seen.items():
            if count > 1:
                message = f"{count} sessions would be called {session_id!r}. Rename all but one."
            elif session_id in self._existing_ids:
                message = f"The project already has a session called {session_id!r}. Rename it."
            else:
                continue
            problems.append(Problem("ID_DUPLICATE", message, session_id))
        return problems

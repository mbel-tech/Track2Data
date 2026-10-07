"""Reader options: what a reader must be told because its files do not say.

Most tracker outputs record neither the frame rate nor the frame size (DeepLabCut, SLEAP,
Anipose), and several need a choice (which keypoint stands for the animal). A reader declares
these as ``parameters``; the confirm dialog renders them, the manifest stores the answers
(``SessionRef.reader_options``), and ``read(..., options=...)`` receives them.

A required option that is missing is an error and never a default: a made-up frame rate
silently corrupts every speed metric.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from track2data.core.errors import ImportError_

ParameterKind = Literal["int", "float", "str", "bool", "choice", "multichoice", "path"]
ValueSource = Literal["file", "video", "tool-default", "required", "user"]


class ReaderParameter(BaseModel):
    """One option a reader accepts."""

    name: str
    label: str
    kind: ParameterKind
    default: Any = None
    required: bool = False
    choices: tuple[str, ...] = ()
    help: str = ""
    #: "group": one value for every session in a scan group; "session": a per-session column.
    scope: Literal["group", "session"] = "group"
    minimum: float | None = None
    maximum: float | None = None


class ProposedValue(BaseModel):
    """A value a detection proposes for a parameter, and where it came from."""

    value: Any = None
    source: ValueSource = "required"


def _invalid(reader: str, name: str, why: str) -> ImportError_:
    where = f"Reader {reader!r}: option" if reader else "Option"
    return ImportError_(
        f"{where} {name!r} {why}",
        code="READER_OPTION_INVALID",
        subject=name,
        remediation=f"Correct option {name!r} in the confirm dialog or with --option.",
    )


def _check(reader: str, spec: ReaderParameter, value: Any) -> Any:
    """Return *value* if it suits *spec*, otherwise raise READER_OPTION_INVALID."""
    kind, name = spec.kind, spec.name
    if kind in ("int", "float"):
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise _invalid(reader, name, f"must be a number, got {value!r}")
        if not math.isfinite(value):
            raise _invalid(reader, name, "must be finite")
        if kind == "int" and not float(value).is_integer():
            raise _invalid(reader, name, f"must be an integer, got {value!r}")
        if spec.minimum is not None and value < spec.minimum:
            raise _invalid(reader, name, f"must be at least {spec.minimum}")
        if spec.maximum is not None and value > spec.maximum:
            raise _invalid(reader, name, f"must be at most {spec.maximum}")
    elif kind == "bool":
        if not isinstance(value, bool):
            raise _invalid(reader, name, f"must be true or false, got {value!r}")
    elif kind == "str":
        if not isinstance(value, str):
            raise _invalid(reader, name, f"must be text, got {value!r}")
    elif kind == "choice":
        if value not in spec.choices:
            raise _invalid(reader, name, f"must be one of {list(spec.choices)}, got {value!r}")
    elif kind == "multichoice":
        if isinstance(value, str) or not isinstance(value, Sequence | set | frozenset):
            raise _invalid(reader, name, "must be a list of choices")
        extra = [item for item in value if item not in spec.choices]
        if extra:
            raise _invalid(reader, name, f"has unknown choices {extra}")
    elif kind == "path" and not isinstance(value, str | Path):
        raise _invalid(reader, name, f"must be a path, got {value!r}")
    return value


def resolve_options(
    reader: str,
    parameters: Sequence[ReaderParameter],
    options: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Validate *options* against *parameters* and fill the declared defaults.

    Unknown names, wrong types and out-of-range values raise READER_OPTION_INVALID. A required
    option that is absent (or None) raises READER_OPTION_MISSING with its name as the subject.
    """
    given = dict(options or {})
    unknown = sorted(set(given) - {p.name for p in parameters})
    if unknown:
        raise _invalid(reader, ", ".join(unknown), "is not an option of this reader")
    resolved: dict[str, Any] = {}
    for spec in parameters:
        value = given.get(spec.name)
        if value is None:
            if spec.required:
                raise ImportError_(
                    f"Reader {reader!r} needs option {spec.name!r} ({spec.label}); "
                    "the files do not record it",
                    code="READER_OPTION_MISSING",
                    subject=spec.name,
                    remediation=f"Supply {spec.name!r} in the confirm dialog or with --option.",
                )
            resolved[spec.name] = spec.default
        else:
            resolved[spec.name] = _check(reader, spec, value)
    return resolved


_TRUE = frozenset({"true", "yes", "1", "on"})
_FALSE = frozenset({"false", "no", "0", "off"})


def parse_value(spec: ReaderParameter, text: str, *, reader: str = "") -> Any:
    """Turn the text of a command-line option into the value *spec* declares.

    Only the *form* is checked here (a number is a number, a choice is one of the choices);
    ranges and requiredness stay with :func:`resolve_options`, which every read goes through
    anyway. A text that is not of the declared kind raises READER_OPTION_INVALID.
    """
    name, kind = spec.name, spec.kind
    if kind == "str":
        return text
    if kind == "path":
        return Path(text)
    raw = text.strip()
    if not raw:
        raise _invalid(reader, name, "needs a value")
    if kind in ("int", "float"):
        try:
            value = int(raw) if kind == "int" else float(raw)
            if not math.isfinite(value):
                raise ValueError(raw)
        except ValueError:
            what = "a whole number" if kind == "int" else "a finite number"
            raise _invalid(reader, name, f"must be {what}, got {text!r}") from None
        return value
    if kind == "bool":
        word = raw.lower()
        if word in _TRUE:
            return True
        if word in _FALSE:
            return False
        raise _invalid(reader, name, f"must be true or false, got {text!r}")
    if kind == "choice":
        if raw not in spec.choices:
            raise _invalid(reader, name, f"must be one of {list(spec.choices)}, got {text!r}")
        return raw
    items = [item.strip() for item in raw.split(",") if item.strip()]
    extra = [item for item in items if item not in spec.choices]
    if extra:
        raise _invalid(reader, name, f"has unknown choices {extra}")
    return items


def parse_assignments(
    parameters: Sequence[ReaderParameter], assignments: Sequence[str], *, reader: str = ""
) -> dict[str, Any]:
    """Parse ``name=value`` strings (the CLI's ``--option``) against a reader's parameters.

    Split on the first ``=`` only, so a value may contain one. A malformed assignment, an
    unknown name, or the same name twice is READER_OPTION_INVALID: a typo must not be
    silently ignored, and "last one wins" would hide a mistake.
    """
    by_name = {spec.name: spec for spec in parameters}
    parsed: dict[str, Any] = {}
    for item in assignments:
        name, separator, text = item.partition("=")
        name = name.strip()
        if not separator or not name:
            raise _invalid(reader, item, "is not of the form name=value")
        spec = by_name.get(name)
        if spec is None:
            raise _invalid(reader, name, "is not an option of this reader")
        if name in parsed:
            raise _invalid(reader, name, "was given more than once")
        parsed[name] = parse_value(spec, text, reader=reader)
    return parsed


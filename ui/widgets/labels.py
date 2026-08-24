"""
Shared "make an engine identifier human-readable" helper.

Track2Data surfaces several controlled vocabularies straight from the
engine in the GUI -- exporter names, preprocessing method literals,
metric ids -- and every one of them is an internal snake_case/kebab
identifier, not something a researcher should read verbatim. This is
the one place that "pretty-print a known value, with a sane fallback
for anything nobody wrote an override for yet" logic lives, rather
than every screen growing its own copy (this lifts the pattern
``ui/export_screen.py`` established first, for its exporter names).
"""

from __future__ import annotations


def label_for(value: str, overrides: dict[str, str] | None = None) -> str:
    """Return a human-readable label for a snake_case/lower engine value.

    *overrides* wins when present -- for the cases mechanical
    title-casing gets wrong (acronyms, hyphenation, a name that isn't
    just "insert spaces"). Otherwise falls back to replacing
    underscores with spaces and title-casing, so a value nobody wrote
    an override for still shows *something* reasonable rather than a
    raw identifier.
    """
    if overrides and value in overrides:
        return overrides[value]
    return value.replace("_", " ").title()

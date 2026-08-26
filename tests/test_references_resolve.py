"""
Every DOI in ``track2data/metrics/references.py`` must resolve, via
Crossref, to the work the entry actually claims.

The 2026-08 reference audit's central finding was that a citation can
be perfectly formatted, carry a perfectly valid DOI, and still point at
the wrong paper -- IL-8 cited a simulation paper for an empirical
measurement protocol, IL-4 a conceptual review for an operational
threshold, and GL-1 once carried a DOI copy-pasted from another metric
entirely. Those were caught by a human reading every entry. This test
makes the same check continuous: it asks Crossref what each DOI really
points to and fails if the first-author surname or the year disagrees
with what the bibliography says.

It cannot catch every kind of wrong citation -- a DOI for a real paper
by the right author in the right year that nonetheless doesn't support
the method is still a human judgement (see the audit's own verdicts in
CHANGELOG.md). What it does catch is the mechanical failure mode:
a transposed DOI, a copy-paste from a neighbouring entry, a Springer
``BF`` identifier off by one digit. The audit flagged that last one
specifically -- ``10.1007/BF00345747`` looks like Jacobs 1974's
``10.1007/BF00384581`` but resolves to an unrelated plant-physiology
paper.

**Marked ``network`` and excluded from CI** (``.github/workflows/ci.yml``
runs ``-m "not r_parity and not network"``). Thirty-five HTTP requests
per matrix cell on every push would be both slow and impolite to a free
public API, and would make CI fail whenever Crossref has a bad day --
an outage is not a defect in this repository. Run it deliberately
instead, which is when it matters (adding or editing a reference)::

    pytest tests/test_references_resolve.py -m network

The offline guards further down are *not* marked, so they do run in CI
on every push.
"""

from __future__ import annotations

import json
import unicodedata
import urllib.error
import urllib.request

import pytest

from track2data.metrics import references as references_module
from track2data.metrics.references import Reference

CROSSREF_WORKS = "https://api.crossref.org/works/"
TIMEOUT_S = 30

# Crossref asks API users to identify themselves. A project URL does
# that without putting anyone's personal email into an outbound request
# to a third party.
USER_AGENT = "Track2Data-reference-check/1.0 (+https://github.com/mbel-tech/Track2Data)"

# NFKD decomposes an accented letter into base + combining mark, which
# strips cleanly -- but it does nothing for a letter whose glyph carries
# the stroke itself, and "ø" has no canonical decomposition at all. Two
# of these references (Bjørneraas 2010, Tunstrøm 2013) would otherwise
# never match the ASCII spelling stored in the bibliography.
_STROKED_LETTERS = str.maketrans(
    {"ø": "o", "Ø": "O", "đ": "d", "Đ": "D", "ł": "l", "Ł": "L", "æ": "ae", "Æ": "AE", "ß": "ss"}
)


def _all_references() -> list[Reference]:
    """Every ``Reference`` declared in the bibliography module, sorted by
    key so parametrised test ids are stable."""
    found = [v for v in vars(references_module).values() if isinstance(v, Reference)]
    return sorted(found, key=lambda ref: ref.key)


def _with_doi() -> list[Reference]:
    return [ref for ref in _all_references() if ref.doi]


def _normalise_surname(name: str) -> str:
    """Casefold and strip diacritics so a stored ASCII spelling matches
    Crossref's own. Needed for Schnörr/Schnorr and Bjørneraas/Bjorneraas,
    and for Couzin, whose Crossref record spells the family name in all
    caps."""
    stripped = name.translate(_STROKED_LETTERS)
    decomposed = unicodedata.normalize("NFKD", stripped)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold().strip()


def _first_author_surname(bibtex_author: str) -> str:
    """Surname of the first author in a BibTeX ``author`` field --
    ``"Sibly, R. M. and Nott, H. M. R." -> "Sibly"``."""
    return bibtex_author.split(" and ")[0].split(",")[0].strip()


def _fetch_crossref(doi: str) -> dict:
    request = urllib.request.Request(
        f"{CROSSREF_WORKS}{doi}", headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        return json.load(response)["message"]


@pytest.fixture(scope="module")
def crossref_reachable() -> None:
    """Skip the whole module -- once -- when Crossref can't be reached,
    so an offline run reports 35 skips rather than 35 slow failures that
    say nothing about this repository."""
    try:
        _fetch_crossref(_with_doi()[0].doi)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        pytest.skip(f"Crossref unreachable ({exc}); skipping DOI resolution checks")


# ── The network check ─────────────────────────────────────────────────────────


@pytest.mark.network
@pytest.mark.slow
@pytest.mark.parametrize("ref", _with_doi(), ids=lambda ref: ref.key)
def test_doi_resolves_to_the_claimed_work(ref: Reference, crossref_reachable: None) -> None:
    """Parametrised one-per-reference rather than a single loop, so a bad
    DOI names itself in the failure and one broken entry doesn't mask the
    other thirty-four."""
    try:
        message = _fetch_crossref(ref.doi)
    except urllib.error.HTTPError as exc:
        pytest.fail(
            f"{ref.key}: DOI {ref.doi!r} did not resolve at Crossref "
            f"(HTTP {exc.code}). The bibliography claims: {ref.text}"
        )

    authors = message.get("author") or []
    got_surname = authors[0].get("family", "") if authors else ""
    want_surname = _first_author_surname(ref.author)
    crossref_title = (message.get("title") or [""])[0]

    assert _normalise_surname(got_surname) == _normalise_surname(want_surname), (
        f"{ref.key}: DOI {ref.doi} resolves to a work whose first author is "
        f"{got_surname!r}, but the bibliography says {want_surname!r}.\n"
        f"  Crossref title: {crossref_title}\n"
        f"  Bibliography:   {ref.text}"
    )

    issued = message.get("issued", {}).get("date-parts") or [[None]]
    got_year = issued[0][0]
    assert got_year == ref.year, (
        f"{ref.key}: DOI {ref.doi} resolves to a work published in {got_year}, "
        f"but the bibliography says {ref.year}.\n"
        f"  Crossref title: {crossref_title}\n"
        f"  Bibliography:   {ref.text}"
    )


# ── Offline guards (these DO run in CI) ───────────────────────────────────────


def test_every_reference_doi_is_a_bare_doi() -> None:
    """Catches a full ``https://doi.org/...`` URL, or citation text, in a
    field the generator writes straight into ``references.bib``.
    ``test_metric_references_consistency.py`` makes this check too, but
    only for ``citation_doi`` -- a DOI reachable solely through
    ``supporting_references`` is checked here and nowhere else."""
    import re

    bad = [
        (ref.key, ref.doi)
        for ref in _with_doi()
        if not re.fullmatch(r"10\.\d{4,9}/\S+", ref.doi)
    ]
    assert not bad, f"not bare DOIs (expected '10.xxxx/...'): {bad}"


def test_reference_keys_are_unique() -> None:
    """Two entries sharing a BibTeX key silently collapse into one in
    ``docs/references.bib`` -- the generator keys its dict by
    ``Reference.key``, so the second would overwrite the first and a
    citation would point at the wrong entry."""
    keys = [ref.key for ref in _all_references()]
    duplicates = {key for key in keys if keys.count(key) > 1}
    assert not duplicates, f"duplicate BibTeX keys in references.py: {sorted(duplicates)}"


def test_no_two_distinct_works_share_a_doi() -> None:
    """One DOI on two different ``Reference`` objects means at least one
    of them is wrong -- this is the bibliography-level form of the bug
    that put Couzin et al. 2002's DOI on GL-1."""
    by_doi: dict[str, set[str]] = {}
    for ref in _with_doi():
        by_doi.setdefault(ref.doi, set()).add(ref.key)
    conflicts = {doi: sorted(keys) for doi, keys in by_doi.items() if len(keys) > 1}
    assert not conflicts, f"the same DOI appears under different keys: {conflicts}"


def test_every_reference_declares_the_fields_the_bibtex_writer_needs() -> None:
    """``scripts/generate_metric_references.py`` writes author/title/year
    unconditionally, so an entry missing one would emit a malformed
    BibTeX record rather than fail loudly."""
    incomplete = [
        ref.key
        for ref in _all_references()
        if not (ref.author.strip() and ref.title.strip() and ref.year)
    ]
    assert not incomplete, f"references missing author/title/year: {incomplete}"

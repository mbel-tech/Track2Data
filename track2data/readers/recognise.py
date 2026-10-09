"""Formats Track2Data can name but cannot read, and what to do instead.

A folder of SLEAP ``.slp`` projects used to produce "nothing recognised", which sends people
looking for a bug that is not there. These entries turn it into "this is SLEAP's project file;
export Analysis HDF5". A match is information only: it never becomes a session to add.

Every signature is something the format itself fixes (a file name, a suffix, a folder name, or a
header row), read with the same header-only ``Peeker`` as everything else in a scan. When a reader
for one of these formats lands, its entry is deleted here, so the table is also the list of what
is still missing.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from track2data.readers.index import IndexEntry, ScanIndex
from track2data.readers.peek import Peeker

Matcher = Callable[[IndexEntry, ScanIndex, Peeker], bool]

#: A FicTrac log line has at least this many numeric columns.
_FICTRAC_COLUMNS = 23


@dataclass(frozen=True)
class RecognisedFormat:
    """A format we can identify but not read."""

    key: str
    display_name: str
    remediation: str
    match: Matcher


@dataclass(frozen=True)
class Recognised:
    """What a scan found of one such format: how many files, and one to point at."""

    key: str
    display_name: str
    remediation: str
    example: Path
    count: int


def _named(*names: str) -> Matcher:
    wanted = {n.lower() for n in names}
    return lambda entry, _index, _peek: not entry.is_dir and entry.name.lower() in wanted


def _suffix(suffix: str) -> Matcher:
    return lambda entry, _index, _peek: not entry.is_dir and entry.suffix == suffix


def _ends_with(tail: str) -> Matcher:
    return lambda entry, _index, _peek: not entry.is_dir and entry.name.lower().endswith(tail)


def _animalta_detailed(entry: IndexEntry, index: ScanIndex, _peek: Peeker) -> bool:
    return (
        not entry.is_dir
        and entry.suffix == ".csv"
        and entry.name.lower().startswith("arena_")
        and any(p.name.lower() == "detailed_data" for p in entry.path.parents)
    )


def _dlc_3d(entry: IndexEntry, _index: ScanIndex, peek: Peeker) -> bool:
    """A DeepLabCut table whose coordinates are x, y, z and that has no likelihood."""
    if entry.is_dir or entry.suffix != ".csv":
        return False
    lines = peek.text_lines(entry.path, 4)
    if not lines or not lines[0].lower().startswith("scorer"):
        return False
    for line in lines[1:4]:
        cells = [c.strip().lower() for c in line.split(",")]
        if cells and cells[0] == "coords":
            coords = set(cells[1:])
            return "z" in coords and "likelihood" not in coords
    return False


def _fictrac(entry: IndexEntry, _index: ScanIndex, peek: Peeker) -> bool:
    """A headerless ``.dat`` whose first line is a long row of numbers."""
    if entry.is_dir or entry.suffix != ".dat":
        return False
    lines = peek.text_lines(entry.path, 1)
    if not lines:
        return False
    cells = lines[0].split(",")
    if len(cells) < _FICTRAC_COLUMNS:
        return False
    try:
        for cell in cells:
            float(cell)
    except ValueError:
        return False
    return True


FORMATS: tuple[RecognisedFormat, ...] = (
    RecognisedFormat(
        "sleap_slp",
        "SLEAP project (.slp)",
        "This is SLEAP's project file, which Track2Data does not read. In SLEAP choose "
        "File > Export Analysis HDF5 and add the exported .h5 file instead.",
        _suffix(".slp"),
    ),
    RecognisedFormat(
        "trx_mat",
        "Ctrax / JAABA trx.mat",
        "This looks like a trx.mat file (the Ctrax / FlyTracker / JAABA interchange format) that "
        "Track2Data cannot read: only classic MATLAB files holding a 'trx' struct are. Save it "
        "again with -v7 (not -v7.3), or add the raw Ctrax .mat instead.",
        _named("trx.mat"),
    ),
    RecognisedFormat(
        "flytracker",
        "FlyTracker output (-track.mat)",
        "This is FlyTracker's own -track.mat, which Track2Data cannot read. Export the "
        "JAABA files from FlyTracker (a trx.mat in a -JAABA folder) and add that.",
        _ends_with("-track.mat"),
    ),
    RecognisedFormat(
        "dannce",
        "DANNCE predictions (save_data_AVG.mat)",
        "This is DANNCE's 3-D prediction file, which Track2Data cannot read: it has no "
        "documented layout to read it against. Export the per-camera 2-D keypoints instead.",
        _named("save_data_AVG.mat"),
    ),
    RecognisedFormat(
        "mwt",
        "Multi-Worm Tracker (.blobs)",
        "These are Multi-Worm Tracker blob files, which Track2Data cannot read. Convert "
        "them with Choreography, or with the MWT-to-WCON converter, and add that output.",
        _suffix(".blobs"),
    ),
    RecognisedFormat(
        "animalta_detailed",
        "AnimalTA detailed data",
        "These are AnimalTA's per-target detailed files, which do not record their unit, so "
        "they are not read. Add the Coordinates .csv from the same AnimalTA run instead.",
        _animalta_detailed,
    ),
    RecognisedFormat(
        "dlc_3d",
        "DeepLabCut 3-D table",
        "This is a DeepLabCut 3-D table (x, y, z with no likelihood), which Track2Data cannot "
        "read yet. Add the 2-D CSV or .h5 DeepLabCut wrote for one camera instead.",
        _dlc_3d,
    ),
    RecognisedFormat(
        "fictrac",
        "FicTrac log (.dat)",
        "This is a FicTrac log of a spherical-treadmill path, not arena trajectories, so it "
        "is not read. Add the tracking output of the video of the animal instead.",
        _fictrac,
    ),
)


def find_unreadable(
    index: ScanIndex,
    peek: Peeker,
    claimed: Sequence[Path] = (),
    formats: Sequence[RecognisedFormat] = FORMATS,
) -> tuple[Recognised, ...]:
    """The formats in *index* that are recognised but unreadable.

    *claimed* are folders a reader already owns; files inside them are not reported (a stray
    ``.slp`` in an idtracker.ai session is not news). Never raises.
    """
    counts: dict[str, int] = {}
    examples: dict[str, Path] = {}
    # The walk lists a folder before what is inside it, so "inside a claimed folder" can be carried
    # down one level at a time instead of searching every entry's ancestors.
    covered = set(claimed)
    for entry in index.walk():
        if entry.path in covered or entry.path.parent in covered:
            covered.add(entry.path)
            continue
        if entry.cloud_only:
            continue
        for fmt in formats:
            try:
                hit = fmt.match(entry, index, peek)
            except Exception:  # a misbehaving matcher must never break a scan
                hit = False
            if hit:
                counts[fmt.key] = counts.get(fmt.key, 0) + 1
                examples.setdefault(fmt.key, entry.path)
                break
    by_key = {fmt.key: fmt for fmt in formats}
    return tuple(
        Recognised(key, by_key[key].display_name, by_key[key].remediation, examples[key], n)
        for key, n in counts.items()
    )

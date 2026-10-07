"""Formats we can name but not read: the scan says what they are and what to do instead.

Each entry is matched by something the format itself fixes (a file name or suffix, or a header
row), never by a guess, so a folder that is *not* one of these is never mislabelled. A match is
information, not a session: it never appears as something to add.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from track2data.readers.recognise import FORMATS
from track2data.readers.scan import scan

DLC_3D = "scorer,s,s,s\nbodyparts,nose,nose,nose\ncoords,x,y,z\n0,1.0,2.0,3.0\n"
DLC_2D = "scorer,s,s,s\nbodyparts,nose,nose,nose\ncoords,x,y,likelihood\n0,1.0,2.0,0.9\n"
FICTRAC = ",".join(str(float(i)) for i in range(25)) + "\n"


def _write(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


#: key -> a function that builds a minimal folder that format fixes
BUILDERS = {
    "sleap_slp": lambda r: _write(r / "labels.v001.slp"),
    "trx_mat": lambda r: _write(r / "run1" / "trx.mat"),
    "flytracker": lambda r: _write(r / "movie-track.mat"),
    "dannce": lambda r: _write(r / "DANNCE" / "predict00" / "save_data_AVG.mat"),
    "mwt": lambda r: _write(r / "exp" / "20240101_120000.blobs"),
    "animalta_detailed": lambda r: _write(
        r / "Results" / "Detailed_data" / "vid" / "Arena_0A.csv", "Time;X;Y\n0;1;2\n"
    ),
    "dlc_3d": lambda r: _write(r / "trial_3d.csv", DLC_3D),
    "fictrac": lambda r: _write(r / "fictrac-20240101.dat", FICTRAC),
}


def test_the_table_and_the_fixtures_cover_the_same_formats() -> None:
    assert {f.key for f in FORMATS} == set(BUILDERS)


@pytest.mark.parametrize("key", sorted(BUILDERS))
def test_each_format_is_named_with_what_to_do_instead(key: str, tmp_path: Path) -> None:
    BUILDERS[key](tmp_path)

    result = scan([tmp_path])

    assert result.groups == ()  # nothing to add
    (found,) = result.recognised
    assert found.key == key
    assert found.display_name and found.remediation.endswith(".")
    assert found.count == 1 and found.example.exists()


@pytest.mark.parametrize("key", sorted(BUILDERS))
def test_every_remediation_says_something_actionable(key: str) -> None:
    (fmt,) = (f for f in FORMATS if f.key == key)
    assert len(fmt.remediation) > 40


def test_a_dlc_2d_table_is_not_taken_for_3d(tmp_path: Path) -> None:
    _write(tmp_path / "trial.csv", DLC_2D)
    assert scan([tmp_path]).recognised == ()


def test_a_short_numeric_dat_file_is_not_fictrac(tmp_path: Path) -> None:
    _write(tmp_path / "log.dat", "1,2,3\n")
    assert scan([tmp_path]).recognised == ()


def test_an_ordinary_mat_file_is_not_named(tmp_path: Path) -> None:
    _write(tmp_path / "data.mat")
    assert scan([tmp_path]).recognised == ()


def test_several_files_of_one_format_are_counted_once(tmp_path: Path) -> None:
    for n in range(3):
        _write(tmp_path / f"v{n}.slp")
    (found,) = scan([tmp_path]).recognised
    assert found.count == 3


def test_two_different_formats_are_both_reported(tmp_path: Path) -> None:
    BUILDERS["sleap_slp"](tmp_path)
    BUILDERS["mwt"](tmp_path)
    assert {r.key for r in scan([tmp_path]).recognised} == {"sleap_slp", "mwt"}


def test_a_file_inside_a_session_we_can_read_is_not_reported(
    tiny_real_session: Path, tmp_path: Path
) -> None:
    import shutil

    shutil.copytree(tiny_real_session, tmp_path / "s1")
    _write(tmp_path / "s1" / "stray.slp")

    result = scan([tmp_path])

    assert [g.best.reader for g in result.groups] == ["idtrackerai"]
    assert result.recognised == ()


def test_a_junk_header_never_raises(tmp_path: Path) -> None:
    (tmp_path / "bad.csv").write_bytes(b"\xff\xfe\x00scorer\x00")
    (tmp_path / "empty.dat").write_bytes(b"")
    assert scan([tmp_path]).recognised == ()


def test_xy_only_is_not_a_3d_table(tmp_path: Path) -> None:
    _write(tmp_path / "t.csv", "scorer,s,s\nbodyparts,n,n\ncoords,x,y\n0,1,2\n")
    assert scan([tmp_path]).recognised == ()


def test_a_table_with_likelihood_is_not_a_3d_table_even_with_z(tmp_path: Path) -> None:
    _write(
        tmp_path / "t.csv",
        "scorer,s,s,s,s\nbodyparts,n,n,n,n\ncoords,x,y,z,likelihood\n0,1,2,3,1\n",
    )
    assert scan([tmp_path]).recognised == ()


def test_a_long_dat_row_that_is_not_all_numbers_is_not_fictrac(tmp_path: Path) -> None:
    cells = [str(float(i)) for i in range(24)] + ["label"]
    _write(tmp_path / "log.dat", ",".join(cells) + "\n")
    assert scan([tmp_path]).recognised == ()


def test_an_arena_csv_outside_detailed_data_is_not_animalta_detailed(tmp_path: Path) -> None:
    _write(tmp_path / "Results" / "other" / "Arena_0A.csv", "Time;X;Y\n")
    assert scan([tmp_path]).recognised == ()


def test_a_file_is_reported_under_one_format_only(tmp_path: Path) -> None:
    from dataclasses import replace

    from track2data.readers.index import build_index
    from track2data.readers.peek import Peeker
    from track2data.readers.recognise import find_unreadable

    path = _write(tmp_path / "a.slp")
    first = replace(FORMATS[0], key="one")
    second = replace(FORMATS[0], key="two")
    index = build_index([tmp_path])
    found = find_unreadable(index, Peeker(None, index), formats=(first, second))
    assert [r.key for r in found] == ["one"] and found[0].example == path


def test_a_cloud_only_placeholder_is_never_opened_or_reported(tmp_path: Path) -> None:
    from track2data.readers.index import IndexEntry, ScanIndex
    from track2data.readers.peek import Peeker
    from track2data.readers.recognise import find_unreadable

    path = tmp_path / "a.slp"
    index = ScanIndex([tmp_path], [IndexEntry(path, False, 10, cloud_only=True)])
    assert find_unreadable(index, Peeker(None, index)) == ()

"""Review finding C21: the WARNING line regex must not backtrack catastrophically."""

from __future__ import annotations

import time
from pathlib import Path

from track2data.readers.idtrackerai.log import load_log_digest


def _write(folder: Path, body: str) -> None:
    (folder / "idtrackerai.log").write_text(body, encoding="utf-8")


def test_a_warning_line_of_spaces_without_a_source_is_parsed_quickly(tmp_path: Path) -> None:
    # A level word followed by a long run of spaces and no ``file.py:N`` source: the old
    # pattern's overlapping ``\s+ .*? \s+ \s*`` made this cubic (about 50 s at 2 KB).
    _write(tmp_path, "12:00:00 WARNING " + " " * 5000 + "\n")
    start = time.perf_counter()
    load_log_digest(tmp_path)
    # The old pattern took minutes on 5 KB; a linear one takes milliseconds.
    assert time.perf_counter() - start < 2.0


def test_warning_lines_still_parse(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "12:00:00 WARNING   There are 75 frames with more blobs   segmentation.py:120\n"
        "WARNING no source on this one\n"
        "ERROR something broke   run.py:9\n",
    )
    digest = load_log_digest(tmp_path)
    assert digest is not None
    warnings = digest["warnings"]
    assert any("75 frames" in w for w in warnings)
    assert any("something broke" in w for w in warnings)
    assert not any("no source" in w for w in warnings)

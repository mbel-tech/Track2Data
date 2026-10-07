"""Export screen: ready-to-paste R / Python code for the files just written."""

from __future__ import annotations

from pathlib import Path

from ui.store.code_snippets import analysis_snippets

OUT = Path("/data/exports/run1")


def test_csv_long_snippets_read_every_session_summary() -> None:
    snips = analysis_snippets(OUT, ["s1", "s2"], ["csv_long"])
    r, py = snips["R (tidyverse)"], snips["Python (pandas)"]
    assert "library(readr)" in r and "library(dplyr)" in r
    assert "trial_activity_summary.csv" in r and "s1" in r and "s2" in r
    assert "import pandas as pd" in py
    assert "trial_activity_summary.csv" in py and "pd.concat" in py


def test_feather_snippets_use_the_arrow_readers() -> None:
    snips = analysis_snippets(OUT, ["s1"], ["feather"])
    assert "arrow::read_feather" in snips["R (tidyverse)"]
    assert "pd.read_feather" in snips["Python (pandas)"]


def test_excel_snippet_reads_the_workbook() -> None:
    snips = analysis_snippets(OUT, ["s1"], ["excel"], project_name="Proj")
    assert "readxl::read_excel" in snips["R (tidyverse)"]
    assert "Track2Data_Proj.xlsx" in snips["Python (pandas)"]


def test_prefers_feather_then_csv_long_then_wide_then_excel() -> None:
    snips = analysis_snippets(OUT, ["s1"], ["csv_long", "feather"])
    assert "read_feather" in snips["Python (pandas)"]
    snips = analysis_snippets(OUT, ["s1"], ["csv_wide"])
    assert "trial_summary_wide.csv" in snips["Python (pandas)"]


def test_nothing_to_show_without_a_loadable_format() -> None:
    assert analysis_snippets(OUT, ["s1"], ["readme"]) == {}
    assert analysis_snippets(OUT, [], ["csv_long"]) == {}


def test_paths_are_quoted_safely() -> None:
    snips = analysis_snippets(Path('/a "b"/out'), ["s'1"], ["csv_long"])
    for code in snips.values():
        assert '"b"' not in code.replace('\\"b\\"', "")  # no raw unescaped quote pair

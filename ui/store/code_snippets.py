"""Ready-to-paste R and Python code that loads what an export just wrote.

Pure string building (no Qt) so it is unit-testable. Output layout is the one
``Engine.run`` produces: ``<out_dir>/<session_id>/<file>``, one folder per
session. The first loadable format found, in order feather, csv_long,
csv_wide, excel, is used.
"""

from __future__ import annotations

import json
from pathlib import Path


def _q(text: str) -> str:
    """A double-quoted string literal valid in both R and Python."""
    return json.dumps(str(text).replace("\\", "/"))


def analysis_snippets(
    out_dir: Path,
    session_ids: list[str],
    exporters: list[str],
    project_name: str = "project",
) -> dict[str, str]:
    """{language label: code}; empty when no exported format can be loaded."""
    if not session_ids:
        return {}
    root = _q(out_dir.as_posix())
    ids = ", ".join(_q(s) for s in session_ids)

    if "feather" in exporters:
        fname = "trial_activity_summary.feather"
        r = (
            "library(dplyr)\nlibrary(purrr)\n\n"
            f"root <- {root}\nsessions <- c({ids})\n"
            f'activity <- map_dfr(sessions, ~ arrow::read_feather(file.path(root, .x, "{fname}")) '
            "%>% mutate(session = .x))\n"
        )
        py = (
            "import pandas as pd\nfrom pathlib import Path\n\n"
            f"root = Path({root})\nsessions = [{ids}]\n"
            f'activity = pd.concat([pd.read_feather(root / s / "{fname}") for s in sessions])\n'
        )
    elif "csv_long" in exporters or "csv_wide" in exporters:
        fname = (
            "trial_activity_summary.csv" if "csv_long" in exporters else "trial_summary_wide.csv"
        )
        r = (
            "library(readr)\nlibrary(dplyr)\nlibrary(purrr)\n\n"
            f"root <- {root}\nsessions <- c({ids})\n"
            f'activity <- map_dfr(sessions, ~ read_csv(file.path(root, .x, "{fname}")) '
            "%>% mutate(session = .x))\n"
        )
        py = (
            "import pandas as pd\nfrom pathlib import Path\n\n"
            f"root = Path({root})\nsessions = [{ids}]\n"
            f'activity = pd.concat([pd.read_csv(root / s / "{fname}") for s in sessions])\n'
        )
    elif "excel" in exporters:
        fname = f"Track2Data_{project_name}.xlsx"
        r = (
            "library(readxl)\n\n"
            f"root <- {root}\nsessions <- c({ids})\n"
            f'activity <- readxl::read_excel(file.path(root, sessions[1], "{fname}"), '
            'sheet = "Activity Summary")\n'
        )
        py = (
            "import pandas as pd\nfrom pathlib import Path\n\n"
            f"root = Path({root})\nsessions = [{ids}]\n"
            f'activity = pd.read_excel(root / sessions[0] / "{fname}", '
            'sheet_name="Activity Summary")\n'
        )
    else:
        return {}
    return {"R (tidyverse)": r, "Python (pandas)": py}

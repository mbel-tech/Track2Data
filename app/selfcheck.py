"""
``Track2Data --self-check``: export a tiny payload through every built-in
exporter and exit non-zero if any is missing or writes nothing.

The release workflow's smoke test (packaging/smoke_test.py) runs this against
the frozen binary. Checking only that the window stays open cannot catch an
exporter module PyInstaller left out, because exporters are imported quietly
and a missing one simply does not register.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

BUILTIN_EXPORTERS = ("csv_long", "csv_wide", "excel", "feather", "readme")


def _payload() -> object:
    import pandas as pd

    from track2data.exporters.base import ExportPayload

    return ExportPayload(
        session_id="selfcheck",
        project_name="SelfCheck",
        project_hash="0000000000000000",
        app_version="selfcheck",
        fish_by_frame=pd.DataFrame(
            {
                "session_id": ["selfcheck"] * 2,
                "individual_id": [0, 0],
                "frame": [0, 1],
                "x": [1.0, 2.0],
                "y": [3.0, 4.0],
            }
        ),
        individual_metrics={
            "IL-1": pd.DataFrame(
                {"session_id": ["selfcheck"], "individual_id": [0], "mean_speed_cm_s": [1.0]}
            )
        },
        manifest_json=json.dumps({"schema_version": 1, "project_name": "SelfCheck"}),
    )


def run_self_check(out: object = None) -> int:
    """Return 0 when every built-in exporter writes at least one file."""
    from track2data.exporters import get_exporter

    stream = out if out is not None else sys.stderr
    failures: list[str] = []
    payload = _payload()
    with tempfile.TemporaryDirectory(prefix="t2d-selfcheck-") as tmp:
        for name in BUILTIN_EXPORTERS:
            exporter = get_exporter(name)
            if exporter is None:
                failures.append(f"{name}: not registered")
                continue
            target = Path(tmp) / name
            target.mkdir()
            try:
                paths = exporter.write(payload, target)
            except Exception as exc:  # reported, not hidden
                failures.append(f"{name}: {type(exc).__name__}: {exc}")
                continue
            if not paths or not all(Path(p).is_file() for p in paths):
                failures.append(f"{name}: wrote no files")
    if stream is not None:
        if failures:
            print("self-check FAILED:\n  " + "\n  ".join(failures), file=stream)  # type: ignore[arg-type]
        else:
            print("self-check OK: " + ", ".join(BUILTIN_EXPORTERS), file=stream)  # type: ignore[arg-type]
    return 1 if failures else 0

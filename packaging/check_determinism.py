"""
Release-tag determinism gate (issue #47).

Runs the same synthetic project through Engine.run() twice, into two
fresh temp directories, and asserts every output file is byte-identical
across the two runs -- manifest.json's created_at/updated_at timestamps
are masked first, since those are expected to differ run-to-run.

Per docs/TECHNICAL_SPEC.md §11.4 (NFR-6 / PRD DV-5): any drift here
means the pipeline has a hidden source of nondeterminism (unordered
dict/set iteration, an uninitialised RNG, wall-clock leaking into
output) and the release must not ship.

Reuses tests/conftest.py's tiny_real_session builder rather than
duplicating synthetic-session construction -- this is the same fixture
data every other test in the suite is validated against.
"""

from __future__ import annotations

import filecmp
import hashlib
import re
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from track2data.api import Engine  # noqa: E402
from track2data.core.models import (  # noqa: E402
    CalibrationConfig,
    MetricSelection,
    ProjectManifest,
    SessionRef,
)

# manifest.json carries the project's own created_at/updated_at plus a
# run_metadata.generated_at stamped fresh by exporters/readme.py on every
# export; README.md's "Generated at" table row is the same timestamp in
# human-readable form. All three are expected to differ between two runs
# by design and are masked before comparing -- everything else in every
# output file, including the rest of manifest.json and README.md, must
# still match exactly.
_JSON_TIMESTAMP_RE = re.compile(r'"(created_at|updated_at|generated_at)":\s*"[^"]*"')
_README_TIMESTAMP_RE = re.compile(r"(\| Generated at \| )[^|]*(\|)")


def _mask_timestamps(path: Path) -> None:
    if path.name == "manifest.json":
        text = path.read_text(encoding="utf-8")
        path.write_text(_JSON_TIMESTAMP_RE.sub(r'"\1": "MASKED"', text), encoding="utf-8")
    elif path.name == "README.md":
        text = path.read_text(encoding="utf-8")
        path.write_text(_README_TIMESTAMP_RE.sub(r"\1MASKED \2", text), encoding="utf-8")


def _make_manifest(session_folder: Path) -> ProjectManifest:
    now = datetime.now(tz=UTC)
    return ProjectManifest(
        project_name="determinism_check",
        created_at=now,
        updated_at=now,
        sessions=[
            SessionRef(
                session_id=session_folder.name,
                folder=session_folder,
                sha256=hashlib.sha256(str(session_folder).encode()).hexdigest(),
            )
        ],
        calibration=CalibrationConfig(mode="scalar", px_per_cm=10.0),
        metrics=MetricSelection(individual=["IL-1", "IL-2"], group=["GL-1"]),
    )


def _run_once(manifest: ProjectManifest, out_dir: Path) -> None:
    Engine(manifest).run(out_dir)


def _diff_trees(a: Path, b: Path) -> list[str]:
    mismatches: list[str] = []
    comparison = filecmp.dircmp(a, b)
    if comparison.left_only or comparison.right_only:
        mismatches.append(
            f"file sets differ under {a.name}: only-in-A={comparison.left_only} "
            f"only-in-B={comparison.right_only}"
        )
    for name in comparison.common_files:
        if not filecmp.cmp(a / name, b / name, shallow=False):
            mismatches.append(f"content differs: {a / name}")
    for sub in comparison.common_dirs:
        mismatches.extend(_diff_trees(a / sub, b / sub))
    return mismatches


def main() -> int:
    from conftest import _build_tiny_real_session

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        session_folder = tmp_path / "session"
        session_folder.mkdir()
        _build_tiny_real_session(session_folder)

        manifest = _make_manifest(session_folder)

        out_a = tmp_path / "out_a"
        out_b = tmp_path / "out_b"
        _run_once(manifest, out_a)
        _run_once(manifest, out_b)

        for out_dir in (out_a, out_b):
            for path in (*out_dir.rglob("manifest.json"), *out_dir.rglob("README.md")):
                _mask_timestamps(path)

        mismatches = _diff_trees(out_a, out_b)

    if mismatches:
        print("DETERMINISM CHECK FAILED:", file=sys.stderr)
        for m in mismatches:
            print(f"  {m}", file=sys.stderr)
        return 1

    print("Determinism check passed: two independent runs produced byte-identical output.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
Regenerate ``docs/METRIC_REFERENCES.csv`` from the metric registry.

Each metric's ``documentation.citation`` / ``documentation.citation_doi``
in the code is the single source of truth; this script only publishes
them in a citable, spreadsheet-readable form. Never hand-edit the CSV --
edit the metric's ``MetricDocumentation`` and re-run this.

``tests/test_metric_references_consistency.py`` fails if the committed
CSV and a fresh regeneration differ, so adding or changing a metric
without re-running this is caught in CI rather than silently publishing
a stale reference list.

Usage::

    python scripts/generate_metric_references.py           # rewrite the CSV
    python scripts/generate_metric_references.py --check   # exit 1 if stale
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = REPO_ROOT / "docs" / "METRIC_REFERENCES.csv"

HEADER = ["metric_id", "level", "priority", "metric_name", "reference", "doi"]


def render_csv() -> str:
    """Return the full CSV text for the current metric registry.

    Written with an explicit "\\n" lineterminator rather than csv's
    "\\r\\n" default so the committed file has one canonical form on
    every platform -- otherwise the drift test would fail on Windows
    against a file generated on Linux, or vice versa.
    """
    # Imported here, not at module scope, so `--help` works even if an
    # optional metric dependency (scipy, shapely) is missing.
    from track2data import metrics

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(HEADER)

    for metric_id in metrics.all_ids():
        metric_cls = metrics.get(metric_id)
        doc = metric_cls.documentation
        writer.writerow(
            [
                metric_cls.id,
                metric_cls.level,
                metric_cls.priority,
                metric_cls.label,
                doc.citation or "",
                doc.citation_doi or "",
            ]
        )

    return buffer.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if the committed CSV is stale, without rewriting it",
    )
    args = parser.parse_args()

    generated = render_csv()

    if args.check:
        current = CSV_PATH.read_text(encoding="utf-8") if CSV_PATH.exists() else ""
        if current != generated:
            print(f"{CSV_PATH.relative_to(REPO_ROOT)} is out of date; re-run without --check")
            return 1
        print(f"{CSV_PATH.relative_to(REPO_ROOT)} is up to date")
        return 0

    CSV_PATH.write_text(generated, encoding="utf-8", newline="")
    row_count = generated.count("\n") - 1
    print(f"wrote {CSV_PATH.relative_to(REPO_ROOT)} ({row_count} metrics)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Generate the browsable metric catalogue for the docs site.

    python scripts/generate_metric_catalogue.py docs/site/metrics.md

Generated from the registry rather than maintained by hand, for the same
reason ``docs/METRIC_REFERENCES.csv`` is: a catalogue that drifts from the
code describes metrics the tool does not compute, and a researcher reads it
to decide what to cite.

``docs/METRICS_SPEC.md`` stays the canonical, implementation-facing
specification. This is the reader-facing view of the same data -- one
linkable, citable page per level, with the formula, units, assumptions,
warnings and DOI a user needs before choosing a measure.
"""

from __future__ import annotations

import sys
from pathlib import Path

import track2data.metrics as registry
from track2data.exporters.schema import unit_for_column

LEVELS = [
    ("individual", "Individual-level", "One value per animal per session."),
    ("group", "Group-level", "One value per session, describing the group as a whole."),
    ("zone", "Zone-level", "One value per animal per zone."),
    (
        "diagnostic",
        "Diagnostics",
        "Always computed. These describe the *quality of the tracking*, not "
        "the animals -- read them before trusting anything above.",
    ),
]


def _doi_link(doi: str | None) -> str:
    if not doi:
        return "—"
    return f"[{doi}](https://doi.org/{doi})"


def _bullets(items: list[str]) -> str:
    if not items:
        return "_none recorded_"
    return "\n".join(f"- {item}" for item in items)


def render() -> str:
    lines: list[str] = [
        "# Metric catalogue",
        "",
        f"Every one of the {len(registry.all_ids())} metrics Track2Data computes, "
        "generated from the registry so it cannot drift from the code.",
        "",
        "Each entry states what the metric measures, the formula, the units of "
        "every column it emits, the assumptions it rests on, the warnings that "
        "come with it, and the work that defines it. **Every metric carries a "
        "citation** — a measure with no citable source does not get "
        "implemented.",
        "",
        "See [interoperability](interoperability.md) for reading these outputs "
        "in R or Python.",
        "",
    ]

    for level, heading, blurb in LEVELS:
        ids = [
            mid for mid in registry.all_ids()
            if (cls := registry.get(mid)) is not None and cls.level == level
        ]
        if not ids:
            continue
        lines += [f"## {heading}", "", blurb, ""]

        for metric_id in ids:
            metric_cls = registry.get(metric_id)
            assert metric_cls is not None
            doc = metric_cls.documentation

            lines += [
                f"### {metric_id} — {metric_cls.label}",
                "",
                doc.definition,
                "",
                "**Formula**",
                "",
                f"```\n{doc.formula_plain}\n```",
                "",
                "**Output columns**",
                "",
                "| Column | Unit |",
                "|---|---|",
            ]
            for column in metric_cls.output_columns:
                if column in ("session_id", "metric_id"):
                    continue
                lines.append(f"| `{column}` | {unit_for_column(column)} |")

            lines += [
                "",
                "**Assumptions**",
                "",
                _bullets(doc.assumptions),
                "",
                "**Warnings**",
                "",
                _bullets(doc.warnings),
                "",
                f"**Reference** — {doc.citation or '—'}",
                "",
                f"**DOI** — {_doi_link(doc.citation_doi)}",
                "",
            ]
            if doc.supporting_references:
                supporting = "; ".join(
                    f"{ref.text} ({_doi_link(ref.doi)})"
                    for ref in doc.supporting_references
                )
                lines += [f"**Supporting** — {supporting}", ""]
            if metric_cls.superseded_by:
                lines += [
                    f"> **Superseded by {metric_cls.superseded_by}.** Kept for "
                    "output-compatibility with existing projects; prefer the "
                    "newer metric for new work.",
                    "",
                ]
            lines.append("---")
            lines.append("")

    return "\n".join(lines)


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/site/metrics.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(), encoding="utf-8")
    print(f"wrote {out} ({len(registry.all_ids())} metrics)")


if __name__ == "__main__":
    main()

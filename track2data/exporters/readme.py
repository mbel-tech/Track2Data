"""Human-readable run README.md + manifest.json exporter."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from track2data.exporters.base import Exporter, ExportPayload


class ReadmeExporter(Exporter):
    """Write a human-readable README.md and an updated manifest.json.

    Files written
    -------------
    * ``README.md`` — plain-text run summary.
    * ``manifest.json`` — the original project manifest augmented with run
      metadata (session count, computed metric IDs, app version, timestamp).
    """

    name = "readme"
    file_extension = ".md"

    def write(self, payload: object, out_dir: Path) -> list[Path]:
        """Write README.md and manifest.json to *out_dir*.

        Parameters
        ----------
        payload:
            An :class:`ExportPayload` instance.
        out_dir:
            Output directory.

        Returns
        -------
        list[Path]
            ``[README.md path, manifest.json path]``
        """
        p: ExportPayload = payload  # type: ignore[assignment]
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(tz=UTC).isoformat()

        # ── collect metric IDs ─────────────────────────────────────────────────
        all_metric_ids: list[str] = (
            list(p.individual_metrics.keys())
            + list(p.group_metrics.keys())
            + list(p.zone_metrics.keys())
            + list(p.diagnostic_metrics.keys())
        )

        # ── README.md ──────────────────────────────────────────────────────────
        readme_lines = [
            f"# Track2Data Run Report — {p.project_name}",
            "",
            "## Run metadata",
            "",
            "| Field | Value |",
            "|-------|-------|",
            f"| Project name | {p.project_name} |",
            f"| Project hash | `{p.project_hash}` |",
            f"| App version | {p.app_version} |",
            f"| Session ID | {p.session_id} |",
            f"| Generated at | {timestamp} |",
            "",
            "## Metrics computed",
            "",
        ]
        if all_metric_ids:
            for mid in all_metric_ids:
                readme_lines.append(f"- {mid}")
        else:
            readme_lines.append("*(none)*")

        preprocess_steps = p.preprocess_report.steps
        readme_lines += [
            "",
            "## Preprocessing steps",
            "",
        ]
        if preprocess_steps:
            for step in preprocess_steps:
                readme_lines.append(
                    f"- **{step.step_name}**: {step.affected_frames} frames affected. "
                    f"{step.notes}"
                )
        else:
            readme_lines.append("*(no preprocessing steps recorded)*")

        readme_lines.append("")

        readme_text = "\n".join(readme_lines)
        readme_path = out_dir / "README.md"
        readme_path.write_text(readme_text, encoding="utf-8")

        # ── manifest.json ──────────────────────────────────────────────────────
        try:
            manifest_data: dict = json.loads(p.manifest_json)
        except (json.JSONDecodeError, TypeError):
            manifest_data = {}

        # Augment with run metadata
        manifest_data.setdefault("project_name", p.project_name)
        manifest_data["run_metadata"] = {
            "session_id": p.session_id,
            "project_hash": p.project_hash,
            "app_version": p.app_version,
            "generated_at": timestamp,
            "metrics_computed": all_metric_ids,
        }

        manifest_path = out_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest_data, indent=2, default=str), encoding="utf-8"
        )

        return [readme_path, manifest_path]


# ── Registration ──────────────────────────────────────────────────────────────

from track2data.exporters import register as _register  # noqa: E402

_register(ReadmeExporter)

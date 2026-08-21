"""Human-readable run README.md + manifest.json exporter."""

from __future__ import annotations

import json
from dataclasses import asdict
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
        ]

        readme_lines += self._provenance_lines(p.provenance)

        readme_lines += [
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
            "session_provenance": asdict(p.provenance),
        }

        manifest_path = out_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest_data, indent=2, default=str), encoding="utf-8"
        )

        return [readme_path, manifest_path]

    @staticmethod
    def _provenance_lines(prov: object) -> list[str]:
        """
        Render idtracker.ai-derived quality/provenance values, not just
        their names.

        Before ExportPayload carried a SessionProvenance, this section
        didn't exist at all: the README listed only metric *IDs* (e.g.
        "D-2"), never the estimated_accuracy or fraction_identified value
        that metric actually reports, and had no way to say which
        trajectory format was read or whether the tracking run itself
        succeeded.
        """
        from track2data.exporters.base import SessionProvenance

        p: SessionProvenance = prov  # type: ignore[assignment]
        lines = [
            "## idtracker.ai provenance",
            "",
            "| Field | Value |",
            "|-------|-------|",
            f"| Reader | {p.reader or '*(unknown)*'} |",
            f"| idtracker.ai version | {p.idtrackerai_version or '*(unknown)*'} |",
            f"| Trajectory format read | {p.trajectory_format or '*(unknown)*'} |",
            f"| Trajectory variant | {p.trajectory_variant or '*(unknown)*'} |",
            f"| Frames / animals | {p.n_frames} / {p.n_animals} |",
            f"| Stable identities | {p.has_stable_identities} |",
            f"| Tracking run status | {p.tracking_status or '*(unknown)*'} |",
        ]
        if p.tracking_status == "Failed" and p.tracking_failure_summary:
            lines.append(f"| Tracking failure | {p.tracking_failure_summary} |")
        lines.append(f"| Tracking log warnings | {p.tracking_warnings_count} |")

        def _fmt(v: float | None) -> str:
            return f"{v:.4f}" if v is not None else "*(not reported)*"

        lines += [
            f"| Estimated accuracy | {_fmt(p.estimated_accuracy)} |",
            f"| Fraction identified | {_fmt(p.fraction_identified)} |",
            f"| Silhouette score | {_fmt(p.silhouette_score)} |",
            f"| Fragment connectivity | {_fmt(p.fragment_connectivity)} |",
        ]

        if p.length_unit is not None:
            confirmation = (
                "confirmed by user" if p.length_unit_confirmed_by_user
                else "**default, not confirmed** -- idtracker.ai does not "
                     "record which physical unit the Validator's Length "
                     "Calibration tool actually used; verify before "
                     f"trusting any *_{p.length_unit_label} column"
            )
            lines.append(
                f"| Length calibration factor | {p.length_unit:.6g} px per "
                f"{p.length_unit_label} ({confirmation}) |"
            )
        else:
            lines.append("| Length calibration factor | *(not calibrated)* |")

        reliability = (
            "acknowledged reliable" if p.body_length_reliable
            else "**not** acknowledged reliable -- depends on segmentation "
                 "parameters and video conditions (idtracker.ai's own caveat)"
        )
        lines.append(f"| Body-length reliability | {reliability} |")

        if p.blob_body_length_source_file:
            lines.append(
                f"| Body-length source | per-identity, from `{p.blob_body_length_source_file}` |"
            )
        else:
            lines.append(
                "| Body-length source | session-wide value broadcast to every "
                "identity (no per-identity blob-layer data) |"
            )

        lines.append("")
        return lines


# ── Registration ──────────────────────────────────────────────────────────────

from track2data.exporters import register as _register  # noqa: E402

_register(ReadmeExporter)

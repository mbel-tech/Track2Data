"""Human-readable run README.md + manifest.json exporter."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from track2data.core.runplan import FusionRunInfo
from track2data.exporters.base import Exporter, ExportPayload, SessionProvenance
from track2data.metrics.availability import view_label


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
        readme_lines += self._native_3d_lines(p.provenance)
        readme_lines += self._camera_view_lines(p.provenance)
        if p.fusion is not None:
            readme_lines += self._fusion_lines(p.fusion)
        readme_lines += _units_lines(p.manifest_json)
        readme_lines += _sparse_slot_lines(p.fish_by_frame)
        readme_lines += _empty_column_lines(p)

        readme_lines += [
            "## Metrics computed",
            "",
        ]
        if all_metric_ids:
            for mid in all_metric_ids:
                readme_lines.append(f"- {mid}")
        else:
            readme_lines.append("*(none)*")

        # A Methods section written from this report alone has to be able to
        # state what was selected but deliberately NOT computed -- listing
        # only the successes silently overstates the analysis.
        skipped = getattr(p, "skipped_metrics", None) or {}
        if skipped:
            readme_lines += [
                "",
                "## Metrics skipped",
                "",
            ]
            for mid, reason in sorted(skipped.items()):
                readme_lines.append(f"- **{mid}**: {reason}")

        preprocess_steps = p.preprocess_report.steps
        readme_lines += [
            "",
            "## Preprocessing steps",
            "",
        ]
        if p.fusion is not None:
            readme_lines += [
                f"The steps of the top session (`{p.fusion.top_session_id}`); the side session "
                f"(`{p.fusion.side_session_id}`) went through the same preprocessing settings "
                "before fusion.",
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
            "session_provenance": {
                k: v
                for k, v in asdict(p.provenance).items()
                if not (k == "native_3d" and v is None)  # only a native 3-D session has it
            },
        }
        if p.fusion is not None:
            manifest_data["run_metadata"]["fusion"] = p.fusion.as_row()

        manifest_path = out_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest_data, indent=2, default=str), encoding="utf-8"
        )

        return [readme_path, manifest_path]

    @staticmethod
    def _camera_view_lines(p: SessionProvenance) -> list[str]:
        """The camera view the project declared and, when a depth metric was computed, the
        water column it was measured against. Written only when there is something to say, so
        a run from a project that never declared a view keeps its README exactly as it was."""
        if p.camera_view == "unknown" and p.water_column is None:
            return []
        lines = ["## Camera view", "", "| Field | Value |", "|-------|-------|"]
        if p.camera_view != "unknown":
            label = view_label(p.camera_view)
            lines.append(f"| Camera view | {label[0].upper() + label[1:]} |")
        if p.water_column is not None:
            top, bottom = p.water_column.get("top_px"), p.water_column.get("bottom_px")
            source = p.water_column.get("source")
            if top is None or bottom is None:
                lines.append(f"| Water column | none ({source}) |")
            else:
                lines.append(f"| Water column | rows {top:g} to {bottom:g} px ({source}) |")
        lines.append("")
        return lines

    @staticmethod
    def _native_3d_lines(p: SessionProvenance) -> list[str]:
        """The native 3-D block: how a session read from an Anipose or DLC-3D file became
        positions in the project's unit. Written for native sessions only."""
        n = p.native_3d
        if not n:
            return []
        wc = n.get("water_column")
        unit = n.get("target_unit") or p.length_unit_label
        if wc:
            water = f"surface z {wc['surface_z']:g} {unit}, floor z {wc['floor_z']:g} {unit}"
        else:
            water = "*(not set)*"
        return [
            "## Native 3-D source",
            "",
            "| Field | Value |",
            "|-------|-------|",
            f"| Reader | `{p.reader}` |",
            f"| File unit | {n.get('source_unit') or '*(not recorded)*'} |",
            f"| Project unit | {unit} |",
            f"| Vertical axis | {n.get('vertical_axis') or '*(not recorded)*'} |",
            f"| Flipped | {n.get('flip', False)} |",
            f"| Water column | {water} |",
            *(
                [
                    f"| Samples outside the water column | {n['outside_samples']} "
                    "(left out of IL-15, IL-16, IL-17, IL-18 and GL-16, never clipped) |"
                ]
                if n.get("outside_samples") is not None
                else []
            ),
            "",
        ]

    @staticmethod
    def _fusion_lines(f: FusionRunInfo) -> list[str]:
        """How a pair unit was fused: the settings, what was fused and left out, and how well
        the two views agreed. Written for pair units only."""
        if f.fusion_agreement_rms_cm is not None:
            agreement = f"{f.fusion_agreement_rms_cm:.4g} cm"
            if f.fusion_agreement_warning:
                agreement += " (**above the warning threshold**)"
        else:
            why = f.fusion_agreement_skipped or "no reason recorded"
            agreement = f"*(not computed: {table_cell(why)})*"
        return [
            "## 3-D fusion",
            "",
            "| Field | Value |",
            "|-------|-------|",
            f"| Unit | pair of top `{f.top_session_id}` and side `{f.side_session_id}` |",
            f"| Side trajectory SHA-256 | `{f.side_trajectory_sha256 or '(not computed)'}` |",
            f"| Frame offset | {f.fusion_frame_offset} |",
            f"| Horizontal axis | {f.fusion_axis} |",
            f"| Flipped | {f.fusion_flip} |",
            f"| Surface row | {f.fusion_surface_row:g} px |",
            f"| Floor row | {f.fusion_floor_row:g} px |",
            f"| Tank height | {f.fusion_tank_height_cm:g} cm |",
            f"| Overlapping frames | {f.fusion_overlap_frames} |",
            f"| Fish fused | {f.fusion_fused_fish} |",
            f"| Top fish left out | {table_cell(f.fusion_unmatched_top) or '*(none)*'} |",
            f"| Side fish left out | {table_cell(f.fusion_unmatched_side) or '*(none)*'} |",
            f"| Positions outside the water column | {f.fusion_outside_column} |",
            f"| Agreement RMS | {agreement} |",
            "",
            "The trajectory checksum in `sessions.csv` is the top session's; "
            "`side_trajectory_sha256` is the side session's.",
            "",
        ]

    @staticmethod
    def _provenance_lines(prov: object) -> list[str]:
        """Render how a session was tracked and read: its values, not just their names.

        A session from idtracker.ai (or one whose reader was never recorded, which is every
        payload built before other trackers could be read) gets the idtracker.ai section. A
        session from any other tracker gets the source-software section, which claims nothing
        about idtracker.ai.
        """
        p: SessionProvenance = prov  # type: ignore[assignment]
        if _is_idtracker(p):
            return ReadmeExporter._idtracker_lines(p)
        return ReadmeExporter._source_software_lines(p)

    @staticmethod
    def _idtracker_lines(p: SessionProvenance) -> list[str]:
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
            f"| Tracked without identification | {_tri(p.track_wo_identities)} |",
            f"| Treated as identity-free | {p.identity_free_effective} "
            f"({p.identity_free_source}) |",
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

        lines.append(
            _calibration_row(
                p,
                unconfirmed="**default, not confirmed** -- idtracker.ai does not "
                "record which physical unit the Validator's Length "
                "Calibration tool actually used; verify before "
                f"trusting any *_{p.length_unit_label} column",
            )
        )

        if p.length_calibration_n:
            spread = (
                f"relative SD {p.length_calibration_rel_sd:.2%}"
                if p.length_calibration_rel_sd is not None
                else "single measurement, no spread estimate"
            )
            lines.append(
                f"| Length calibration clicks | {p.length_calibration_n} ({spread}) |"
            )

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

        if p.reader_options:
            lines.append(
                f"| Reader options (given by the user, not recorded in the files) | "
                f"{_options_cell(p.reader_options)} |"
            )
        lines.append(
            f"| Last validated | {p.last_validated or '*(never opened in the Validator)*'} |"
        )
        lines.append(
            f"| idtracker.ai data policy | {p.data_policy or '*(not reported)*'} |"
        )

        lines.append("")
        return lines

    @staticmethod
    def _source_software_lines(p: SessionProvenance) -> list[str]:
        """Render what is known about a session from any tracker other than idtracker.ai.

        Says which software and reader produced the numbers, whether that reader has been
        tested against real output, who chose it and with which options, and which file it
        read -- the facts a Methods section needs and the numbers do not show. Only file
        *names* are listed: a path would put the user's directory layout into a document that
        is meant to be shared.
        """
        return [
            "## Source software provenance",
            "",
            "| Field | Value |",
            "|-------|-------|",
            f"| Software | {table_cell(p.source_software or p.reader or '*(unknown)*')} |",
            f"| Reader | {table_cell(p.reader or '*(unknown)*')} |",
            f"| Reader verification | {_verification_cell(p.reader_verification)} |",
            f"| Reader chosen | {_chosen_cell(p.reader_chosen_by, p.detection_confidence)} |",
            f"| Reader options | {_options_cell(p.reader_options)} |",
            f"| Source file(s) | {_files_cell(p.source_files)} |",
            f"| Frames / animals | {p.n_frames} / {p.n_animals} |",
            *_position_rows(p),
            f"| Stable identities | {p.has_stable_identities} |",
            f"| Tracked without identification | {_tri(p.track_wo_identities)} |",
            f"| Treated as identity-free | {p.identity_free_effective} "
            f"({p.identity_free_source}) |",
            # a native 3-D file has no pixels: its unit is in the "Native 3-D source" block
            *(
                []
                if p.native_3d
                else [
                    _calibration_row(
                        p,
                        unconfirmed="**not confirmed** -- check the physical unit before "
                        f"trusting any *_{p.length_unit_label} column",
                    )
                ]
            ),
            "",
        ]


# ── Provenance cells ──────────────────────────────────────────────────────────

# How many source files a README lists before counting the rest.
_MAX_FILES_SHOWN = 5

_VERIFICATION = {
    "real_sample": "tested against real tracker output",
    "synthetic_only": (
        "**unverified** -- written from the format's documentation and tested on synthetic "
        "files only; compare a few trajectories with the tracker's own output before "
        "relying on the numbers"
    ),
}

_CHOSEN_BY = {"detected": "detected automatically", "user": "chosen by the user"}


#: A slot with more than this share of its frames missing gets a line in the README.
_SPARSE_SLOT_SHARE = 0.9


def _units_lines(manifest_json: str) -> list[str]:
    """Say why the centimetre columns are empty when the project calibrates by body length.

    That mode fills the ``*_bl`` (body lengths) and ``*_px`` columns and leaves ``*_cm`` empty
    on purpose: no pixels-per-cm value is set. Nothing else in the output says so.
    """
    try:
        calibration = json.loads(manifest_json).get("calibration") or {}
    except (json.JSONDecodeError, TypeError, AttributeError):
        return []
    if calibration.get("mode") != "bodylength":
        return []
    return [
        "## Units",
        "",
        "Calibration is 'bodylength': distances and speeds are given in pixels (`*_px`) and in "
        "body lengths (`*_bl`). The centimetre columns (`*_cm`) are empty (NaN) because no "
        "pixels-per-cm value is set. For centimetres choose 'scalar' calibration and give "
        "pixels per cm, or 'session' calibration where the tracker records its own length unit.",
        "",
    ]


def _sparse_slot_lines(fish_by_frame: pd.DataFrame) -> list[str]:
    """List identity slots that are almost always missing (idtracker.ai allocates slots up
    front, so a run with fewer animals than slots leaves some empty)."""
    df = fish_by_frame
    column = next((c for c in ("x_px", "x") if c in df.columns), None)
    if column is None or "individual_id" not in df.columns or len(df) == 0:
        return []
    share = df[column].isna().groupby(df["individual_id"]).mean()
    sparse = share[share > _SPARSE_SLOT_SHARE]
    if sparse.empty:
        return []
    lines = [
        "## Identity slots with little data",
        "",
        f"These slots have a position in fewer than {1 - _SPARSE_SLOT_SHARE:.0%} of their frames; "
        "their metrics are mostly NaN.",
        "",
        "| Slot | Frames missing |",
        "|------|----------------|",
    ]
    lines += [f"| {slot} | {value:.1%} |" for slot, value in sparse.items()]
    lines.append("")
    return lines


_FRAGMENTS_REASON = (
    "needs preprocessing/list_of_fragments.json, which a bare trajectory export lacks"
)

#: Why a diagnostic's columns can be entirely NaN, keyed by metric id. Each reason was checked
#: against where the metric reads its input (``metrics/diagnostic.py`` and the idtracker.ai reader).
_EMPTY_COLUMN_REASONS = {
    "D-2": "the trajectory file records no estimated_accuracy or fraction_identified",
    "D-3": "the export has no id_probabilities",
    "D-5": "the trajectory file records no fraction_identified",
    "D-6": "needs session.json (number_of_error_frames), which a bare trajectory export lacks",
    "D-7": _FRAGMENTS_REASON,
    "D-8": _FRAGMENTS_REASON,
    "D-9": _FRAGMENTS_REASON,
    "D-12": (
        "the trajectory file records no silhouette_score or fragment_connectivity "
        "(idtracker.ai writes them only to some exports)"
    ),
    "D-13": _FRAGMENTS_REASON,
    "D-14": _FRAGMENTS_REASON,
    "D-15": (
        "needs the tracker's blob table (preprocessing/list_of_blobs.pickle), which is read only "
        "when the project enables blob diagnostics and allows pickle loading"
    ),
}
_GENERIC_EMPTY_REASON = "no valid values in this session (all frames NaN after preprocessing)"


def _empty_column_lines(p: ExportPayload) -> list[str]:
    """List the metric columns that hold no value at all, each with the reason it can be empty.

    Only columns that are NaN in every row of a non-empty table count; a column with a single
    value is not listed. The reason comes from the metric id, except ``*_cm`` columns, which the
    Units section explains.
    """
    try:
        calibration = json.loads(p.manifest_json).get("calibration") or {}
        bodylength = calibration.get("mode") == "bodylength"
    except (json.JSONDecodeError, TypeError, AttributeError):
        bodylength = False

    rows: list[str] = []
    for tables in (p.individual_metrics, p.group_metrics, p.zone_metrics, p.diagnostic_metrics):
        for mid, df in tables.items():
            if len(df) == 0:
                continue
            by_reason: dict[str, list[str]] = {}
            for column in df.columns:
                if not df[column].isna().all():
                    continue
                if bodylength and re.search(r"_cm(_s)?$", str(column)):
                    reason = "empty on purpose under body-length calibration; see the Units section"
                else:
                    reason = _EMPTY_COLUMN_REASONS.get(mid, _GENERIC_EMPTY_REASON)
                by_reason.setdefault(reason, []).append(f"`{column}`")
            rows += [
                f"| {mid} | {', '.join(columns)} | {reason} |"
                for reason, columns in by_reason.items()
            ]
    if not rows:
        return []
    return [
        "## Columns with no values",
        "",
        "These metric columns are NaN in every row of this run.",
        "",
        "| Metric | Columns | Why |",
        "|--------|---------|-----|",
        *rows,
        "",
    ]


def _is_idtracker(p: SessionProvenance) -> bool:
    """Whether to describe *p* with the idtracker.ai section.

    A provenance with no reader recorded is read as idtracker.ai: that is every payload built
    before another tracker could be read, and their README must not change.
    """
    return not p.reader or p.reader.startswith("idtrackerai")


def _tri(v: bool | None) -> str:
    return "*(not reported)*" if v is None else str(v)


def table_cell(text: str) -> str:
    """Make *text* safe inside a Markdown table cell."""
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _verification_cell(verification: str | None) -> str:
    if verification is None:
        return "*(not recorded)*"
    return _VERIFICATION.get(verification, table_cell(verification))


def _chosen_cell(chosen_by: str | None, confidence: str | None) -> str:
    if not chosen_by:
        return "*(not recorded)*"
    who = _CHOSEN_BY.get(chosen_by, chosen_by)
    return table_cell(f"{who} (detection confidence {confidence})" if confidence else who)


def _options_cell(options: dict[str, object]) -> str:
    if not options:
        return "*(none)*"
    return table_cell(", ".join(f"{name}={value}" for name, value in sorted(options.items())))


def _position_rows(p: SessionProvenance) -> list[str]:
    """The row saying which keypoint stood for the animal (pose trackers only)."""
    s = p.keypoint_selection
    if not s:
        return []
    how = "chosen by the user" if s.get("chosen_by") == "user" else "best coverage"
    cutoff = s.get("cutoff")
    cut = f"likelihood cutoff {cutoff:g}" if cutoff is not None else "no likelihood cutoff"
    plane = ", ".join(s.get("plane") or ("x", "y"))
    n = s["n_keypoints"]
    text = (
        f"keypoint `{s['keypoint']}` ({how}; {cut}; present in {100 * s['coverage']:.1f} % "
        f"of frames and animals; plane {plane}). The file has {n} keypoints; the others are "
        "stored but no metric uses them"
    )
    return [f"| Animal position | {table_cell(text)} |"]


def _files_cell(files: tuple[str, ...]) -> str:
    if not files:
        return "*(not recorded)*"
    names = [f"`{Path(f).name or f}`" for f in files[:_MAX_FILES_SHOWN]]
    if len(files) > _MAX_FILES_SHOWN:
        names.append(f"+{len(files) - _MAX_FILES_SHOWN} more")
    return table_cell(", ".join(names))


def _calibration_row(p: SessionProvenance, *, unconfirmed: str) -> str:
    """The calibration-factor row; *unconfirmed* says why an unconfirmed factor is not trusted."""
    if p.length_unit is None:
        return "| Length calibration factor | *(not calibrated)* |"
    confirmation = "confirmed by user" if p.length_unit_confirmed_by_user else unconfirmed
    return (
        f"| Length calibration factor | {p.length_unit:.6g} px per "
        f"{p.length_unit_label} ({confirmation}) |"
    )


# ── Registration ──────────────────────────────────────────────────────────────

from track2data.exporters import register as _register  # noqa: E402

_register(ReadmeExporter)

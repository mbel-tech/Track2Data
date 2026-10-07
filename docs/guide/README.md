# Track2Data user guide

Track2Data turns [idtracker.ai](https://idtracker.ai) output folders into clean, calibrated,
analysis-ready tables. This guide walks through the desktop app one screen at a time, with
screenshots of a small demo project (two fish in a circular arena).

> The screenshots are generated from the real app by
> [`scripts/generate_guide_screenshots.py`](../../scripts/generate_guide_screenshots.py), so they
> match the current version. In the app, **Help ▸ Open user guide** brings you here.

## Install and start

```bash
pip install "track2data[ui]"   # or, from a clone: pip install -e ".[ui]"
track2data-gui
```

Only need the command line? `pip install track2data` gives you `track2data run project.t2d.json`
(see [`track2data --help`](../../README.md#installation)).

## The workflow

The left sidebar lists the stages. A badge shows where each one stands:

| Badge | Meaning |
|---|---|
| ✓ | complete |
| ⚠ | usable, but look at the tooltip (e.g. a session has no stable identities) |
| ✗ | must be fixed before you can continue |
| ○ | nothing entered yet (optional stages stay ○) |

**Settings save themselves.** There are no Apply buttons: a change is stored a moment after you
make it, and again when you leave the screen. **Next ▶** stays disabled, with a tooltip saying why,
until Project, Sessions and Metrics are filled in and the calibration is valid.

| # | Screen | What you do |
|---|---|---|
| 1 | [Project](01-project.md) | Create or open a project |
| 2 | [Sessions](02-sessions.md) | Add idtracker.ai output folders |
| 3 | [Calibration](03-calibration.md) | Choose how pixels become body lengths or cm |
| 4 | [Zones](04-zones.md) | Draw regions of interest (optional) |
| 5 | [Metadata](05-metadata.md) | Attach treatment, date, … from a CSV (optional) |
| 6 | [Preprocessing](06-preprocessing.md) | Gap filling, jump removal, smoothing |
| 7 | [Metrics](07-metrics.md) | Pick what to compute |
| 8 | [Processing](08-processing.md) | Run the pipeline |
| 9 | [Preview](09-preview.md) | Check trajectories, diagnostics and metric tables |
| 10 | [Export](10-export.md) | Write CSV / Feather / Excel and load them in R or Python |

Also: [Understanding the output files](outputs.md) · [Troubleshooting](troubleshooting.md).

## Quick start (five minutes)

1. **File ▸ New project…**, name it. You land on *Sessions*.
2. **Add Folders…** and choose one or more idtracker.ai session folders.
3. Leave *Calibration* on **Body length** unless you know your pixels-per-cm.
4. On *Metrics*, pick a preset such as **Standard locomotor**.
5. **▶ Run pipeline**, then look at **Preview ▸ Trajectories** to confirm tracking looks right.
6. On *Export*, tick the formats you want and **Export**.

Do step 5 before trusting any number: the trajectory view is the quickest way to spot identity
swaps, tracking gaps and over-aggressive smoothing.
